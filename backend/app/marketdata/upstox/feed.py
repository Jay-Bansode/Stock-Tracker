import asyncio
import json
import logging
import random
import uuid
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, datetime

import httpx
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import InvalidStatus, WebSocketException

from app.marketdata.base import MarketDataProvider, Tick, TickHandler, to_price
from app.marketdata.upstox.proto import feed_pb
from app.marketdata.upstox.rest import UpstoxApiError, UpstoxAuthError, UpstoxRest

log = logging.getLogger(__name__)

SUB_CHUNK = 100
WINDOW_CHECK_SECONDS = 30
AUTH_RETRY_SECONDS = 300


def decode_feed(raw: bytes) -> tuple[list[Tick], dict[str, str] | None]:
    """Decode one binary FeedResponse into ticks plus (for market_info frames) segment status."""
    pb = feed_pb()
    resp = pb.FeedResponse()
    resp.ParseFromString(raw)

    status = None
    if resp.HasField("marketInfo"):
        status = {
            seg: pb.MarketStatus.Name(value)
            for seg, value in resp.marketInfo.segmentStatus.items()
        }

    ticks = []
    for key, feed in resp.feeds.items():
        ltpc = _ltpc(feed)
        if ltpc is None or ltpc.ltp <= 0:
            continue
        ticks.append(
            Tick(
                instrument_key=key,
                ltp=to_price(ltpc.ltp),
                close=to_price(ltpc.cp) if ltpc.cp else None,
                ts=datetime.fromtimestamp(ltpc.ltt / 1000, tz=UTC) if ltpc.ltt else None,
            )
        )
    return ticks, status


def _ltpc(feed):
    kind = feed.WhichOneof("FeedUnion")
    if kind == "ltpc":
        return feed.ltpc
    if kind == "fullFeed":
        full = feed.fullFeed
        which = full.WhichOneof("FullFeedUnion")
        if which == "marketFF":
            return full.marketFF.ltpc
        if which == "indexFF":
            return full.indexFF.ltpc
    if kind == "firstLevelWithGreeks":
        return feed.firstLevelWithGreeks.ltpc
    return None


def sub_message(method: str, keys: Iterable[str], mode: str = "ltpc") -> bytes:
    data: dict = {"instrumentKeys": list(keys)}
    if method != "unsub":
        data["mode"] = mode
    return json.dumps({"guid": uuid.uuid4().hex, "method": method, "data": data}).encode()


class UpstoxProvider(MarketDataProvider):
    """Single connection to the Upstox V3 feed in ltpc mode.

    Each (re)connect re-authorizes (the wss URL is single-use), resubscribes everything, and the
    first frame after subscribing is a snapshot. The engine evaluates that snapshot like any
    other tick, so moves missed during a disconnect still fire.
    """

    name = "upstox"

    def __init__(
        self,
        rest: UpstoxRest,
        *,
        should_connect: Callable[[], Awaitable[bool]],
        on_auth_error: Callable[[str], Awaitable[None]],
        on_connection_change: Callable[[bool], Awaitable[None]] | None = None,
        connect_fn=connect,
    ):
        super().__init__()
        self._rest = rest
        self._should_connect = should_connect
        self._on_auth_error = on_auth_error
        self._on_connection_change = on_connection_change
        self._connect = connect_fn
        self._ws: ClientConnection | None = None
        self._subscribed: set[str] = set()
        self._wake = asyncio.Event()

    async def set_subscriptions(self, keys: set[str]) -> None:
        keys = set(keys)
        self.keys = keys
        ws = self._ws
        if ws is not None:
            add, remove = keys - self._subscribed, self._subscribed - keys
            try:
                await self._send(ws, "sub", add)
                await self._send(ws, "unsub", remove)
                self._subscribed = set(keys)
            except WebSocketException:
                log.warning("subscription update failed; will resubscribe on reconnect")
        self._wake.set()

    async def _send(self, ws: ClientConnection, method: str, keys: Iterable[str]) -> None:
        keys = sorted(keys)
        for i in range(0, len(keys), SUB_CHUNK):
            await ws.send(sub_message(method, keys[i : i + SUB_CHUNK]))  # bytes -> binary frame

    async def _set_connected(self, value: bool) -> None:
        if self.connected != value:
            self.connected = value
            if self._on_connection_change:
                await self._on_connection_change(value)

    async def _idle(self, seconds: float) -> None:
        self._wake.clear()
        try:
            await asyncio.wait_for(self._wake.wait(), timeout=seconds)
        except TimeoutError:
            pass

    async def run(self, on_ticks: TickHandler) -> None:
        backoff = 1.0
        while True:
            if not self.keys or not await self._should_connect():
                await self._set_connected(False)
                await self._idle(WINDOW_CHECK_SECONDS)
                continue
            try:
                uri = await self._rest.authorize_feed()
                async with self._connect(uri, max_size=None, open_timeout=20) as ws:
                    log.info("upstox feed connected, subscribing %d instruments", len(self.keys))
                    self._ws = ws
                    self._subscribed = set(self.keys)
                    await self._send(ws, "sub", self._subscribed)
                    await self._set_connected(True)
                    backoff = 1.0
                    watcher = asyncio.create_task(self._close_outside_window(ws))
                    try:
                        async for raw in ws:
                            if isinstance(raw, str):
                                continue
                            ticks, status = decode_feed(raw)
                            if status:
                                self.market_status = status
                            if ticks:
                                await on_ticks(ticks)
                    finally:
                        watcher.cancel()
                log.info("upstox feed closed")
            except UpstoxAuthError as exc:
                await self._drop()
                log.error("upstox auth failed: %s", exc)
                await self._on_auth_error(str(exc))
                await asyncio.sleep(AUTH_RETRY_SECONDS)
                continue
            except InvalidStatus as exc:
                code = exc.response.status_code
                await self._drop()
                if code in (401, 403):
                    await self._on_auth_error(f"feed handshake rejected ({code})")
                    await asyncio.sleep(AUTH_RETRY_SECONDS)
                    continue
                log.warning("upstox feed handshake failed: %s", exc)
            except (OSError, TimeoutError, WebSocketException, httpx.HTTPError, UpstoxApiError) as exc:
                log.warning("upstox feed error: %r", exc)
            await self._drop()
            delay = backoff + random.uniform(0, backoff / 2)
            backoff = min(backoff * 2, 60.0)
            await asyncio.sleep(delay)

    async def _drop(self) -> None:
        self._ws = None
        self._subscribed = set()
        await self._set_connected(False)

    async def _close_outside_window(self, ws: ClientConnection) -> None:
        while True:
            await asyncio.sleep(WINDOW_CHECK_SECONDS)
            if not await self._should_connect():
                log.info("market window closed; disconnecting feed")
                await ws.close()
                return
