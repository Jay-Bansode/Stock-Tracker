"""Cron (free-hosting) mode: each call to /api/cron/poll does, in one short request, what the
always-on engine and notifier do continuously: fetch prices, evaluate alerts, send messages."""

import asyncio
import logging
import random
import time
import zlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import IST, Settings
from app.engine.index import AlertIndex
from app.engine.processor import AlertProcessor
from app.marketdata.base import Tick, to_price
from app.marketdata.market_calendar import MarketCalendar
from app.marketdata.seed import SEED_PRICES
from app.marketdata.upstox.rest import UpstoxAuthError, UpstoxRest
from app.notify import build_senders
from app.notify.base import Sender
from app.notify.worker import ChannelWorker
from app.runtime.store import PgStore
from app.services.alerts import send_system_once

log = logging.getLogger(__name__)

POLL_LOCK_ID = 727_002
STATUS_KEY = "poll"
DRAIN_RESERVE_SECONDS = 5  # a delivery batch can still be running when the budget is checked


class QuoteSource(Protocol):
    name: str

    async def fetch(self, keys: list[str]) -> list[Tick]: ...


class UpstoxQuoteSource:
    """Last price (+ previous close) from LTP v3, plus the previous and current 1-minute
    candles so a target touched between two polls is still noticed."""

    name = "upstox"

    def __init__(self, rest: UpstoxRest):
        self.rest = rest

    async def fetch(self, keys: list[str]) -> list[Tick]:
        quotes = await self.rest.ltp(keys)
        try:
            candles = await self.rest.ohlc_1m(keys)
        except UpstoxAuthError:
            raise
        except Exception as exc:
            log.warning("1-minute candles unavailable, using last price only: %s", exc)
            candles = {}
        now = datetime.now(UTC)
        ticks = []
        for key in keys:
            ltp, close = quotes.get(key, (None, None))
            candle_ltp, recent = candles.get(key, (None, []))
            price = ltp or candle_ltp
            if price is not None:
                ticks.append(Tick(key, price, close=close, ts=now, candles=tuple(recent)))
        return ticks


class SimulatedQuoteSource:
    """Random walk from the last stored price (or the seed price), for trying cron mode
    without an Upstox account."""

    name = "simulated"

    def __init__(self, store: PgStore, random_walk: bool = True, volatility_pct: float = 0.05):
        self.store = store
        self.random_walk = random_walk
        self.volatility = volatility_pct / 100

    async def fetch(self, keys: list[str]) -> list[Tick]:
        known = await self.store.get_prices(keys)
        ticks = []
        for key in keys:
            if key in known:
                price = Decimal(str(known[key]["p"]))
                close = known[key]["c"]
            else:
                price = SEED_PRICES.get(key) or Decimal(100 + zlib.crc32(key.encode()) % 2900)
                close = price
            if self.random_walk:
                price = price * (1 + Decimal(str(random.gauss(0, self.volatility))))
            ticks.append(Tick(key, max(to_price(price), Decimal("0.05")),
                              close=to_price(close) if close else None))
        return ticks


