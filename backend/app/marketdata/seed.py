"""Fallback instruments for when the Upstox instrument master can't be downloaded (offline dev).

Keys follow Upstox's SEGMENT|ISIN format so watchlists built on these keep working once the real
master is synced. Prices only seed the simulated provider.
"""

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Instrument

SEED = [
    # instrument_key, symbol, name, segment, type, isin, sim price
    ("NSE_EQ|INE002A01018", "RELIANCE", "Reliance Industries", "NSE_EQ", "EQ", "INE002A01018", "1470"),
    ("NSE_EQ|INE040A01034", "HDFCBANK", "HDFC Bank", "NSE_EQ", "EQ", "INE040A01034", "1650"),
    ("NSE_EQ|INE467B01029", "TCS", "Tata Consultancy Services", "NSE_EQ", "EQ", "INE467B01029", "3050"),
    ("NSE_EQ|INE009A01021", "INFY", "Infosys", "NSE_EQ", "EQ", "INE009A01021", "1480"),
    ("NSE_EQ|INE090A01021", "ICICIBANK", "ICICI Bank", "NSE_EQ", "EQ", "INE090A01021", "1370"),
    ("NSE_EQ|INE062A01020", "SBIN", "State Bank of India", "NSE_EQ", "EQ", "INE062A01020", "870"),
    ("NSE_EQ|INE154A01025", "ITC", "ITC", "NSE_EQ", "EQ", "INE154A01025", "410"),
    ("NSE_EQ|INE018A01030", "LT", "Larsen & Toubro", "NSE_EQ", "EQ", "INE018A01030", "3650"),
    ("NSE_EQ|INE397D01024", "BHARTIARTL", "Bharti Airtel", "NSE_EQ", "EQ", "INE397D01024", "1950"),
    ("NSE_EQ|INE030A01027", "HINDUNILVR", "Hindustan Unilever", "NSE_EQ", "EQ", "INE030A01027", "2450"),
    ("NSE_EQ|INE238A01034", "AXISBANK", "Axis Bank", "NSE_EQ", "EQ", "INE238A01034", "1150"),
    ("BSE_EQ|INE002A01018", "RELIANCE", "Reliance Industries", "BSE_EQ", "A", "INE002A01018", "1470"),
    ("NSE_INDEX|Nifty 50", "NIFTY", "Nifty 50", "NSE_INDEX", "INDEX", None, "25500"),
    ("NSE_INDEX|Nifty Bank", "BANKNIFTY", "Nifty Bank", "NSE_INDEX", "INDEX", None, "57000"),
]

SEED_PRICES: dict[str, Decimal] = {row[0]: Decimal(row[6]) for row in SEED}


async def ensure_seed_instruments(sm: async_sessionmaker[AsyncSession]) -> int:
    """Insert the seed rows only if the instruments table is empty. Returns rows inserted."""
    async with sm() as session:
        count = await session.scalar(select(func.count()).select_from(Instrument))
        if count:
            return 0
        rows = [
            {
                "instrument_key": key,
                "trading_symbol": symbol,
                "name": name,
                "exchange": segment.split("_")[0],
                "segment": segment,
                "instrument_type": itype,
                "isin": isin,
            }
            for key, symbol, name, segment, itype, isin, _ in SEED
        ]
        await session.execute(insert(Instrument).values(rows).on_conflict_do_nothing())
        await session.commit()
        return len(rows)
