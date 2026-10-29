"""Where the latest prices live: Redis for the always-on Docker stack, Postgres for cron mode
(free hosting has no Redis and no long-lived processes)."""

from decimal import Decimal
from typing import Protocol

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Quote, SystemState
from app.marketdata import cache
from app.marketdata.base import Tick


class PriceStore(Protocol):
    async def publish_ticks(self, ticks: list[Tick]) -> None: ...

    async def get_prices(self, keys: list[str]) -> dict[str, dict]: ...

    async def get_ltp(self, key: str) -> Decimal | None: ...


class RedisStore:
    def __init__(self, redis: Redis):
        self.redis = redis

    async def publish_ticks(self, ticks: list[Tick]) -> None:
        await cache.publish_ticks(self.redis, ticks)

    async def get_prices(self, keys: list[str]) -> dict[str, dict]:
        return await cache.get_prices(self.redis, keys)

    async def get_ltp(self, key: str) -> Decimal | None:
        return await cache.get_ltp(self.redis, key)


class PgStore:
    def __init__(self, sm: async_sessionmaker[AsyncSession]):
        self._sm = sm

    async def publish_ticks(self, ticks: list[Tick]) -> None:
        if not ticks:
            return
        latest = {t.instrument_key: t for t in ticks}  # one row per key per statement
        rows = [
            {"instrument_key": t.instrument_key, "ltp": t.ltp, "close": t.close, "ts": t.ts}
            for t in latest.values()
        ]
        stmt = insert(Quote).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Quote.instrument_key],
            set_={
                "ltp": stmt.excluded.ltp,
                # keep the known previous close when a source doesn't send one
                "close": func.coalesce(stmt.excluded.close, Quote.close),
                "ts": stmt.excluded.ts,
                "updated_at": func.now(),
            },
        )
        async with self._sm() as session:
            await session.execute(stmt)
            await session.commit()

    async def get_prices(self, keys: list[str]) -> dict[str, dict]:
        if not keys:
            return {}
        async with self._sm() as session:
            rows = await session.scalars(select(Quote).where(Quote.instrument_key.in_(keys)))
            return {
                q.instrument_key: {
                    "k": q.instrument_key,
                    "p": float(q.ltp),
                    "c": float(q.close) if q.close is not None else None,
                    "t": int((q.ts or q.updated_at).timestamp() * 1000),
                }
                for q in rows
            }

    async def get_ltp(self, key: str) -> Decimal | None:
        async with self._sm() as session:
            return await session.scalar(select(Quote.ltp).where(Quote.instrument_key == key))

    async def write_state(self, key: str, value: dict) -> None:
        stmt = insert(SystemState).values(key=key, value=value)
        stmt = stmt.on_conflict_do_update(
            index_elements=[SystemState.key],
            set_={"value": stmt.excluded.value, "updated_at": func.now()},
        )
        async with self._sm() as session:
            await session.execute(stmt)
            await session.commit()

    async def read_state(self, key: str) -> dict | None:
        async with self._sm() as session:
            return await session.scalar(select(SystemState.value).where(SystemState.key == key))