class PollRuntime:
    """Per-process objects reused across cron calls (HTTP clients, holiday cache)."""

    def __init__(self, settings: Settings, sm: async_sessionmaker[AsyncSession],
                 source: QuoteSource | None = None, senders: dict[str, Sender] | None = None,
                 calendar: MarketCalendar | None = None):
        self.settings = settings
        self.sm = sm
        self.store = PgStore(sm)
        rest = None
        if settings.market_data_provider == "upstox":
            rest = UpstoxRest(settings.upstox_analytics_token, settings.upstox_api_base)
        self.source = source or (
            UpstoxQuoteSource(rest) if rest else SimulatedQuoteSource(
                self.store, settings.simulated_random_walk, settings.simulated_volatility_pct)
        )
        self.calendar = calendar or (
            MarketCalendar(settings, rest) if rest
            else MarketCalendar(settings.model_copy(update={"enforce_market_hours": False}))
        )
        self.senders = build_senders(settings) if senders is None else senders

    async def _evaluate(self, ticks: list[Tick], now: datetime | None) -> tuple[int, int]:
        index = AlertIndex()
        await index.reload(self.sm)
        processor = AlertProcessor(self.sm, index, self.settings.enabled_channels)
        events = 0
        for tick in ticks:
            events += len(await processor.process(tick, now))
        return events, index.alert_count

    async def process_ticks(self, ticks: list[Tick], now: datetime | None = None) -> dict:
        """Store + evaluate specific ticks and deliver the results (dev-tick injection)."""
        start = time.monotonic()
        await self.store.publish_ticks(ticks)
        events, _ = await self._evaluate(ticks, now)
        sent = await self.drain_outbox(start + self.settings.poll_budget_seconds)
        return {"events": events, "sent": sent}

    async def drain_outbox(self, deadline: float) -> int:
        """Deliver queued notifications until done or out of time; the rest go next minute."""
        stop_at = deadline - DRAIN_RESERVE_SECONDS

        async def drain(sender: Sender) -> int:
            worker = ChannelWorker(self.sm, sender, self.settings.notify_max_attempts)
            handled = 0
            try:
                await worker.recover_stale()
                while time.monotonic() < stop_at:
                    n = await worker.process_batch(limit=5)
                    if not n:
                        break
                    handled += n
            except Exception:
                log.exception("%s delivery failed", sender.channel)
            return handled

        return sum(await asyncio.gather(*(drain(s) for s in self.senders.values())))

    async def run_cycle(self, now: datetime | None = None) -> dict:
        started = time.monotonic()
        deadline = started + self.settings.poll_budget_seconds
        at = now or datetime.now(UTC)
        summary: dict = {
            "at": at.isoformat(), "provider": self.source.name, "ok": True, "error": None,
            "market_open": False, "polled": 0, "rules": 0, "events": 0, "sent": 0,
        }
        # Transaction-scoped lock: overlapping calls skip instead of double-processing, and the
        # lock can never leak because it ends with the transaction.
        async with self.sm() as lock, lock.begin():
            got = await lock.scalar(text("SELECT pg_try_advisory_xact_lock(:id)"),
                                    {"id": POLL_LOCK_ID})
            if not got:
                return {"skipped": "busy"}
            try:
                summary["market_open"] = await self.calendar.is_open(at)
                if summary["market_open"]:
                    index = AlertIndex()
                    await index.reload(self.sm)
                    keys = sorted(index.subscription_keys(self.settings.max_subscriptions))
                    ticks = await self.source.fetch(keys) if keys else []
                    await self.store.publish_ticks(ticks)
                    summary["polled"] = len(ticks)
                    summary["events"], summary["rules"] = await self._evaluate(ticks, now)
            except UpstoxAuthError as exc:
                summary.update(ok=False, error=f"Upstox rejected the token: {exc}"[:300])
                await send_system_once(
                    self.sm, "upstox_auth",
                    "Upstox rejected the market data token, so alerts are NOT being checked. "
                    "Generate a new Analytics Token and update UPSTOX_ANALYTICS_TOKEN.",
                    self.settings.enabled_channels, timedelta(hours=6),
                )
            except Exception as exc:
                log.exception("poll cycle failed")
                summary.update(ok=False, error=repr(exc)[:300])

            summary["sent"] = await self.drain_outbox(deadline)
            await self._token_expiry_reminder(at)
            summary["duration_ms"] = int((time.monotonic() - started) * 1000)
            await self.store.write_state(STATUS_KEY, summary)
        return summary

    async def _token_expiry_reminder(self, now: datetime) -> None:
        expires = self.settings.upstox_token_expires_on
        if self.settings.market_data_provider != "upstox" or not expires:
            return
        days_left = (expires - now.astimezone(IST).date()).days
        if days_left <= 7:
            await send_system_once(
                self.sm, "token_expiry",
                f"Upstox Analytics Token expires on {expires:%d %b %Y} ({max(days_left, 0)} "
                "day(s) left). Generate a new one and update UPSTOX_ANALYTICS_TOKEN.",
                self.settings.enabled_channels, timedelta(hours=24),
            )


_runtime: PollRuntime | None = None


def get_runtime(settings: Settings, sm: async_sessionmaker[AsyncSession]) -> PollRuntime:
    global _runtime
    if _runtime is None or _runtime.settings is not settings or _runtime.sm is not sm:
        _runtime = PollRuntime(settings, sm)
    return _runtime
