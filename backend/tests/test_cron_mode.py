"""Cron (free-hosting) mode: the once-a-minute poll cycle and its endpoints."""

import gzip
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import httpx
import pytest
import respx
from sqlalchemy import select, text, update

from app.api.deps import get_sm
from app.config import Settings, get_settings
from app.db.models import Alert, AlertEvent
from app.db.session import get_session
from app.engine.poll import POLL_LOCK_ID, PollRuntime
from app.main import create_app
from app.marketdata.base import Candle, Tick
from app.marketdata.instruments_sync import refresh_instruments, sync_instruments
from app.marketdata.upstox.rest import UpstoxAuthError
from app.runtime.store import PgStore
from app.services.alerts import send_system_once, trigger_alert
from tests.conftest import HDFCBANK, RELIANCE
from tests.test_worker import FakeSender


class FakeSource:
    name = "fake"

    def __init__(self):
        self.ticks: dict[str, Tick] = {}
        self.calls = 0
        self.error: Exception | None = None

    def set(self, key, price, candles=()):
        self.ticks[key] = Tick(key, D(price), candles=tuple(candles))

    async def fetch(self, keys):
        self.calls += 1
        if self.error:
            raise self.error
        return [t for k, t in self.ticks.items() if k in keys]


class FakeCalendar:
    def __init__(self, open_=True):
        self.open = open_

    async def is_open(self, now=None):
        return self.open


def cron_settings(**kw):
    return Settings(
        _env_file=None, run_mode="cron", telegram_bot_token="t", telegram_chat_id="1",
        whatsapp_token="w", whatsapp_phone_number_id="p", whatsapp_to="9", **kw,
    )


def make_runtime(sm, open_=True):
    src = FakeSource()
    tg, wa = FakeSender("TELEGRAM"), FakeSender("WHATSAPP")
    rt = PollRuntime(cron_settings(), sm, source=src, senders={"TELEGRAM": tg, "WHATSAPP": wa},
                     calendar=FakeCalendar(open_))
    return rt, src, tg, wa


async def _events(sm):
    async with sm() as s:
        return (await s.scalars(select(AlertEvent).order_by(AlertEvent.id))).all()


async def _armed_at(sm, alert_id):
    async with sm() as s:
        return await s.scalar(select(Alert.updated_at).where(Alert.id == alert_id))


async def test_cycle_runs_example_scenario_exactly_once(sm, example):
    rt, src, tg, wa = make_runtime(sm)
    src.set(RELIANCE, "1502")
    src.set(HDFCBANK, "1650")

    first = await rt.run_cycle()
    assert (first["events"], first["sent"], first["polled"], first["ok"]) == (2, 4, 2, True)
    assert sorted(m.watchlist for m in tg.sent) == ["Intraday Stocks", "Long-Term Stocks"]
    assert sorted(m.watchlist for m in wa.sent) == ["Intraday Stocks", "Long-Term Stocks"]

    again = await rt.run_cycle()  # next minute, price still above both targets
    assert (again["events"], again["sent"]) == (0, 0)
    assert len(tg.sent) == 2 and len(wa.sent) == 2

    status = await PgStore(sm).read_state("poll")
    assert status["ok"] and status["market_open"] and status["polled"] == 2
    prices = await PgStore(sm).get_prices([RELIANCE])
    assert prices[RELIANCE]["p"] == 1502.0


async def test_touch_between_polls_and_rearm_ignores_old_spike(sm, example):
    rt, src, tg, _ = make_runtime(sm)
    armed = await _armed_at(sm, example["Long-Term Stocks"])
    spike = Candle(armed + timedelta(seconds=1), high=D("1501"), low=D("1470"))
    src.set(RELIANCE, "1475", candles=[spike])  # back down by the time we poll

    await rt.run_cycle()
    assert {(e.watchlist_name, e.trigger_price) for e in await _events(sm)} == {
        ("Long-Term Stocks", D("1501.00")), ("Intraday Stocks", D("1501.00"))}

    async with sm() as s:  # user re-arms Long-Term
        await s.execute(update(Alert).where(Alert.id == example["Long-Term Stocks"])
                        .values(status="ACTIVE", updated_at=datetime.now(UTC)))
        await s.commit()
    rearmed = await _armed_at(sm, example["Long-Term Stocks"])

    src.set(RELIANCE, "1490", candles=[spike])  # same old candle still in the window
    assert (await rt.run_cycle())["events"] == 0

    src.set(RELIANCE, "1490", candles=[Candle(rearmed + timedelta(seconds=1), D("1500.5"), D("1489"))])
    assert (await rt.run_cycle())["events"] == 1
    assert (await _events(sm))[-1].trigger_price == D("1500.50")


async def test_overlapping_cycles_skip_instead_of_double_processing(sm, example):
    rt, src, _, _ = make_runtime(sm)
    src.set(RELIANCE, "1502")
    async with sm() as other, other.begin():
        await other.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": POLL_LOCK_ID})
        assert await rt.run_cycle() == {"skipped": "busy"}
    assert src.calls == 0
    assert (await rt.run_cycle())["events"] == 2


async def test_market_closed_skips_prices_but_still_delivers_queue(sm, example):
    rt, src, tg, wa = make_runtime(sm, open_=False)
    await trigger_alert(sm, example["Banking Stocks"], D("1701"), None, ["TELEGRAM", "WHATSAPP"])
    summary = await rt.run_cycle()
    assert src.calls == 0 and summary["market_open"] is False and summary["sent"] == 2
    assert tg.sent[0].watchlist == "Banking Stocks"


