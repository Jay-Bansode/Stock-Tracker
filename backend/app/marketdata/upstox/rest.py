import asyncio
import logging
import time
from collections import deque
from datetime import UTC, date, datetime
from decimal import Decimal

import httpx

from app.marketdata.base import Candle, to_price

log = logging.getLogger(__name__)

LTP_BATCH = 500  # API rejects more than 500 keys per quote call


def _candle(raw: dict | None) -> Candle | None:
    """Upstox OHLC object {open, high, low, close, volume, ts(ms, candle start)}."""
    if not raw or not raw.get("ts") or not raw.get("high") or not raw.get("low"):
        return None
    return Candle(
        start=datetime.fromtimestamp(int(raw["ts"]) / 1000, tz=UTC),
        high=to_price(raw["high"]),
        low=to_price(raw["low"]),
    )


class UpstoxAuthError(Exception):
    """Token missing, expired, revoked or lacking permission."""


class UpstoxApiError(Exception):
    pass


class RateLimiter:
    """Sliding-window limiter over several windows at once (e.g. per second / minute / 30 min)."""

    def __init__(self, windows: list[tuple[float, int]]):
        self._windows = windows
        self._calls: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                longest = max(w for w, _ in self._windows)
                while self._calls and now - self._calls[0] > longest:
                    self._calls.popleft()
                wait = 0.0
                for window, limit in self._windows:
                    in_window = [t for t in self._calls if now - t < window]
                    if len(in_window) >= limit:
                        wait = max(wait, window - (now - in_window[0]))
                if wait <= 0:
                    self._calls.append(now)
                    return
                await asyncio.sleep(wait)


# Published market-quote limits, kept slightly under.
QUOTE_LIMITS = [(1.0, 20), (60.0, 200), (1800.0, 900)]


class UpstoxRest:
    def __init__(self, token: str, base_url: str = "https://api.upstox.com",
                 client: httpx.AsyncClient | None = None):
        self._token = token
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=20)
        self._limiter = RateLimiter(QUOTE_LIMITS)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict | None = None) -> dict:
        if not self._token:
            raise UpstoxAuthError("UPSTOX_ANALYTICS_TOKEN is not set")
        await self._limiter.acquire()
        resp = await self._client.get(
            path,
            params=params,
            headers={"Authorization": f"Bearer {self._token}", "Accept": "application/json"},
        )
        if resp.status_code in (401, 403):
            raise UpstoxAuthError(f"Upstox rejected the token ({resp.status_code}): {resp.text[:300]}")
        if resp.status_code >= 400:
            raise UpstoxApiError(f"GET {path} -> {resp.status_code}: {resp.text[:300]}")
        body = resp.json()
        if body.get("status") != "success":
            raise UpstoxApiError(f"GET {path} returned {body}")
        return body

    async def authorize_feed(self) -> str:
        """Returns a single-use wss:// URL for the V3 market data feed."""
        body = await self._get("/v3/feed/market-data-feed/authorize")
        data = body.get("data") or {}
        uri = data.get("authorized_redirect_uri") or data.get("authorizedRedirectUri")
        if not uri:
            raise UpstoxApiError(f"authorize response missing redirect uri: {body}")
        return uri

    async def ltp(self, keys: list[str]) -> dict[str, tuple[Decimal, Decimal | None]]:
        """Last traded price (and previous close when present) keyed by instrument_key."""
        out: dict[str, tuple[Decimal, Decimal | None]] = {}
        for i in range(0, len(keys), LTP_BATCH):
            chunk = keys[i : i + LTP_BATCH]
            body = await self._get("/v3/market-quote/ltp", {"instrument_key": ",".join(chunk)})
            # Response is keyed by "NSE_EQ:RELIANCE"; instrument_token carries the instrument_key.
            for quote in (body.get("data") or {}).values():
                key = quote.get("instrument_token")
                price = quote.get("last_price")
                if key and price:
                    close = quote.get("cp")
                    out[key] = (to_price(price), to_price(close) if close else None)
        return out

    async def ohlc_1m(self, keys: list[str]) -> dict[str, tuple[Decimal | None, list[Candle]]]:
        """Last price plus the previous and current 1-minute candles, keyed by instrument_key.
        A once-a-minute poller uses the candles' high/low to catch touches between polls."""
        out: dict[str, tuple[Decimal | None, list[Candle]]] = {}
        for i in range(0, len(keys), LTP_BATCH):
            chunk = keys[i : i + LTP_BATCH]
            body = await self._get(
                "/v3/market-quote/ohlc", {"instrument_key": ",".join(chunk), "interval": "I1"}
            )
            for quote in (body.get("data") or {}).values():
                key = quote.get("instrument_token")
                if not key:
                    continue
                candles = [c for c in (_candle(quote.get("prev_ohlc")),
                                       _candle(quote.get("live_ohlc"))) if c]
                price = quote.get("last_price")
                out[key] = (to_price(price) if price else None, candles)
        return out

    async def trading_holidays(self, exchange: str = "NSE") -> set[date]:
        body = await self._get("/v2/market/holidays")
        days: set[date] = set()
        for h in body.get("data") or []:
            if h.get("holiday_type") == "TRADING_HOLIDAY" and exchange in (
                h.get("closed_exchanges") or []
            ):
                days.add(date.fromisoformat(h["date"][:10]))
        return days
