import asyncio
import gzip
import logging
import os
import tempfile
from datetime import UTC, datetime, timedelta

import httpx
import ijson
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models import Instrument
from app.marketdata.seed import ensure_seed_instruments

log = logging.getLogger(__name__)

KEEP_SEGMENTS = {"NSE_EQ", "BSE_EQ", "NSE_INDEX", "BSE_INDEX"}
UPSERT_CHUNK = 1000
FRESH_FOR = timedelta(hours=20)


def instrument_row(r: dict) -> dict | None:
    segment = r.get("segment")
    key = r.get("instrument_key")
    symbol = r.get("trading_symbol") or r.get("tradingsymbol")
    if segment not in KEEP_SEGMENTS or not key or not symbol:
        return None
    return {
        "instrument_key": key,
        "trading_symbol": symbol[:64],
        "name": (r.get("short_name") or r.get("name") or symbol)[:255],
        "exchange": r.get("exchange") or segment.split("_")[0],
        "segment": segment,
        "instrument_type": (r.get("instrument_type") or "")[:16],
        "isin": r.get("isin"),
    }


def parse_instruments(rows: list[dict]) -> list[dict]:
    return [row for r in rows if (row := instrument_row(r))]


def _parse_file(path: str) -> list[dict]:
    """Stream-parse the gzipped master. The NSE file is mostly F&O contracts we drop, so
    parsing item by item keeps memory small (fits a 512 MB free-tier instance)."""
    with gzip.open(path, "rb") as fh:
        return [row for r in ijson.items(fh, "item") if (row := instrument_row(r))]


async def _upsert(sm: async_sessionmaker[AsyncSession], rows: list[dict]) -> None:
    async with sm() as session:
        for i in range(0, len(rows), UPSERT_CHUNK):
            stmt = insert(Instrument).values(rows[i : i + UPSERT_CHUNK])
            stmt = stmt.on_conflict_do_update(
                index_elements=[Instrument.instrument_key],
                set_={
                    "trading_symbol": stmt.excluded.trading_symbol,
                    "name": stmt.excluded.name,
                    "exchange": stmt.excluded.exchange,
                    "segment": stmt.excluded.segment,
                    "instrument_type": stmt.excluded.instrument_type,
                    "isin": stmt.excluded.isin,
                    "updated_at": func.now(),
                },
            )
            await session.execute(stmt)
        await session.commit()


async def sync_instruments(sm: async_sessionmaker[AsyncSession], settings: Settings,
                           client: httpx.AsyncClient | None = None) -> int:
    """Download Upstox's public instrument master and upsert equities + indices."""
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=120, follow_redirects=True)
    total = 0
    try:
        for exchange in settings.instrument_exchanges:
            url = settings.upstox_instruments_url.format(exchange=exchange)
            fd, path = tempfile.mkstemp(suffix=".json.gz")
            try:
                with os.fdopen(fd, "wb") as out:
                    async with client.stream("GET", url) as resp:
                        resp.raise_for_status()
                        async for chunk in resp.aiter_bytes(1 << 16):
                            out.write(chunk)
                rows = await asyncio.to_thread(_parse_file, path)
            finally:
                os.unlink(path)
            await _upsert(sm, rows)
            log.info("synced %d instruments from %s", len(rows), exchange)
            total += len(rows)
    finally:
        if own_client:
            await client.aclose()
    return total


async def last_synced_at(sm: async_sessionmaker[AsyncSession]) -> datetime | None:
    async with sm() as session:
        return await session.scalar(select(func.max(Instrument.updated_at)))


async def refresh_instruments(sm: async_sessionmaker[AsyncSession], settings: Settings, *,
                              download: bool = True, force: bool = False) -> str:
    """Make sure the stock list exists: download it if stale (or forced), and fall back to the
    built-in seed list if the table is still empty (e.g. offline)."""
    result = "fresh"
    last = await last_synced_at(sm)
    if download and (force or last is None or datetime.now(UTC) - last > FRESH_FOR):
        try:
            result = f"synced {await sync_instruments(sm, settings)}"
        except Exception as exc:
            log.warning("instrument sync failed: %s", exc)
            result = f"sync failed: {exc}"
    if await last_synced_at(sm) is None:
        result += f"; seeded {await ensure_seed_instruments(sm)}"
    return result
