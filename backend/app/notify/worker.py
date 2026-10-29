import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta

import asyncpg
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import func

from app.config import get_settings
from app.db.models import Notification, NotificationKind, NotificationStatus
from app.db.session import CHANNEL_OUTBOX, get_sessionmaker
from app.logging_setup import setup_logging
from app.notify import build_senders
from app.notify.base import Sender, SendError
from app.notify.formatter import AlertMessage

log = logging.getLogger("app.notify")

BACKOFF_SECONDS = [5, 30, 120, 600, 1800]
POLL_SECONDS = 5
STALE_SENDING = timedelta(minutes=5)
MIN_INTERVAL = {"TELEGRAM": 1.0, "WHATSAPP": 1.0}  # per-chat pacing to stay under provider limits


def backoff_for(attempts: int) -> float:
    return BACKOFF_SECONDS[min(attempts - 1, len(BACKOFF_SECONDS) - 1)]


class ChannelWorker:
    """Drains the outbox for one channel. Channels run independently, so a WhatsApp outage never
    delays Telegram."""

    def __init__(self, sm: async_sessionmaker[AsyncSession], sender: Sender, max_attempts: int,
                 min_interval: float | None = None):
        self._sm = sm
        self._sender = sender
        self.channel = sender.channel
        self._max_attempts = max_attempts
        self._min_interval = MIN_INTERVAL.get(self.channel, 0.0) if min_interval is None else min_interval
        self._last_send = 0.0
        self.wake = asyncio.Event()

    async def recover_stale(self) -> int:
        """Rows stuck in SENDING (worker crashed mid-send) go back to PENDING."""
        async with self._sm() as session, session.begin():
            result = await session.execute(
                update(Notification)
                .where(
                    Notification.channel == self.channel,
                    Notification.status == NotificationStatus.SENDING,
                    Notification.updated_at < func.now() - STALE_SENDING,
                )
                .values(status=NotificationStatus.PENDING, updated_at=func.now())
            )
            return result.rowcount or 0

    async def claim(self, limit: int = 10) -> list[int]:
        async with self._sm() as session, session.begin():
            rows = (
                await session.scalars(
                    select(Notification)
                    .where(
                        Notification.channel == self.channel,
                        Notification.status == NotificationStatus.PENDING,
                        Notification.next_attempt_at <= func.now(),
                    )
                    .order_by(Notification.id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for n in rows:
                n.status = NotificationStatus.SENDING
                n.attempts += 1
            return [n.id for n in rows]

    async def process_batch(self, limit: int = 10) -> int:
        ids = await self.claim(limit)
        for nid in ids:
            await self._deliver(nid)
        return len(ids)

    async def _deliver(self, nid: int) -> None:
        async with self._sm() as session:
            n = await session.get(Notification, nid, options=[selectinload(Notification.event)])
            if n is None:  # its event was deleted in the meantime
                return
            attempts = n.attempts
            kind, body, event = n.kind, n.body, n.event

        await self._pace()
        try:
            if kind == NotificationKind.ALERT:
                if event is None:
                    raise SendError("alert event no longer exists", retryable=False)
                provider_id = await self._sender.send_alert(AlertMessage.from_event(event))
            else:
                provider_id = await self._sender.send_text(body or "")
        except SendError as exc:
            await self._failed(nid, attempts, exc)
            return
        except Exception as exc:  # unexpected bug: retry with backoff rather than drop
            log.exception("unexpected error sending notification %s", nid)
            await self._failed(nid, attempts, SendError(repr(exc), retryable=True))
            return

        async with self._sm() as session, session.begin():
            await session.execute(
                update(Notification)
                .where(Notification.id == nid)
                .values(status=NotificationStatus.SENT, provider_message_id=provider_id,
                        sent_at=func.now(), last_error=None, updated_at=func.now())
            )
        log.info("sent %s notification %s (provider id %s)", self.channel, nid, provider_id)

    async def _failed(self, nid: int, attempts: int, exc: SendError) -> None:
        give_up = not exc.retryable or attempts >= self._max_attempts
        delay = exc.retry_after if exc.retry_after is not None else backoff_for(attempts)
        values = {"last_error": str(exc)[:1000], "updated_at": func.now()}
        if give_up:
            values["status"] = NotificationStatus.FAILED
            log.error("%s notification %s failed permanently: %s", self.channel, nid, exc)
        else:
            values["status"] = NotificationStatus.PENDING
            values["next_attempt_at"] = datetime.now(UTC) + timedelta(seconds=delay)
            log.warning("%s notification %s attempt %d failed, retry in %.0fs: %s",
                        self.channel, nid, attempts, delay, exc)
        async with self._sm() as session, session.begin():
            await session.execute(update(Notification).where(Notification.id == nid).values(**values))

    async def _pace(self) -> None:
        wait = self._last_send + self._min_interval - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_send = time.monotonic()

    async def run(self) -> None:
        last_recovery = 0.0
        while True:
            self.wake.clear()
            try:
                if time.monotonic() - last_recovery > 60:
                    if recovered := await self.recover_stale():
                        log.warning("recovered %d stale %s notifications", recovered, self.channel)
                    last_recovery = time.monotonic()
                handled = await self.process_batch()
            except Exception:
                log.exception("%s worker loop error", self.channel)
                handled = 0
                await asyncio.sleep(POLL_SECONDS)
            if not handled:
                try:
                    await asyncio.wait_for(self.wake.wait(), POLL_SECONDS)
                except TimeoutError:
                    pass


async def main() -> None:
    setup_logging()
    settings = get_settings()
    senders = build_senders(settings)
    if not senders:
        log.warning("no notification channels configured; set TELEGRAM_* and/or WHATSAPP_* in .env")
    sm = get_sessionmaker()
    workers = [ChannelWorker(sm, s, settings.notify_max_attempts) for s in senders.values()]

    conn = await asyncpg.connect(settings.asyncpg_dsn)

    def wake_all(*_):
        for w in workers:
            w.wake.set()

    await conn.add_listener(CHANNEL_OUTBOX, wake_all)
    log.info("notifier running for channels: %s", [w.channel for w in workers] or "none")
    try:
        async with asyncio.TaskGroup() as tg:
            for w in workers:
                tg.create_task(w.run())
            if not workers:
                tg.create_task(asyncio.Event().wait())
    finally:
        await conn.close()
