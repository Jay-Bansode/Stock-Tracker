from datetime import UTC, datetime
from decimal import Decimal as D

import httpx
import pytest
import respx

from app.marketdata.upstox.rest import UpstoxAuthError, UpstoxRest

BASE = "https://api.upstox.com"
TS = 1793251920000  # candle start, epoch ms


@respx.mock
async def test_ohlc_1m_parses_prev_and_live_candles():
    route = respx.get(f"{BASE}/v3/market-quote/ohlc").mock(return_value=httpx.Response(200, json={
        "status": "success",
        "data": {
            "NSE_EQ:RELIANCE": {
                "last_price": 1495.2,
                "instrument_token": "NSE_EQ|INE002A01018",
                "prev_ohlc": {"open": 1490, "high": 1501.5, "low": 1489, "close": 1494, "volume": 10, "ts": TS},
                "live_ohlc": {"open": 1494, "high": 1496, "low": 1493.1, "close": 1495.2, "volume": 4, "ts": TS + 60000},
            },
            "NSE_EQ:NOCANDLE": {"last_price": 100, "instrument_token": "NSE_EQ|X", "prev_ohlc": None, "live_ohlc": None},
        },
    }))
    out = await UpstoxRest("tok", BASE).ohlc_1m(["NSE_EQ|INE002A01018", "NSE_EQ|X"])
    assert route.calls.last.request.url.params["interval"] == "I1"
    ltp, candles = out["NSE_EQ|INE002A01018"]
    assert ltp == D("1495.20")
    assert [(c.start, c.high, c.low) for c in candles] == [
        (datetime.fromtimestamp(TS / 1000, UTC), D("1501.50"), D("1489.00")),
        (datetime.fromtimestamp((TS + 60000) / 1000, UTC), D("1496.00"), D("1493.10")),
    ]
    assert out["NSE_EQ|X"] == (D("100.00"), [])


@respx.mock
async def test_rejected_token_raises_auth_error():
    respx.get(f"{BASE}/v3/market-quote/ohlc").mock(return_value=httpx.Response(401, json={}))
    with pytest.raises(UpstoxAuthError):
        await UpstoxRest("bad", BASE).ohlc_1m(["NSE_EQ|X"])
