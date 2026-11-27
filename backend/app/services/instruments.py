from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Instrument


async def resolve_instrument(session: AsyncSession, ref: str) -> Instrument | None:
    """An instrument by exact instrument_key ("NSE_EQ|INE…") or by trading symbol
    (case-insensitive), preferring the NSE listing when the symbol trades on both exchanges."""
    ref = ref.strip()
    if not ref:
        return None
    if "|" in ref:
        return await session.get(Instrument, ref)
    return await session.scalar(
        select(Instrument)
        .where(func.upper(Instrument.trading_symbol) == ref.upper())
        .order_by(case((Instrument.segment == "NSE_EQ", 0), else_=1), Instrument.instrument_key)
        .limit(1)
    )
