from decimal import Decimal as D

import pytest
from sqlalchemy import select

from app.bot.handlers import NOT_LINKED, Bot
from app.config import Settings
from app.db.models import Alert, User, Watchlist, WatchlistItem
from app.marketdata.base import Tick
from app.runtime.store import PgStore
from tests.conftest import HDFCBANK, RELIANCE, make_user

ADMIN_CHAT = "123"  # the `owner` fixture's linked chat


class FakeApi:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []
        self.toasts: list[str] = []
        self.edited: list[tuple[str, int, list]] = []

    async def send_message(self, chat_id, html_text, buttons=None):
        self.sent.append((str(chat_id), html_text))
        return "1"

    async def answer_callback(self, callback_id, text=""):
        self.toasts.append(text)

    async def edit_buttons(self, chat_id, message_id, buttons):
        self.edited.append((str(chat_id), message_id, buttons))


def msg(chat, text):
    return {"update_id": 1, "message": {"message_id": 1, "chat": {"id": int(chat)}, "text": text}}


def tap(chat, data):
    return {"update_id": 2, "callback_query": {"id": "cb", "data": data,
                                               "message": {"message_id": 9, "chat": {"id": int(chat)}}}}


@pytest.fixture
def bot(sm):
    api = FakeApi()
    return Bot(sm, PgStore(sm), api, Settings(_env_file=None)), api


async def _reply(bot_and_api, chat, text):
    b, api = bot_and_api
    await b.handle(msg(chat, text))
    assert api.sent and api.sent[-1][0] == str(chat)
    return api.sent[-1][1]


async def test_start_code_links_the_chat_instantly(sm, bot, owner):
    await make_user(sm, "bob", telegram_link_code="code1")
    reply = await _reply(bot, 555, "/start code1")
    assert "Connected to Tracker as <b>bob</b>" in reply
    async with sm() as s:
        bob = await s.scalar(select(User).where(User.username == "bob"))
    assert (bob.telegram_chat_id, bob.telegram_link_code) == ("555", None)

    assert "expired" in await _reply(bot, 556, "/start code1")  # single use


async def test_linking_a_chat_moves_it_off_another_account(sm, bot, owner):
    await make_user(sm, "bob", telegram_link_code="code2")
    await _reply(bot, ADMIN_CHAT, "/start code2")
    async with sm() as s:
        chats = dict((await s.execute(select(User.username, User.telegram_chat_id))).all())
    assert chats == {"admin": None, "bob": ADMIN_CHAT}  # one account per chat


async def test_unlinked_chat_is_told_how_to_link(bot, owner):
    assert await _reply(bot, 999, "/alerts") == NOT_LINKED


async def test_price(sm, bot, example):
    await PgStore(sm).publish_ticks([Tick(RELIANCE, D("1502"), close=D("1490"))])
    reply = await _reply(bot, ADMIN_CHAT, "/price reliance")
    assert "<b>RELIANCE</b>" in reply and "₹1,502" in reply and "+0.81% today" in reply
    assert "No price yet" in await _reply(bot, ADMIN_CHAT, "/price HDFCBANK")
    assert "couldn't find" in await _reply(bot, ADMIN_CHAT, "/price NOPE")


async def test_alerts_lists_only_your_own(sm, bot, example):
    reply = await _reply(bot, ADMIN_CHAT, "/alerts")
    assert "Your alerts (3)" in reply and "HDFCBANK" in reply and "Banking Stocks" in reply
    await make_user(sm, "bob", telegram_chat_id="777")
    assert "no alerts yet" in await _reply(bot, 777, "/alerts")


async def test_add_uses_the_right_watchlist(sm, bot, example):
    reply = await _reply(bot, ADMIN_CHAT, "/add HDFCBANK >= 1800")
    assert "Alert added" in reply and "Banking Stocks" in reply  # the list already holding it
    reply = await _reply(bot, ADMIN_CHAT, "/add RELIANCE below 1,400 in intraday stocks")
    assert "Intraday Stocks" in reply
    assert "No watchlist called" in await _reply(bot, ADMIN_CHAT, "/add RELIANCE >= 1 in Nope")

    async with sm() as s:
        rows = (await s.execute(
            select(Watchlist.name, Alert.condition, Alert.target_price, Alert.status)
            .join(WatchlistItem, Alert.watchlist_item_id == WatchlistItem.id)
            .join(Watchlist, WatchlistItem.watchlist_id == Watchlist.id)
            .where(Alert.target_price.in_([D("1800"), D("1400")]))
            .order_by(Alert.id)
        )).all()
    assert rows == [("Banking Stocks", "ABOVE", D("1800.00"), "ACTIVE"),
                    ("Intraday Stocks", "BELOW", D("1400.00"), "ACTIVE")]


async def test_add_creates_a_telegram_watchlist_when_you_have_none(sm, bot, example):
    await make_user(sm, "bob", telegram_chat_id="777")
    assert "in <b>Telegram</b>" in await _reply(bot, 777, "/add RELIANCE >= 1")
    async with sm() as s:
        bob = await s.scalar(select(User).where(User.username == "bob"))
        names = (await s.scalars(select(Watchlist.name).where(Watchlist.user_id == bob.id))).all()
    assert names == ["Telegram"]


async def test_buttons_disable_and_rearm_only_your_alerts(sm, bot, example):
    b, api = bot
    alert_id = example["Long-Term Stocks"]
    await b.handle(tap(ADMIN_CHAT, f"disable:{alert_id}"))
    assert api.toasts[-1] == "Disabled ✓"
    assert api.edited[-1][1] == 9  # the alert message's buttons were swapped
    await b.handle(tap(ADMIN_CHAT, f"rearm:{alert_id}"))
    assert api.toasts[-1].startswith("Re-armed")

    await make_user(sm, "bob", telegram_chat_id="777")
    await b.handle(tap(777, f"disable:{alert_id}"))  # someone else's alert
    assert api.toasts[-1] == "This alert no longer exists."
    async with sm() as s:
        assert (await s.get(Alert, alert_id)).status == "ACTIVE"
