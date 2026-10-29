import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal as D

from websockets.asyncio.server import serve

from app.marketdata.upstox.feed import UpstoxProvider, decode_feed, sub_message
from app.marketdata.upstox.proto import feed_pb


def _ltpc_frame(prices: dict[str, float], kind="live_feed") -> bytes:
    pb = feed_pb()
    resp = pb.FeedResponse(type=getattr(pb, kind), currentTs=1)
    for key, price in prices.items():
        resp.feeds[key].ltpc.ltp = price
        resp.feeds[key].ltpc.cp = 1490.0
        resp.feeds[key].ltpc.ltt = 1793251935000
    return resp.SerializeToString()


def test_decode_ltpc_frame():
    ticks, status = decode_feed(_ltpc_frame({"NSE_EQ|INE002A01018": 1502.05}))
    assert status is None
    [t] = ticks
    assert t.instrument_key == "NSE_EQ|INE002A01018"
    assert t.ltp == D("1502.05")
    assert t.close == D("1490.00")
    assert t.ts == datetime.fromtimestamp(1793251935, tz=UTC)


def test_decode_full_feed_and_market_info():
    pb = feed_pb()
    resp = pb.FeedResponse(type=pb.live_feed)
    resp.feeds["NSE_EQ|A"].fullFeed.marketFF.ltpc.ltp = 101.1
    resp.feeds["NSE_INDEX|Nifty 50"].fullFeed.indexFF.ltpc.ltp = 25500.25
    resp.feeds["NSE_EQ|ZERO"].ltpc.ltp = 0  # no trade yet -> skipped
    ticks, _ = decode_feed(resp.SerializeToString())
    assert {t.instrument_key: t.ltp for t in ticks} == {
        "NSE_EQ|A": D("101.10"),
        "NSE_INDEX|Nifty 50": D("25500.25"),
    }

    info = pb.FeedResponse(type=pb.market_info)
    info.marketInfo.segmentStatus["NSE_EQ"] = pb.NORMAL_OPEN
    ticks, status = decode_feed(info.SerializeToString())
    assert ticks == [] and status == {"NSE_EQ": "NORMAL_OPEN"}


def test_sub_message_shape():
    msg = json.loads(sub_message("sub", ["B", "A"]))
    assert msg["method"] == "sub" and msg["data"] == {"instrumentKeys": ["B", "A"], "mode": "ltpc"}
    assert "mode" not in json.loads(sub_message("unsub", ["A"]))["data"]


async def test_provider_streams_reconnects_and_diffs_subscriptions():
    received: list[list[dict]] = []
    second_conn_msgs = asyncio.Queue()

    async def handler(ws):
        conn_no = len(received) + 1
        msgs: list[dict] = []
        received.append(msgs)
        first = await ws.recv()
        assert isinstance(first, bytes), "subscription requests must be binary frames"
        msgs.append(json.loads(first))
        info = feed_pb().FeedResponse(type=feed_pb().market_info)
        info.marketInfo.segmentStatus["NSE_EQ"] = feed_pb().NORMAL_OPEN
        await ws.send(info.SerializeToString())
        await ws.send(_ltpc_frame({"NSE_EQ|X": 100.0 + conn_no}, kind="initial_feed"))
        if conn_no == 1:
            await ws.close()  # simulate a drop; provider must re-authorize and resubscribe
            return
        async for raw in ws:
            await second_conn_msgs.put(json.loads(raw))

    class FakeRest:
        calls = 0

        async def authorize_feed(self):
            FakeRest.calls += 1
            return f"ws://127.0.0.1:{port}/feed"

    async def always_open():
        return True

    async def on_auth_error(detail):
        raise AssertionError(detail)

    ticks = []
    got_both = asyncio.Event()

    async def on_ticks(batch):
        ticks.extend(batch)
        if len(ticks) >= 2:
            got_both.set()

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        provider = UpstoxProvider(FakeRest(), should_connect=always_open,
                                  on_auth_error=on_auth_error)
        await provider.set_subscriptions({"NSE_EQ|X", "NSE_EQ|Y"})
        task = asyncio.create_task(provider.run(on_ticks))
        try:
            await asyncio.wait_for(got_both.wait(), 10)
            assert FakeRest.calls == 2
            assert [t.ltp for t in ticks] == [D("101.00"), D("102.00")]
            for conn in received:
                assert conn[0]["method"] == "sub"
                assert sorted(conn[0]["data"]["instrumentKeys"]) == ["NSE_EQ|X", "NSE_EQ|Y"]
            assert provider.connected
            assert provider.market_status == {"NSE_EQ": "NORMAL_OPEN"}

            await provider.set_subscriptions({"NSE_EQ|X", "NSE_EQ|Z"})
            sub = await asyncio.wait_for(second_conn_msgs.get(), 5)
            unsub = await asyncio.wait_for(second_conn_msgs.get(), 5)
            assert (sub["method"], sub["data"]["instrumentKeys"]) == ("sub", ["NSE_EQ|Z"])
            assert (unsub["method"], unsub["data"]["instrumentKeys"]) == ("unsub", ["NSE_EQ|Y"])
        finally:
            task.cancel()
