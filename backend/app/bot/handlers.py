"""What the bot does with each Telegram update (a message or a button tap)."""

import html
import logging
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.commands import Add, Alerts, Help, Invalid, Price, Start, parse
from app.config import Settings
from app.db.models import Alert, AlertStatus, Condition, Instrument, TriggerMode, User, Watchlist, WatchlistItem
from app.db.session import CHANNEL_ALERTS_CHANGED, notify
from app.notify.base import SendError
from app.notify.formatter import format_inr
from app.notify.telegram import TelegramApi, alert_buttons
from app.runtime.store import PriceStore
from app.services.instruments import resolve_instrument

log = logging.getLogger(__name__)

MAX_ALERT_LINES = 30
STATUS_LABEL = {AlertStatus.TRIGGERED: "🎯 Target hit", AlertStatus.ACTIVE: "👀 Watching",
                AlertStatus.DISABLED: "⏸ Disabled"}

HELP = (
    "<b>Tracker bot</b>\n\n"
    "/price SYMBOL — latest price, e.g. <code>/price RELIANCE</code>\n"
    "/alerts — your alerts and their status\n"
    "/add SYMBOL &gt;= PRICE [in WATCHLIST] — new alert, e.g. <code>/add TCS below 3,800</code>\n"
    "/help — this list\n\n"
    "Alert messages have <b>Re-arm</b> and <b>Disable</b> buttons."
)
NOT_LINKED = (
    "This chat isn't linked to a Tracker account yet.\n"
    "Open Tracker → <b>Settings → Telegram alerts → Connect Telegram</b>, then press Start here."
)


def _e(value: object) -> str:
    return html.escape(str(value))


def _symbol(cond: str) -> str:
    return "≥" if cond == Condition.ABOVE else "≤"


