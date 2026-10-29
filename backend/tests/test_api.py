from decimal import Decimal as D

import httpx
import pytest

from app.api.deps import get_redis, get_sm, get_store
from app.config import Settings, get_settings
from app.db.session import get_session
from app.main import create_app
from app.marketdata.base import Tick
from app.marketdata.cache import publish_ticks
from app.marketdata.seed import ensure_seed_instruments
from app.runtime.store import RedisStore
from app.services.alerts import trigger_alert

RELIANCE = "NSE_EQ|INE002A01018"


@pytest.fixture
async def client(sm, redis):
    await ensure_seed_instruments(sm)
    app = create_app()
    settings = Settings(admin_username="admin", admin_password="pw", secret_key="test-secret-key-that-is-long-enough-for-hs256",
                        _env_file=None)

    async def session_override():
        async with sm() as s:
            yield s

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_redis] = lambda: redis
    app.dependency_overrides[get_store] = lambda: RedisStore(redis)
    app.dependency_overrides[get_sm] = lambda: sm
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as c:
        yield c


async def _login(client):
    r = await client.post("/api/auth/login", json={"username": "admin", "password": "pw"})
    assert r.status_code == 200


async def test_requires_login(client):
    assert (await client.get("/api/watchlists")).status_code == 401
    bad = await client.post("/api/auth/login", json={"username": "admin", "password": "nope"})
    assert bad.status_code == 401
    await _login(client)
    assert (await client.get("/api/auth/me")).json() == {"username": "admin"}


async def test_watchlist_alert_history_flow(client, sm, redis):
    await _login(client)
    wl_ids = {}
    for name in ("Long-Term Stocks", "Intraday Stocks"):
        r = await client.post("/api/watchlists", json={"name": name})
        assert r.status_code == 201
        wl_ids[name] = r.json()["id"]
    dup = await client.post("/api/watchlists", json={"name": "Long-Term Stocks"})
    assert dup.status_code == 409

    found = (await client.get("/api/instruments/search", params={"q": "relia"})).json()
    assert found[0]["instrument_key"] == RELIANCE  # NSE ranked before BSE

    await publish_ticks(redis, [Tick(RELIANCE, D("1470"), close=D("1460"))])
    alert_ids = {}
    for name, target in (("Long-Term Stocks", 1500), ("Intraday Stocks", 1480)):
        item = await client.post(f"/api/watchlists/{wl_ids[name]}/items",
                                 json={"instrument_key": RELIANCE})
        assert item.status_code == 201
        r = await client.post(f"/api/watchlist-items/{item.json()['id']}/alerts",
                              json={"condition": "ABOVE", "target_price": target})
        assert r.status_code == 201
        body = r.json()
        assert body["current_price"] == 1470.0 and body["already_met"] is False
        alert_ids[name] = body["id"]

    again = await client.post(f"/api/watchlists/{wl_ids['Intraday Stocks']}/items",
                              json={"instrument_key": RELIANCE})
    assert again.status_code == 409

    below = await client.patch(f"/api/alerts/{alert_ids['Intraday Stocks']}",
                               json={"condition": "BELOW", "target_price": 1475})
    assert below.json()["already_met"] is True  # 1470 <= 1475 -> UI warns it fires immediately

    lists = {w["name"]: w for w in (await client.get("/api/watchlists")).json()}
    assert lists["Long-Term Stocks"]["item_count"] == 1
    assert lists["Long-Term Stocks"]["active_alerts"] == 1

    await trigger_alert(sm, alert_ids["Long-Term Stocks"], D("1502"), None, ["TELEGRAM"])
    hist = (await client.get("/api/history")).json()
    assert hist["total"] == 1
    event = hist["items"][0]
    assert (event["watchlist_name"], event["target_price"], event["trigger_price"]) == (
        "Long-Term Stocks", 1500.0, 1502.0)
    assert event["notifications"][0]["status"] == "PENDING"

    csv = await client.get("/api/history/export.csv")
    assert "Long-Term Stocks" in csv.text and "RELIANCE" in csv.text

    triggered = (await client.get("/api/alerts", params={"status": "TRIGGERED"})).json()
    assert [a["watchlist_name"] for a in triggered] == ["Long-Term Stocks"]
    rearmed = await client.post(f"/api/alerts/{alert_ids['Long-Term Stocks']}/rearm")
    assert rearmed.json()["status"] == "ACTIVE"

    # deleting the watchlist keeps the history snapshot
    assert (await client.delete(f"/api/watchlists/{wl_ids['Long-Term Stocks']}")).status_code == 204
    hist = (await client.get("/api/history")).json()
    assert hist["items"][0]["watchlist_name"] == "Long-Term Stocks"
    assert hist["items"][0]["alert_id"] is None


async def test_dev_ticks_resolves_symbols(client, redis):
    await _login(client)
    pubsub = redis.pubsub()
    await pubsub.subscribe("tracker:dev_ticks")
    r = await client.post("/api/dev/ticks", json={"RELIANCE": 1502})
    assert r.json()["published"] == [{"k": RELIANCE, "p": "1502"}]
    assert (await client.post("/api/dev/ticks", json={"NOPE": 1})).status_code == 404
    await pubsub.aclose()
