import asyncio
import json
import logging
import random
import zlib
from decimal import Decimal

from redis.asyncio import Redis

from app.marketdata.base import MarketDataProvider, Tick, TickHandler, to_price
from app.marketdata.cache import DEV_TICKS_CHANNEL
from app.marketdata.seed import SEED_PRICES

log = logging.getLogger(__name__)


class SimulatedProvider(MarketDataProvider):
    """Random-walk prices for development, plus exact prices injected through
    POST /api/dev/ticks (relayed over Redis) for deterministic testing."""

    name = "simulated"

    def __init__(self, redis: Redis, *, random_walk: bool = True, tick_seconds: float = 1.0,
                 volatility_pct: float = 0.05):
        super().__init__()
        self._redis = redis
        self._random_walk = random_walk
        self._tick_seconds = tick_seconds
        self._volatility = volatility_pct / 100
        self._prices: dict[str, Decimal] = {}
        self._closes: dict[str, Decimal] = {}
        self._on_ticks: TickHandler | None = None

    def _price(self, key: str) -> Decimal:
        if key not in self._prices:
            base = SEED_PRICES.get(key) or Decimal(100 + zlib.crc32(key.encode()) % 2900)
            self._prices[key] = base
            self._closes[key] = base
        return self._prices[key]

    def _tick(self, key: str, price: Decimal) -> Tick:
        self._prices[key] = price
        self._price(key)  # ensures a close exists
        return Tick(key, price, close=self._closes[key])

    async def set_subscriptions(self, keys: set[str]) -> None:
        new = set(keys) - self.keys
        self.keys = set(keys)
        if new and self._on_ticks:
            await self._on_ticks([self._tick(k, self._price(k)) for k in sorted(new)])

    async def run(self, on_ticks: TickHandler) -> None:
        self._on_ticks = on_ticks
        self.connected = True
        self.market_status = {"NSE_EQ": "NORMAL_OPEN", "BSE_EQ": "NORMAL_OPEN"}
        if self.keys:
            await on_ticks([self._tick(k, self._price(k)) for k in sorted(self.keys)])
        injector = asyncio.create_task(self._listen_injections(on_ticks))
        try:
            while True:
                await asyncio.sleep(self._tick_seconds)
                if self._random_walk and self.keys:
                    ticks = []
                    for key in sorted(self.keys):
                        p = self._price(key)
                        step = p * Decimal(str(random.gauss(0, self._volatility)))
                        ticks.append(self._tick(key, max(to_price(p + step), Decimal("0.05"))))
                    await on_ticks(ticks)
        finally:
            injector.cancel()

    async def _listen_injections(self, on_ticks: TickHandler) -> None:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(DEV_TICKS_CHANNEL)
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                try:
                    items = json.loads(message["data"])
                    ticks = [self._tick(i["k"], to_price(i["p"])) for i in items]
                except (ValueError, KeyError, TypeError):
                    log.warning("ignoring malformed dev tick: %r", message["data"])
                    continue
                log.info("injected ticks: %s", [(t.instrument_key, str(t.ltp)) for t in ticks])
                await on_ticks(ticks)
        finally:
            await pubsub.aclose()