class Bot:
    def __init__(self, sm: async_sessionmaker[AsyncSession], store: PriceStore, api: TelegramApi,
                 settings: Settings):
        self.sm, self.store, self.api, self.settings = sm, store, api, settings

    async def handle(self, update: dict) -> None:
        """Never raises: a failing update is logged and, where possible, apologised for."""
        try:
            if "callback_query" in update:
                await self._callback(update["callback_query"])
            elif (msg := update.get("message")) and msg.get("text") is not None:
                await self._message(msg)
        except Exception:
            log.exception("telegram update %s failed", update.get("update_id"))
            chat = ((update.get("message") or {}).get("chat") or {}).get("id")
            if chat is not None:
                await self._reply(chat, "Sorry, something went wrong. Please try again.")

    # --- messages -------------------------------------------------------------------------

    async def _message(self, msg: dict) -> None:
        chat_id = str(msg["chat"]["id"])
        cmd = parse(msg["text"])
        if isinstance(cmd, Start) and cmd.code:
            return await self._link(chat_id, cmd.code)

        async with self.sm() as session:
            user = await self._user(session, chat_id)
            if user is None:
                return await self._reply(chat_id, NOT_LINKED)
            match cmd:
                case Start():
                    reply = f"Hi {_e(user.username)} 👋\n\n{HELP}"
                case Help():
                    reply = HELP
                case Invalid(message):
                    reply = _e(message)
                case Price(symbol):
                    reply = await self._price(session, symbol)
                case Alerts():
                    reply = await self._alerts(session, user)
                case Add():
                    reply = await self._add(session, user, cmd)
        await self._reply(chat_id, reply)

    async def _link(self, chat_id: str, code: str) -> None:
        async with self.sm() as session, session.begin():
            user = await session.scalar(select(User).where(User.telegram_link_code == code))
            if user is None:
                reply = "This link has expired. In Tracker, click <b>Connect Telegram</b> again."
            else:
                # One Tracker account per chat, so commands always know whose alerts to use.
                await session.execute(sql_update(User).where(User.telegram_chat_id == chat_id, User.id != user.id)
                                      .values(telegram_chat_id=None))
                user.telegram_chat_id, user.telegram_link_code = chat_id, None
                reply = (f"✅ Connected to Tracker as <b>{_e(user.username)}</b>. "
                         f"Your price alerts will arrive here.\n\n{HELP}")
        await self._reply(chat_id, reply)

    async def _price(self, session: AsyncSession, symbol: str) -> str:
        inst = await resolve_instrument(session, symbol)
        if inst is None:
            return f"I couldn't find <b>{_e(symbol)}</b>. Use the NSE/BSE symbol, e.g. RELIANCE."
        quote = (await self.store.get_prices([inst.instrument_key])).get(inst.instrument_key)
        head = f"<b>{_e(inst.trading_symbol)}</b> · {_e(inst.name)} ({_e(inst.exchange)})"
        if not quote or quote.get("p") is None:
            return f"{head}\nNo price yet. Prices update during market hours."
        price = Decimal(str(quote["p"]))
        line = f"{head}\n<b>{format_inr(price)}</b>"
        if quote.get("c"):
            close = Decimal(str(quote["c"]))
            pct = (price - close) / close * 100
            line += f"  {'▲' if pct >= 0 else '▼'} {pct:+.2f}% today"
        return line

    async def _alerts(self, session: AsyncSession, user: User) -> str:
        rows = (await session.execute(
            select(Alert, Watchlist.name, Instrument.trading_symbol)
            .join(WatchlistItem, Alert.watchlist_item_id == WatchlistItem.id)
            .join(Watchlist, WatchlistItem.watchlist_id == Watchlist.id)
            .join(Instrument, WatchlistItem.instrument_key == Instrument.instrument_key)
            .where(Watchlist.user_id == user.id)
            .order_by(case((Alert.status == AlertStatus.TRIGGERED, 0),
                           (Alert.status == AlertStatus.ACTIVE, 1), else_=2),
                      Watchlist.sort_order, Instrument.trading_symbol)
        )).all()
        if not rows:
            return "You have no alerts yet. Add one with <code>/add RELIANCE &gt;= 1500</code>."
        lines = [f"<b>Your alerts ({len(rows)})</b>"]
        for alert, wl_name, sym in rows[:MAX_ALERT_LINES]:
            lines.append(f"• <b>{_e(sym)}</b> {_symbol(alert.condition)} {format_inr(alert.target_price)}"
                         f" · {_e(wl_name)} — {STATUS_LABEL.get(alert.status, alert.status)}")
        if len(rows) > MAX_ALERT_LINES:
            lines.append(f"…and {len(rows) - MAX_ALERT_LINES} more in Tracker.")
        return "\n".join(lines)

    async def _add(self, session: AsyncSession, user: User, cmd: Add) -> str:
        inst = await resolve_instrument(session, cmd.symbol)
        if inst is None:
            return f"I couldn't find <b>{_e(cmd.symbol)}</b>. Use the NSE/BSE symbol, e.g. RELIANCE."
        lists = list(await session.scalars(
            select(Watchlist).where(Watchlist.user_id == user.id).order_by(Watchlist.sort_order, Watchlist.id)))

        if cmd.watchlist:
            target_list = next((w for w in lists if w.name.lower() == cmd.watchlist.lower()), None)
            if target_list is None:
                names = ", ".join(_e(w.name) for w in lists) or "none yet"
                return f"No watchlist called <b>{_e(cmd.watchlist)}</b>. Yours: {names}."
            item = await session.scalar(select(WatchlistItem).where(
                WatchlistItem.watchlist_id == target_list.id, WatchlistItem.instrument_key == inst.instrument_key))
        else:
            # Prefer a watchlist that already holds this stock, then the first one.
            item = await session.scalar(
                select(WatchlistItem)
                .join(Watchlist, WatchlistItem.watchlist_id == Watchlist.id)
                .where(Watchlist.user_id == user.id, WatchlistItem.instrument_key == inst.instrument_key)
                .order_by(Watchlist.sort_order, Watchlist.id).limit(1))
            target_list = next((w for w in lists if item and w.id == item.watchlist_id), None) or (lists[0] if lists else None)
            if target_list is None:
                next_order = await session.scalar(select(func.coalesce(func.max(Watchlist.sort_order), 0))
                                                  .where(Watchlist.user_id == user.id))
                target_list = Watchlist(user_id=user.id, name="Telegram", sort_order=next_order + 1)
                session.add(target_list)
                await session.flush()

        if item is None:
            item = WatchlistItem(watchlist_id=target_list.id, instrument_key=inst.instrument_key)
            session.add(item)
            await session.flush()
        alert = Alert(watchlist_item_id=item.id, condition=cmd.condition, target_price=cmd.target,
                      trigger_mode=TriggerMode.ONCE, status=AlertStatus.ACTIVE)
        session.add(alert)
        await notify(session, CHANNEL_ALERTS_CHANGED)
        await session.commit()

        reply = (f"✅ Alert added: <b>{_e(inst.trading_symbol)}</b> {_symbol(cmd.condition)} "
                 f"{format_inr(cmd.target)} in <b>{_e(target_list.name)}</b>.")
        ltp = await self.store.get_ltp(inst.instrument_key)
        if ltp is not None:
            met = ltp >= cmd.target if cmd.condition == Condition.ABOVE else ltp <= cmd.target
            reply += f"\nCurrent price {format_inr(ltp)}" + (" — already met, so it fires on the next check." if met else ".")
        return reply

    # --- button taps ------------------------------------------------------------------------

    async def _callback(self, cq: dict) -> None:
        msg = cq.get("message") or {}
        chat_id = str((msg.get("chat") or {}).get("id", ""))
        action, _, raw_id = (cq.get("data") or "").partition(":")
        toast = "This alert no longer exists."
        new_status = {"rearm": AlertStatus.ACTIVE, "disable": AlertStatus.DISABLED}.get(action)

        if new_status and raw_id.isdigit():
            async with self.sm() as session:
                user = await self._user(session, chat_id)
                alert = user and await session.scalar(
                    select(Alert)
                    .join(WatchlistItem, Alert.watchlist_item_id == WatchlistItem.id)
                    .join(Watchlist, WatchlistItem.watchlist_id == Watchlist.id)
                    .where(Alert.id == int(raw_id), Watchlist.user_id == user.id))
                if user is None:
                    toast = "Link this chat in Tracker first."
                elif alert is not None:
                    alert.status = new_status
                    await notify(session, CHANNEL_ALERTS_CHANGED)
                    await session.commit()
                    toast = "Re-armed ✓ — watching again" if new_status == AlertStatus.ACTIVE else "Disabled ✓"
                    try:
                        await self.api.edit_buttons(chat_id, msg["message_id"],
                                                    alert_buttons(alert.id, new_status, self.settings.app_base_url))
                    except (SendError, KeyError):
                        pass  # the status changed either way; old buttons are cosmetic
        try:
            await self.api.answer_callback(cq["id"], toast)
        except SendError:
            log.warning("could not answer telegram callback %s", cq.get("id"))

    # --- helpers --------------------------------------------------------------------------

    @staticmethod
    async def _user(session: AsyncSession, chat_id: str) -> User | None:
        return await session.scalar(select(User).where(User.telegram_chat_id == chat_id).limit(1)) if chat_id else None

    async def _reply(self, chat_id: str | int, html_text: str) -> None:
        try:
            await self.api.send_message(chat_id, html_text)
        except SendError as exc:
            log.warning("telegram reply to %s failed: %s", chat_id, exc)
