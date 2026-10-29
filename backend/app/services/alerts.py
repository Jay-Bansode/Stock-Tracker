from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import func

from app.db.models import (
    Alert,
    AlertEvent,
    AlertStatus,
    Instrument,
    Notification,
    NotificationKind,
    NotificationStatus,
    SystemState,
    TriggerMode,
    Watchlist,
    WatchlistItem,
)
from app.db.session import CHANNEL_OUTBOX, notify


async def trigger_alert(
    sm: async_sessionmaker[AsyncSession],
    alert_id: int,
    price: Decimal,
    exchange_ts: datetime | None,
    channels: list[str],
) -> int | None:
    """Fire one alert exactly once. Returns the new alert_events id, or None if it was not ACTIVE.

    The conditional UPDATE is the dedupe guarantee: concurrent or repeated ticks race on the row
    lock, and only the transaction that flips ACTIVE -> TRIGGERED gets a row back. The history
    event and one outbox row per channel are written in that same transaction.
    """
    async with sm() as session, session.begin():
        won = await session.scalar(
            update(Alert)
            .where(Alert.id == alert_id, Alert.status == AlertStatus.ACTIVE)
            .values(
                status=AlertStatus.TRIGGERED,
                last_triggered_at=func.now(),
                last_trigger_price=price,
                trigger_count=Alert.trigger_count + 1,
                updated_at=func.now(),
            )
            .returning(Alert.id)
        )
        if won is None:
            return None

        ctx = (
            await session.execute(
                select(Alert, Watchlist, Instrument)
                .join(WatchlistItem, Alert.watchlist_item_id == WatchlistItem.id)
                .join(Watchlist, WatchlistItem.watchlist_id == Watchlist.id)
                .join(Instrument, WatchlistItem.instrument_key == Instrument.instrument_key)
                .where(Alert.id == alert_id)
            )
        ).one()
        alert, watchlist, instrument = ctx
        event = AlertEvent(
            alert_id=alert.id,
            watchlist_id=watchlist.id,
            watchlist_name=watchlist.name,
            instrument_key=instrument.instrument_key,
            trading_symbol=instrument.trading_symbol,
            company_name=instrument.name,
            condition=alert.condition,
            target_price=alert.target_price,
            trigger_price=price,
            exchange_ts=exchange_ts,
        )
        session.add(event)
        await session.flush()
        for channel in channels:
            session.add(
                Notification(
                    alert_event_id=event.id,
                    kind=NotificationKind.ALERT,
                    channel=channel,
                    status=NotificationStatus.PENDING,
                )
            )
        if channels:
            await notify(session, CHANNEL_OUTBOX)
        return event.id


async def rearm_repeat_alert(sm: async_sessionmaker[AsyncSession], alert_id: int) -> bool:
    async with sm() as session, session.begin():
        result = await session.scalar(
            update(Alert)
            .where(
                Alert.id == alert_id,
                Alert.status == AlertStatus.TRIGGERED,
                Alert.trigger_mode == TriggerMode.REPEAT,
            )
            .values(status=AlertStatus.ACTIVE, updated_at=func.now())
            .returning(Alert.id)
        )
        return result is not None


async def send_system_once(sm: async_sessionmaker[AsyncSession], reason: str, text: str,
                           channels: list[str], every: timedelta) -> bool:
    """Queue a system message at most once per `every`, tracked in the database so it holds
    across stateless cron requests and restarts. Returns True if it was queued."""
    stmt = insert(SystemState).values(key=f"notice:{reason}", value={"text": text[:500]})
    stmt = stmt.on_conflict_do_update(
        index_elements=[SystemState.key],
        set_={"value": stmt.excluded.value, "updated_at": func.now()},
        where=SystemState.updated_at < func.now() - every,
    ).returning(SystemState.key)
    async with sm() as session, session.begin():
        claimed = await session.scalar(stmt)
    if claimed is None:
        return False
    await enqueue_system_message(sm, f"⚠️ Tracker: {text}", channels)
    return True


async def enqueue_system_message(sm: async_sessionmaker[AsyncSession], text: str,
                                 channels: list[str]) -> None:
    """Operational messages (feed down, token expiring). Telegram only: WhatsApp business-initiated
    messages must use an approved template."""
    channels = [c for c in channels if c == "TELEGRAM"]
    if not channels:
        return
    async with sm() as session, session.begin():
        for channel in channels:
            session.add(
                Notification(
                    kind=NotificationKind.SYSTEM,
                    channel=channel,
                    status=NotificationStatus.PENDING,
                    body=text,
                )
            )
        await notify(session, CHANNEL_OUTBOX)
