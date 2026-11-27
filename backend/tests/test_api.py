from decimal import Decimal as D

import httpx
import pytest

from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from app.api.deps import (
    forgot_throttle,
    get_redis,
    get_sm,
    get_store,
    login_throttle,
    register_throttle,
)
from app.db.models import PasswordResetToken
from app.notify import email as email_mod
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
async def client(sm, redis, owner):
    await ensure_seed_instruments(sm)
    for throttle in (login_throttle, forgot_throttle, register_throttle):
        throttle.clear()
    email_mod.outbox.clear()
    app = create_app()
    settings = Settings(secret_key="test-secret-key-that-is-long-enough-for-hs256",
                        email_provider="console", _env_file=None)

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
    me = (await client.get("/api/auth/me")).json()
    assert (me["username"], me["is_admin"], me["telegram_linked"]) == ("admin", True, True)


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


def _new_client(client):
    """Same app, separate cookie jar: a second browser."""
    return httpx.AsyncClient(transport=client._transport, base_url="http://test")


async def _register(c, username, password="password1"):
    r = await c.post("/api/auth/register", json={
        "username": username, "email": f"{username}@example.com", "password": password})
    assert r.status_code == 201, r.text
    return r.json()


def _reset_tokens():
    return [next(w for w in m["text"].split() if "token=" in w).split("token=")[1]
            for m in email_mod.outbox]


async def test_register_and_login_by_email(client):
    async with _new_client(client) as c:
        me = await _register(c, "Bob")
        assert (me["username"], me["is_admin"], me["telegram_linked"]) == ("Bob", False, False)
        assert (await c.get("/api/auth/me")).json()["email"] == "bob@example.com"
    async with _new_client(client) as c:
        dup = await c.post("/api/auth/register", json={
            "username": "bob", "email": "other@example.com", "password": "password1"})
        assert dup.status_code == 409  # usernames are case-insensitive
        short = await c.post("/api/auth/register", json={
            "username": "carol", "email": "carol@example.com", "password": "short"})
        assert short.status_code == 422
        r = await c.post("/api/auth/login", json={"username": "BOB@example.com",
                                                  "password": "password1"})
        assert r.status_code == 200 and r.json()["username"] == "Bob"


async def test_users_only_see_their_own_data(client, sm):
    await _login(client)
    wl = (await client.post("/api/watchlists", json={"name": "Mine"})).json()
    item = (await client.post(f"/api/watchlists/{wl['id']}/items",
                              json={"instrument_key": RELIANCE})).json()
    alert = (await client.post(f"/api/watchlist-items/{item['id']}/alerts",
                               json={"condition": "ABOVE", "target_price": 1500})).json()
    await trigger_alert(sm, alert["id"], D("1502"), None, ["TELEGRAM"])
    note_id = (await client.get("/api/history")).json()["items"][0]["notifications"][0]["id"]

    async with _new_client(client) as bob:
        await _register(bob, "bob")
        assert (await bob.get("/api/watchlists")).json() == []
        assert (await bob.get("/api/alerts")).json() == []
        assert (await bob.get("/api/history")).json()["total"] == 0
        wl_url = f"/api/watchlists/{wl['id']}"
        assert (await bob.get(f"{wl_url}/items")).status_code == 404
        assert (await bob.patch(wl_url, json={"name": "x"})).status_code == 404
        assert (await bob.delete(wl_url)).status_code == 404
        assert (await bob.delete(f"{wl_url}/items/{item['id']}")).status_code == 404
        assert (await bob.post(f"/api/watchlist-items/{item['id']}/alerts",
                               json={"condition": "ABOVE", "target_price": 1})).status_code == 404
        assert (await bob.patch(f"/api/alerts/{alert['id']}", json={"note": "x"})).status_code == 404
        assert (await bob.delete(f"/api/alerts/{alert['id']}")).status_code == 404
        assert (await bob.post(f"/api/notifications/{note_id}/retry")).status_code == 404
        assert (await bob.post("/api/dev/ticks", json={"RELIANCE": 1})).status_code == 403
        assert (await bob.patch(f"{wl_url}/items/{item['id']}",
                                json={"bought_on": "2024-01-01"})).status_code == 404
        # the same watchlist name is fine for a different user
        assert (await bob.post("/api/watchlists", json={"name": "Mine"})).status_code == 201
        status = (await bob.get("/api/system/status")).json()
        assert status["alerts"] == {"active": 0, "triggered": 0, "fired_today": 0}
    assert len((await client.get("/api/watchlists")).json()) == 1


async def test_forgot_and_reset_password(client):
    async with _new_client(client) as bob:
        await _register(bob, "bob", "password1")
        unknown = await bob.post("/api/auth/forgot-password", json={"email": "nobody@example.com"})
        known = await bob.post("/api/auth/forgot-password", json={"email": "BOB@example.com"})
        assert unknown.status_code == known.status_code == 202
        assert unknown.json() == known.json()  # no hint whether the account exists
        assert [m["to"] for m in email_mod.outbox] == ["bob@example.com"]
        assert "http://test/reset-password?token=" in email_mod.outbox[0]["text"]
        [token] = _reset_tokens()

        r = await bob.post("/api/auth/reset-password", json={"token": token, "password": "newpass99"})
        assert r.status_code == 200
        again = await bob.post("/api/auth/reset-password",
                               json={"token": token, "password": "another99"})
        assert again.status_code == 400  # single use
        assert (await bob.get("/api/auth/me")).status_code == 200  # signed in by the reset

    async with _new_client(client) as c:
        old = await c.post("/api/auth/login", json={"username": "bob", "password": "password1"})
        assert old.status_code == 401
        new = await c.post("/api/auth/login", json={"username": "bob", "password": "newpass99"})
        assert new.status_code == 200


