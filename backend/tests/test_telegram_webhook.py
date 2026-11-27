import httpx
import pytest

from app.api.deps import get_redis, get_sm, get_store
from app.bot.handlers import NOT_LINKED
from app.config import Settings, get_settings
from app.db.session import get_session
from app.main import create_app
from app.runtime.store import PgStore
from tests.conftest import make_user
from tests.test_bot_handlers import FakeApi, msg

SETTINGS = Settings(_env_file=None, telegram_bot_token="TOKEN", run_mode="cron",
                    secret_key="test-secret-key-that-is-long-enough-for-hs256")


@pytest.fixture
def app_and_api(sm, monkeypatch):
    monkeypatch.setattr("app.main.get_settings", lambda: SETTINGS)
    api = FakeApi()
    monkeypatch.setattr("app.api.telegram.bot_api", lambda *a: api)
    app = create_app()
    app.state.redis, app.state.store = None, PgStore(sm)

    async def session_override():
        async with sm() as s:
            yield s

    app.dependency_overrides.update({get_session: session_override, get_settings: lambda: SETTINGS,
                                     get_sm: lambda: sm, get_redis: lambda: None,
                                     get_store: lambda: PgStore(sm)})
    return app, api


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_webhook_requires_telegrams_secret(app_and_api, owner):
    app, api = app_and_api
    async with _client(app) as c:
        url = "/api/telegram/webhook"
        assert (await c.post(url, json=msg(999, "/alerts"))).status_code == 403
        bad = {"X-Telegram-Bot-Api-Secret-Token": "nope"}
        assert (await c.post(url, json=msg(999, "/alerts"), headers=bad)).status_code == 403
        assert api.sent == []

        good = {"X-Telegram-Bot-Api-Secret-Token": SETTINGS.telegram_webhook_secret}
        r = await c.post(url, json=msg(999, "/alerts"), headers=good)
        assert r.status_code == 200
        assert api.sent == [("999", NOT_LINKED)]


async def test_verify_reports_whether_the_bot_has_linked_you(app_and_api, sm, owner):
    app, _ = app_and_api
    await make_user(sm, "bob", "password1")
    async with _client(app) as c:
        await c.post("/api/auth/login", json={"username": "bob", "password": "password1"})
        assert (await c.post("/api/account/telegram/verify")).status_code == 404
    async with _client(app) as c:
        await c.post("/api/auth/login", json={"username": "admin", "password": "pw"})
        r = await c.post("/api/account/telegram/verify")
        assert r.status_code == 200 and r.json()["telegram_linked"] is True


def test_transport_choice():
    s = lambda **kw: Settings(_env_file=None, telegram_bot_token="T", **kw)  # noqa: E731
    assert s(run_mode="services").telegram_transport == "polling"
    assert s(run_mode="cron", app_base_url="https://x.onrender.com").telegram_transport == "webhook"
    assert s(run_mode="cron", app_base_url="").telegram_transport is None  # no public https URL
    assert s(run_mode="services", telegram_mode="off").telegram_transport is None
    assert Settings(_env_file=None).telegram_transport is None  # no bot token
