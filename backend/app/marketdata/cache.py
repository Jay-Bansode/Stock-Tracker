"""Redis layout shared by engine (writer) and api (reader)."""

import json
import time
from decimal import Decimal

from redis.asyncio import Redis

from app.marketdata.base import Tick

PRICE_KEY = "tracker:price:{}"
TICKS_CHANNEL = "tracker:ticks"
DEV_TICKS_CHANNEL = "tracker:dev_ticks"
ENGINE_STATUS_KEY = "tracker:engine"


def tick_payload(t: Tick) -> dict:
    return {
        "k": t.instrument_key,
        "p": float(t.ltp),
        "c": float(t.close) if t.close is not None else None,
        "t": int(t.ts.timestamp() * 1000) if t.ts else int(time.time() * 1000),
    }


async def publish_ticks(redis: Redis, ticks: list[Tick]) -> None:
    payload = [tick_payload(t) for t in ticks]
    pipe = redis.pipeline(transaction=False)
    for p in payload:
        fields = {"ltp": p["p"], "ts": p["t"]}
        if p["c"] is not None:
            fields["close"] = p["c"]
        pipe.hset(PRICE_KEY.format(p["k"]), mapping=fields)
    pipe.publish(TICKS_CHANNEL, json.dumps(payload))
    await pipe.execute()


async def get_prices(redis: Redis, keys: list[str]) -> dict[str, dict]:
    if not keys:
        return {}
    pipe = redis.pipeline(transaction=False)
    for k in keys:
        pipe.hgetall(PRICE_KEY.format(k))
    out = {}
    for k, h in zip(keys, await pipe.execute(), strict=True):
        if h and h.get("ltp"):
            out[k] = {
                "k": k,
                "p": float(h["ltp"]),
                "c": float(h["close"]) if h.get("close") else None,
                "t": int(h.get("ts") or 0),
            }
    return out


async def get_ltp(redis: Redis, key: str) -> Decimal | None:
    value = await redis.hget(PRICE_KEY.format(key), "ltp")
    return Decimal(value) if value else None
