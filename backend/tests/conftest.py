"""Integration tests run against the compose Postgres/Redis (docker compose up -d postgres redis).

A dedicated `tracker_test` database is created and migrated once per session with Alembic, so the
migration itself is exercised. Tests that need it are skipped when Postgres is unreachable.
"""

import asyncio
import os
from decimal import Decimal

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Alert, Instrument, Watchlist, WatchlistItem

ADMIN_DSN = os.environ.get("TEST_ADMIN_DSN", "postgresql://tracker:tracker@localhost:55432/tracker")
TEST_DB = "tracker_test"
TEST_URL = f"postgresql+asyncpg://tracker:tracker@localhost:55432/{TEST_DB}"
TEST_REDIS = os.environ.get("TEST_REDIS_URL", "redis://localhost:56379/15")
BACKEND_DIR = os.path.dirname(os.path.dirname(__file__))

TABLES = ("notifications, alert_events, alerts, watchlist_items, watchlists, instruments, "
          "quotes, system_state")


async def _prepare_database() -> None:
    conn = await asyncpg.connect(ADMIN_DSN, timeout=5)
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname=$1", TEST_DB)
        if exists:
            await conn.execute(f"DROP DATABASE {TEST_DB} WITH (FORCE)")
        await conn.execute(f"CREATE DATABASE {TEST_DB}")
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def migrated_db():
    try:
        asyncio.run(_prepare_database())
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"Postgres not available: {exc}")
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
    cfg.set_main_option("sqlalchemy.url", TEST_URL)
    command.upgrade(cfg, "head")
    return TEST_URL


@pytest.fixture
async def sm(migrated_db):
    engine = create_async_engine(migrated_db)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def redis():
    client = Redis.from_url(TEST_REDIS, decode_responses=True)
    try:
        await client.ping()
    except Exception as exc:
        pytest.skip(f"Redis not available: {exc}")
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


RELIANCE = "NSE_EQ|INE002A01018"
HDFCBANK = "NSE_EQ|INE040A01034"


@pytest.fixture
async def example(sm):
    """The scenario from the requirements: Reliance in two watchlists, HDFC Bank in a third."""
    async with sm() as s:
        s.add_all([
            Instrument(instrument_key=RELIANCE, trading_symbol="RELIANCE",
                       name="Reliance Industries", exchange="NSE", segment="NSE_EQ",
                       instrument_type="EQ", isin="INE002A01018"),
            Instrument(instrument_key=HDFCBANK, trading_symbol="HDFCBANK", name="HDFC Bank",
                       exchange="NSE", segment="NSE_EQ", instrument_type="EQ",
                       isin="INE040A01034"),
        ])
        ids = {}
        for name, key, target in [
            ("Long-Term Stocks", RELIANCE, "1500"),
            ("Intraday Stocks", RELIANCE, "1480"),
            ("Banking Stocks", HDFCBANK, "1700"),
        ]:
            wl = Watchlist(name=name)
            item = WatchlistItem(watchlist=wl, instrument_key=key)
            alert = Alert(item=item, condition="ABOVE", target_price=Decimal(target),
                          trigger_mode="ONCE", status="ACTIVE")
            s.add_all([wl, item, alert])
            await s.flush()
            ids[name] = alert.id
        await s.commit()
    return ids