async def test_rejected_token_sends_one_system_notice(sm, example):
    rt, src, tg, wa = make_runtime(sm)
    src.error = UpstoxAuthError("401")
    first = await rt.run_cycle()
    second = await rt.run_cycle()
    assert not first["ok"] and "rejected" in first["error"]
    assert not second["ok"]
    notices = [m for m in tg.sent if isinstance(m, str)]
    assert len(notices) == 1 and "Upstox rejected" in notices[0]
    assert wa.sent == []  # system messages are Telegram-only


async def test_pg_store_keeps_previous_close(sm):
    store = PgStore(sm)
    await store.publish_ticks([Tick("K", D("10.50"), close=D("10"))])
    await store.publish_ticks([Tick("K", D("11"))])
    prices = await store.get_prices(["K", "MISSING"])
    assert list(prices) == ["K"]
    assert (prices["K"]["p"], prices["K"]["c"]) == (11.0, 10.0)
    assert await store.get_ltp("K") == D("11.00")


async def test_send_system_once_dedupes_across_calls(sm):
    hour = timedelta(hours=1)
    assert await send_system_once(sm, "x", "hello", ["TELEGRAM"], hour)
    assert not await send_system_once(sm, "x", "hello", ["TELEGRAM"], hour)
    assert await send_system_once(sm, "other", "hi", ["TELEGRAM"], hour)


@respx.mock
async def test_streaming_instrument_sync_keeps_equities_and_indices(sm):
    rows = [
        {"segment": "NSE_EQ", "instrument_key": "NSE_EQ|INE002A01018", "trading_symbol": "RELIANCE",
         "name": "RELIANCE INDUSTRIES LTD", "short_name": "Reliance Industries", "exchange": "NSE",
         "instrument_type": "EQ", "isin": "INE002A01018", "lot_size": 1, "tick_size": 10.0},
        {"segment": "NSE_FO", "instrument_key": "NSE_FO|1", "trading_symbol": "RELIANCE FUT"},
        {"segment": "NSE_INDEX", "instrument_key": "NSE_INDEX|Nifty 50", "trading_symbol": "NIFTY",
         "name": "Nifty 50", "exchange": "NSE", "instrument_type": "INDEX"},
    ]
    settings = Settings(_env_file=None, instrument_exchanges=["NSE"])
    respx.get(settings.upstox_instruments_url.format(exchange="NSE")).mock(
        return_value=httpx.Response(200, content=gzip.compress(json.dumps(rows).encode())))
    assert await sync_instruments(sm, settings) == 2
    assert await refresh_instruments(sm, settings) == "fresh"  # synced < 20 h ago: no download


# --- endpoints ------------------------------------------------------------------------------

def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.fixture
def cron_app(sm, monkeypatch):
    settings = Settings(_env_file=None, run_mode="cron", cron_secret="s3cret", admin_password="pw",
                        secret_key="test-secret-key-that-is-long-enough-for-hs256",
                        market_data_provider="simulated", simulated_random_walk=False)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    app = create_app()
    app.state.redis = None  # lifespan doesn't run under ASGITransport
    app.state.store = PgStore(sm)

    async def session_override():
        async with sm() as s:
            yield s

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_sm] = lambda: sm
    return app, settings


async def test_cron_endpoint_requires_the_secret(cron_app, example):
    app, settings = cron_app
    async with _client(app) as c:
        assert (await c.post("/api/cron/poll")).status_code == 401
        assert (await c.post("/api/cron/poll", headers={"X-Cron-Secret": "nope"})).status_code == 401
        ok = await c.post("/api/cron/poll", headers={"X-Cron-Secret": "s3cret"})
        assert ok.status_code == 200
        body = ok.json()
        assert body["ok"] and body["provider"] == "simulated" and body["polled"] == 2
        assert body["events"] == 0  # seeded prices are below the targets

    app.dependency_overrides[get_settings] = lambda: settings.model_copy(update={"cron_secret": ""})
    async with _client(app) as c:
        assert (await c.post("/api/cron/poll", headers={"X-Cron-Secret": ""})).status_code == 404


async def test_cron_mode_dashboard_endpoints(cron_app, example):
    app, _ = cron_app
    async with _client(app) as c:
        assert (await c.post("/api/auth/login", json={"username": "admin", "password": "pw"})).status_code == 200
        await c.post("/api/cron/poll", headers={"X-Cron-Secret": "s3cret"})

        injected = (await c.post("/api/dev/ticks", json={"RELIANCE": 1502})).json()
        assert injected["events"] == 2  # evaluated immediately, no engine process needed

        status = (await c.get("/api/system/status")).json()
        assert status["mode"] == "cron" and status["engine"] is None
        assert status["poll"]["ok"] and status["poll"]["provider"] == "simulated"
        assert status["alerts"]["fired_today"] == 2

        quotes = (await c.get("/api/quotes", params={"keys": RELIANCE})).json()
        assert quotes[RELIANCE]["p"] == 1502.0


async def test_services_mode_has_no_cron_endpoint(monkeypatch):
    monkeypatch.setattr("app.main.get_settings", lambda: Settings(_env_file=None))
    async with _client(create_app()) as c:
        assert (await c.post("/api/cron/poll", headers={"X-Cron-Secret": "x"})).status_code == 404
