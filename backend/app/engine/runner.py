import asyncio
import json
import logging
import time
from datetime import UTC, datetime, timedelta

import asyncpg
from redis.asyncio import Redis

from app.config import IST, Settings, get_settings
from app.db.session import CHANNEL_ALERTS_CHANGED, get_sessionmaker
from app.engine.index import AlertIndex
from app.engine.processor import AlertProcessor
from app.logging_setup import setup_logging
from app.marketdata.base import MarketDataProvider, Tick
from app.marketdata.cache import ENGINE_STATUS_KEY, publish_ticks
from app.marketdata.instruments_sync import refresh_instruments
from app.marketdata.market_calendar import MarketCalendar
from app.marketdata.simulated import SimulatedProvider
from app.marketdata.upstox.feed import UpstoxProvider
from app.marketdata.upstox.rest import UpstoxRest
from app.services.alerts import enqueue_system_message

log = logging.getLogger("app.engine")

LEADER_LOCK_ID = 727_001
RELOAD_SAFETY_SECONDS = 60
STATUS_SECONDS = 5
FEED_DOWN_ALERT = timedelta(minutes=5)
INSTRUMENT_SYNC_AT = (7, 0)  # IST


class SystemNotifier:
    def __init__(self, engine: "Engine"):
        self._engine = engine
        self._last: dict[str, datetime] = {}

    async def send(self, reason: str, text: str, every: timedelta = timedelta(hours=6)) -> None:
        now = datetime.now(UTC)
        last = self._last.get(reason)
        if last and now - last < every:
            return
        self._last[reason] = now
        log.warning("system notice [%s]: %s", reason, text)
        try:
            await enqueue_system_message(self._engine.sm, f"⚠️ Tracker: {text}",
                                         self._engine.settings.enabled_channels)
        except Exception:
            log.exception("could not queue system message")


