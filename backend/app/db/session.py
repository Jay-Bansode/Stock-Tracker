from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

# LISTEN/NOTIFY channels shared by api, engine and notifier.
CHANNEL_ALERTS_CHANGED = "tracker_alerts_changed"
CHANNEL_OUTBOX = "tracker_outbox"


def make_engine(url: str, pool_size: int = 10) -> AsyncEngine:
    return create_async_engine(url, pool_pre_ping=True, pool_size=pool_size, max_overflow=5)


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    # Free Postgres tiers cap connections; one web process needs only a few.
    return make_engine(settings.database_url, pool_size=3 if settings.run_mode == "cron" else 10)


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session


async def notify(session: AsyncSession, channel: str, payload: str = "") -> None:
    """Queue a pg_notify; Postgres delivers it only when the surrounding transaction commits."""
    await session.execute(text("SELECT pg_notify(:c, :p)"), {"c": channel, "p": payload})
