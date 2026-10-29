import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.deps import COOKIE_NAME, user_from_token
from app.config import get_settings
from app.marketdata.cache import TICKS_CHANNEL, get_prices

router = APIRouter()
log = logging.getLogger(__name__)

FLUSH_SECONDS = 1.0  # at most one update per instrument per second to the browser


@router.websocket("/ws/prices")
async def prices_ws(ws: WebSocket):
    """Client sends {"subscribe": [instrument_key, ...]} (replacing the previous set) and receives
    {"type": "snapshot"|"ticks", "prices": [{k, p, c, t}, ...]}."""
    if user_from_token(get_settings(), ws.cookies.get(COOKIE_NAME)) is None:
        await ws.close(code=4401)
        return
    redis = ws.app.state.redis
    if redis is None:  # cron mode: no live stream, the dashboard polls /api/quotes instead
        await ws.close(code=4404)
        return
    await ws.accept()
    keys: set[str] = set()
    pending: dict[str, dict] = {}
    pubsub = redis.pubsub()
    await pubsub.subscribe(TICKS_CHANNEL)

    async def reader():
        nonlocal keys
        while True:
            msg = await ws.receive_json()
            if isinstance(msg, dict) and isinstance(msg.get("subscribe"), list):
                keys = {str(k) for k in msg["subscribe"]}
                snapshot = await get_prices(redis, sorted(keys))
                await ws.send_json({"type": "snapshot", "prices": list(snapshot.values())})

    async def pump():
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            for tick in json.loads(message["data"]):
                if tick["k"] in keys:
                    pending[tick["k"]] = tick

    async def flusher():
        while True:
            await asyncio.sleep(FLUSH_SECONDS)
            if pending:
                batch = list(pending.values())
                pending.clear()
                await ws.send_json({"type": "ticks", "prices": batch})

    tasks = [asyncio.create_task(c()) for c in (reader, pump, flusher)]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in done:
            exc = t.exception()
            if exc and not isinstance(exc, WebSocketDisconnect):
                log.warning("price socket closed with error: %r", exc)
    finally:
        for t in tasks:
            t.cancel()
        await pubsub.aclose()