async def test_reset_signs_out_other_sessions_and_links_expire(client, sm):
    await _login(client)
    assert (await client.get("/api/auth/me")).status_code == 200
    async with _new_client(client) as c:
        for _ in range(2):
            await c.post("/api/auth/forgot-password", json={"email": "admin@example.com"})
        first, second = _reset_tokens()
        async with sm() as s:
            await s.execute(update(PasswordResetToken).where(PasswordResetToken.id == 1)
                            .values(expires_at=datetime.now(UTC) - timedelta(minutes=1)))
            await s.commit()
        expired = await c.post("/api/auth/reset-password",
                               json={"token": first, "password": "newpass99"})
        assert expired.status_code == 400
        ok = await c.post("/api/auth/reset-password", json={"token": second, "password": "newpass99"})
        assert ok.status_code == 200
    assert (await client.get("/api/auth/me")).status_code == 401  # pre-reset session is dead


async def test_change_password_and_email(client):
    await _login(client)
    bad = await client.post("/api/auth/change-password",
                            json={"current_password": "nope", "new_password": "newpass99"})
    assert bad.status_code == 400
    ok = await client.post("/api/auth/change-password",
                           json={"current_password": "pw", "new_password": "newpass99"})
    assert ok.status_code == 200
    assert (await client.get("/api/auth/me")).status_code == 200  # this browser stays signed in
    r = await client.put("/api/account/email",
                         json={"email": "New@Example.com", "current_password": "newpass99"})
    assert r.json()["email"] == "new@example.com"


async def test_timed_alerts(client):
    await _login(client)
    wl = (await client.post("/api/watchlists", json={"name": "Timed"})).json()
    item = (await client.post(f"/api/watchlists/{wl['id']}/items",
                              json={"instrument_key": RELIANCE})).json()
    url = f"/api/watchlist-items/{item['id']}/alerts"
    r = await client.post(url, json={"condition": "ABOVE", "target_price": 1500,
                                     "trigger_mode": "ONCE",
                                     "check_from": "15:15:30", "check_until": "15:15"})
    assert r.status_code == 201
    body = r.json()
    assert (body["check_from"], body["check_until"]) == ("15:15:00", "15:15:00")
    assert body["trigger_mode"] == "REPEAT"  # timed alerts are daily checks

    one_end = await client.post(url, json={"condition": "ABOVE", "target_price": 1,
                                           "check_from": "15:15"})
    backwards = await client.post(url, json={"condition": "ABOVE", "target_price": 1,
                                             "check_from": "15:30", "check_until": "15:00"})
    assert one_end.status_code == backwards.status_code == 422
    bad_patch = await client.patch(f"/api/alerts/{body['id']}", json={"check_until": "15:00"})
    assert bad_patch.status_code == 422

    between = await client.patch(f"/api/alerts/{body['id']}",
                                 json={"check_from": "14:30", "check_until": "15:30"})
    assert (between.json()["check_from"], between.json()["check_until"]) == ("14:30:00", "15:30:00")
    cleared = await client.patch(f"/api/alerts/{body['id']}",
                                 json={"check_from": None, "check_until": None})
    assert cleared.json()["check_from"] is None and cleared.json()["check_until"] is None


async def test_buying_date(client):
    await _login(client)
    wl = (await client.post("/api/watchlists", json={"name": "Held"})).json()
    item = (await client.post(f"/api/watchlists/{wl['id']}/items",
                              json={"instrument_key": RELIANCE})).json()
    assert item["bought_on"] is None
    url = f"/api/watchlists/{wl['id']}/items/{item['id']}"

    r = await client.patch(url, json={"bought_on": "2024-08-12"})
    assert r.status_code == 200 and r.json()["bought_on"] == "2024-08-12"
    listed = (await client.get(f"/api/watchlists/{wl['id']}/items")).json()
    assert listed[0]["bought_on"] == "2024-08-12"

    future = (datetime.now(UTC) + timedelta(days=3)).date().isoformat()
    assert (await client.patch(url, json={"bought_on": future})).status_code == 422
    assert (await client.patch(url, json={"bought_on": "1985-01-01"})).status_code == 422

    cleared = await client.patch(url, json={"bought_on": None})
    assert cleared.json()["bought_on"] is None
    wrong_list = f"/api/watchlists/{wl['id'] + 999}/items/{item['id']}"
    assert (await client.patch(wrong_list, json={"bought_on": None})).status_code == 404


async def test_dev_ticks_resolves_symbols(client, redis):
    await _login(client)
    pubsub = redis.pubsub()
    await pubsub.subscribe("tracker:dev_ticks")
    r = await client.post("/api/dev/ticks", json={"RELIANCE": 1502})
    assert r.json()["published"] == [{"k": RELIANCE, "p": "1502"}]
    assert (await client.post("/api/dev/ticks", json={"NOPE": 1})).status_code == 404
    await pubsub.aclose()
