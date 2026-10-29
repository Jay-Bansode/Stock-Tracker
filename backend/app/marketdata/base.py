from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

PAISE = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class Candle:
    start: datetime
    high: Decimal
    low: Decimal


@dataclass(frozen=True, slots=True)
class Tick:
    instrument_key: str
    ltp: Decimal
    close: Decimal | None = None  # previous day's close, for day change %
    ts: datetime | None = None  # exchange last-trade time
    # Recent 1-minute candles (cron mode only): lets a once-a-minute poll still notice a
    # target that was touched between polls.
    candles: tuple[Candle, ...] = ()


TickHandler = Callable[[list[Tick]], Awaitable[None]]


def to_price(value: float | str | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(PAISE)


class MarketDataProvider(ABC):
    """A source of live ticks. `run` streams forever (reconnecting as needed) and hands each
    batch of ticks to the handler; subscriptions can change while it runs."""

    name: str

    def __init__(self) -> None:
        self.keys: set[str] = set()
        self.connected = False
        self.market_status: dict[str, str] = {}
        self._keys_changed = None  # created lazily inside the running loop

    @abstractmethod
    async def run(self, on_ticks: TickHandler) -> None: ...

    async def set_subscriptions(self, keys: set[str]) -> None:
        self.keys = set(keys)
