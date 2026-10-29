import json
import time
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, status
from pydantic import Field
from sqlalchemy import case, func, select

from app.api.deps import RedisDep, SessionDep, SettingsDep, SmDep
from app.api.schemas import TestNotificationIn
from app.config import IST
from app.db.models import Alert, AlertEvent, AlertStatus, Instrument
from app.engine.poll import STATUS_KEY, get_runtime
from app.marketdata.base import Tick, to_price
from app.marketdata.cache import DEV_TICKS_CHANNEL, ENGINE_STATUS_KEY
from app.notify import build_senders
from app.notify.base import SendError
from app.notify.formatter import sample_message
from app.runtime.store import PgStore

router = APIRouter(tags=["system"])


@router.get("/system/status")
async def system_status(session: SessionDep, redis: RedisDep, settings: SettingsDep,
                        sm: SmDep):
    engine = poll = None
    if settings.run_mode == "cron":
        poll = await PgStore(sm).read_state(STATUS_KEY)
    elif redis is not None and (raw := await redis.hgetall(ENGINE_STATUS_KEY)):
        engine = {
            "provider": raw.get("provider"),
            "connected": raw.get("connected") == "1",
            "market_window_open": raw.get("market_window_open") == "1",
            "market_status": json.loads(raw.get("market_status") or "{}"),
            "subscriptions": int(raw.get("subscriptions") or 0),
            "active_rules": int(raw.get("active_rules") or 0),
            "last_tick_at": float(raw.get("last_tick_at") or 0) or None,
            "heartbeat_age_sec": round(time.time() - float(raw.get("heartbeat") or 0), 1),
        }
    counts = (
        await session.execute(
            select(
                func.count(case((Alert.status == AlertStatus.ACTIVE, 1))),
                func.count(case((Alert.status == AlertStatus.TRIGGERED, 1))),
            )
        )
    ).one()
    today = datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0)
    fired_today = await session.scalar(
        select(func.count()).select_from(AlertEvent).where(AlertEvent.triggered_at >= today)
    )
    expires = settings.upstox_token_expires_on
    return {
        "mode": settings.run_mode,
        "engine": engine,
        "poll": poll,
        "provider": settings.market_data_provider,
        "upstox_token_set": bool(settings.upstox_analytics_token),
        "upstox_token_expires_on": expires.isoformat() if expires else None,
        "upstox_token_days_left": (expires - datetime.now(IST).date()).days if expires else None,
        "channels": {
            "TELEGRAM": settings.telegram_enabled,
            "WHATSAPP": settings.whatsapp_enabled,
        },
        "alerts": {"active": counts[0], "triggered": counts[1], "fired_today": fired_today or 0},
    }


@router.post("/system/test-notification")
async def test_notification(body: TestNotificationIn, settings: SettingsDep):
    sender = build_senders(settings).get(body.channel.upper())
    if sender is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{body.channel} is not configured")
    try:
        message_id = await sender.send_alert(sample_message())
    except SendError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))
    return {"ok": True, "provider_message_id": message_id}


@router.post("/dev/ticks")
async def inject_ticks(session: SessionDep, redis: RedisDep, settings: SettingsDep, sm: SmDep,
                       prices: dict[str, Annotated[Decimal, Field(gt=0)]] = Body(
                           examples=[{"RELIANCE": 1502, "NSE_EQ|INE040A01034": 1650.5}])):
    """Simulated mode only: push exact prices, keyed by NSE symbol or instrument_key."""
    if settings.market_data_provider != "simulated":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only available with the simulated provider")
    resolved = []
    for ref, price in prices.items():
        if "|" in ref:
            key = ref if await session.get(Instrument, ref) else None
        else:
            key = await session.scalar(
                select(Instrument.instrument_key)
                .where(func.upper(Instrument.trading_symbol) == ref.upper())
                .order_by(case((Instrument.segment == "NSE_EQ", 0), else_=1))
                .limit(1)
            )
        if key is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown instrument {ref}")
        resolved.append({"k": key, "p": str(price)})
    if settings.run_mode == "cron":
        # No live engine to relay to: evaluate and deliver right here.
        ticks = [Tick(r["k"], to_price(r["p"])) for r in resolved]
        result = await get_runtime(settings, sm).process_ticks(ticks)
        return {"published": resolved, **result}
    await redis.publish(DEV_TICKS_CHANNEL, json.dumps(resolved))
    return {"published": resolved}