class Engine:
    def __init__(self, settings: Settings, redis: Redis):
        self.settings = settings
        self.sm = get_sessionmaker()
        self.redis = redis
        self.index = AlertIndex()
        self.processor = AlertProcessor(self.sm, self.index, settings.enabled_channels)
        self.system = SystemNotifier(self)
        self.reload_event = asyncio.Event()
        self.last_tick_at: float | None = None
        self.rest: UpstoxRest | None = None
        self.calendar: MarketCalendar
        self.provider: MarketDataProvider = self._build_provider()
        self._subscribed: set[str] = set()

    def _build_provider(self) -> MarketDataProvider:
        s = self.settings
        if s.market_data_provider == "upstox":
            self.rest = UpstoxRest(s.upstox_analytics_token, s.upstox_api_base)
            self.calendar = MarketCalendar(s, self.rest)
            return UpstoxProvider(
                self.rest,
                should_connect=self.calendar.is_open,
                on_auth_error=self._on_auth_error,
            )
        self.calendar = MarketCalendar(s.model_copy(update={"enforce_market_hours": False}))
        return SimulatedProvider(
            self.redis,
            random_walk=s.simulated_random_walk,
            tick_seconds=s.simulated_tick_seconds,
            volatility_pct=s.simulated_volatility_pct,
        )

    async def _on_auth_error(self, detail: str) -> None:
        await self.system.send(
            "upstox_auth",
            "Upstox rejected the market data token, so alerts are NOT being monitored. "
            f"Generate a new Analytics Token and update UPSTOX_ANALYTICS_TOKEN. ({detail[:200]})",
        )

    async def on_ticks(self, ticks: list[Tick]) -> None:
        self.last_tick_at = time.time()
        try:
            await publish_ticks(self.redis, ticks)
        except Exception as exc:
            log.warning("price cache update failed: %s", exc)
        for tick in ticks:
            await self.processor.process(tick)

    # --- background loops -------------------------------------------------------------------

    async def reload_loop(self) -> None:
        while True:
            try:
                await self.index.reload(self.sm)
                keys = self.index.subscription_keys(self.settings.max_subscriptions)
                if len(self.index.watch_keys) > len(keys):
                    log.warning("subscription cap %d reached; %d instruments not streamed",
                                self.settings.max_subscriptions,
                                len(self.index.watch_keys) - len(keys))
                new_keys = keys - self._subscribed
                self._subscribed = keys
                await self.provider.set_subscriptions(keys)
                if new_keys:
                    await self._prime_prices(sorted(new_keys))
            except Exception:
                log.exception("alert index reload failed")
            self.reload_event.clear()
            try:
                await asyncio.wait_for(self.reload_event.wait(), RELOAD_SAFETY_SECONDS)
            except TimeoutError:
                pass

    async def _prime_prices(self, keys: list[str]) -> None:
        """Fill the dashboard price cache via REST (e.g. stock added after market close).
        Not evaluated against alerts: only live-feed ticks trigger."""
        if self.rest is None:
            return
        try:
            quotes = await self.rest.ltp(keys)
            ticks = [Tick(k, ltp, close=close) for k, (ltp, close) in quotes.items()]
            if ticks:
                await publish_ticks(self.redis, ticks)
        except Exception as exc:
            log.warning("could not prime prices via REST: %s", exc)

    async def status_loop(self) -> None:
        while True:
            status = {
                "provider": self.provider.name,
                "connected": int(self.provider.connected),
                "market_status": json.dumps(self.provider.market_status),
                "market_window_open": int(await self.calendar.is_open()),
                "subscriptions": len(self._subscribed),
                "active_rules": self.index.alert_count,
                "last_tick_at": self.last_tick_at or 0,
                "heartbeat": time.time(),
                "channels": ",".join(self.settings.enabled_channels),
            }
            try:
                await self.redis.hset(ENGINE_STATUS_KEY, mapping=status)
                await self.redis.expire(ENGINE_STATUS_KEY, STATUS_SECONDS * 6)
            except Exception as exc:
                log.warning("status write failed: %s", exc)
            await asyncio.sleep(STATUS_SECONDS)

    async def health_loop(self) -> None:
        down_since: datetime | None = None
        notified_down = False
        while True:
            now = datetime.now(UTC)
            if self.provider.name == "upstox" and self.provider.keys and await self.calendar.is_open():
                if self.provider.connected:
                    if notified_down:
                        await self.system.send("feed_up", "Upstox live feed is back online.",
                                               every=timedelta(0))
                    down_since, notified_down = None, False
                else:
                    down_since = down_since or now
                    if not notified_down and now - down_since >= FEED_DOWN_ALERT:
                        notified_down = True
                        await self.system.send(
                            "feed_down",
                            "Upstox live feed has been disconnected for over 5 minutes during "
                            "market hours. Alerts are paused until it reconnects.",
                            every=timedelta(0),
                        )
            else:
                down_since, notified_down = None, False

            expires = self.settings.upstox_token_expires_on
            if self.provider.name == "upstox" and expires:
                days_left = (expires - now.astimezone(IST).date()).days
                if days_left <= 7:
                    await self.system.send(
                        "token_expiry",
                        f"Upstox Analytics Token expires on {expires:%d %b %Y} "
                        f"({max(days_left, 0)} day(s) left). Generate a new one in the Upstox "
                        "developer portal and update UPSTOX_ANALYTICS_TOKEN.",
                        every=timedelta(hours=24),
                    )
            await asyncio.sleep(30)

    async def instruments_loop(self) -> None:
        await self._sync_instruments()
        while True:
            now = datetime.now(IST)
            nxt = now.replace(hour=INSTRUMENT_SYNC_AT[0], minute=INSTRUMENT_SYNC_AT[1],
                              second=0, microsecond=0)
            if nxt <= now:
                nxt += timedelta(days=1)
            await asyncio.sleep((nxt - now).total_seconds())
            await self._sync_instruments()

    async def _sync_instruments(self) -> None:
        result = await refresh_instruments(
            self.sm, self.settings, download=self.settings.instruments_sync_on_start
        )
        log.info("instrument master: %s", result)


async def _acquire_leadership(dsn: str) -> asyncpg.Connection:
    """Only one engine may hold the feed. Standby instances wait here until the leader dies."""
    while True:
        conn = await asyncpg.connect(dsn)
        if await conn.fetchval("SELECT pg_try_advisory_lock($1)", LEADER_LOCK_ID):
            return conn
        await conn.close()
        log.info("another engine holds the leader lock; standing by")
        await asyncio.sleep(15)


async def _watch_connection(conn: asyncpg.Connection) -> None:
    while True:
        await asyncio.sleep(30)
        await conn.fetchval("SELECT 1")  # raises if the lock connection died -> process exits


async def main() -> None:
    setup_logging()
    settings = get_settings()
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    conn = await _acquire_leadership(settings.asyncpg_dsn)
    log.info("engine is leader; provider=%s channels=%s", settings.market_data_provider,
             settings.enabled_channels or "none (events recorded, nothing sent)")

    engine = Engine(settings, redis)
    await conn.add_listener(CHANNEL_ALERTS_CHANGED, lambda *_: engine.reload_event.set())
    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(engine.instruments_loop())
            tg.create_task(engine.reload_loop())
            tg.create_task(engine.provider.run(engine.on_ticks))
            tg.create_task(engine.status_loop())
            tg.create_task(engine.health_loop())
            tg.create_task(_watch_connection(conn))
    finally:
        await conn.close()
        await redis.aclose()
