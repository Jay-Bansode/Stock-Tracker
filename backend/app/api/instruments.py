from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import case, func, select

from app.api.deps import SessionDep, StoreDep
from app.api.schemas import InstrumentOut
from app.db.models import Instrument

router = APIRouter(tags=["instruments"])


def _escape_like(q: str) -> str:
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("/instruments/search", response_model=list[InstrumentOut])
async def search_instruments(
    session: SessionDep,
    q: Annotated[str, Query(min_length=1, max_length=50)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
):
    q = q.strip()
    text = Instrument.trading_symbol + " " + Instrument.name  # matches the trigram index expression
    rows = await session.scalars(
        select(Instrument)
        .where(text.ilike(f"%{_escape_like(q)}%", escape="\\"))
        .order_by(
            case((func.upper(Instrument.trading_symbol) == q.upper(), 0), else_=1),
            case((Instrument.trading_symbol.ilike(f"{_escape_like(q)}%", escape="\\"), 0), else_=1),
            case((Instrument.segment == "NSE_EQ", 0), (Instrument.segment == "NSE_INDEX", 1),
                 else_=2),
            func.length(Instrument.trading_symbol),
            Instrument.trading_symbol,
        )
        .limit(limit)
    )
    return [InstrumentOut.model_validate(r) for r in rows]


@router.get("/quotes")
async def quotes(store: StoreDep, keys: Annotated[str, Query(max_length=20000)]):
    """Latest cached prices: {instrument_key: {k, p (ltp), c (prev close), t (ms)}}."""
    return await store.get_prices([k for k in keys.split(",") if k])
