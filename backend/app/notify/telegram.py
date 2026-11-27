"""Telegram Bot API: a small client, the alert sender, and helpers for linking chats."""

import asyncio
import html
import sys
from typing import Any

import httpx

from app.notify.base import SendError
from app.notify.formatter import AlertMessage

API = "https://api.telegram.org"

# Inline keyboard: rows of buttons, each {"text": ..., "callback_data": ...} or {"text", "url"}.
Buttons = list[list[dict[str, str]]]


class TelegramApi:
    """Thin async wrapper over the methods Tracker uses. Errors become SendError, with
    `retryable` set the same way for every call."""

    def __init__(self, token: str, api_base: str = API, client: httpx.AsyncClient | None = None):
        self._base = f"{api_base.rstrip('/')}/bot{token}"
        self._client = client or httpx.AsyncClient(timeout=15)

    async def call(self, method: str, payload: dict[str, Any] | None = None,
                   timeout: float | None = None) -> Any:
        try:
            resp = await self._client.post(f"{self._base}/{method}", json=payload or {},
                                           timeout=timeout or httpx.USE_CLIENT_DEFAULT)
        except httpx.HTTPError as exc:
            raise SendError(f"telegram network error: {exc!r}", retryable=True) from exc
        body = _json(resp)
        if resp.status_code == 200 and body.get("ok"):
            return body.get("result")
        desc = body.get("description") or resp.text[:300]
        if resp.status_code == 429:
            retry_after = (body.get("parameters") or {}).get("retry_after")
            raise SendError(f"telegram rate limited: {desc}", retryable=True,
                            retry_after=float(retry_after) if retry_after else None)
        if resp.status_code >= 500:
            raise SendError(f"telegram {resp.status_code}: {desc}", retryable=True)
        # 400 bad chat id / 401 bad token / 403 bot blocked / 409 webhook conflict: won't heal
        raise SendError(f"telegram {resp.status_code}: {desc}", retryable=False)

    async def send_message(self, chat_id: str | int, html_text: str,
                           buttons: Buttons | None = None) -> str:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": html_text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if buttons:
            payload["reply_markup"] = {"inline_keyboard": buttons}
        result = await self.call("sendMessage", payload)
        return str(result["message_id"])

    async def answer_callback(self, callback_id: str, text: str = "") -> None:
        await self.call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})

    async def edit_buttons(self, chat_id: str | int, message_id: int, buttons: Buttons) -> None:
        await self.call("editMessageReplyMarkup", {
            "chat_id": chat_id, "message_id": message_id,
            "reply_markup": {"inline_keyboard": buttons},
        })

    async def set_webhook(self, url: str, secret: str) -> None:
        await self.call("setWebhook", {
            "url": url, "secret_token": secret,
            "allowed_updates": ["message", "callback_query"], "drop_pending_updates": False,
        })

    async def delete_webhook(self) -> None:
        await self.call("deleteWebhook", {"drop_pending_updates": False})

    async def get_updates(self, offset: int | None, timeout: int = 25) -> list[dict]:
        payload: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            payload["offset"] = offset
        return await self.call("getUpdates", payload, timeout=timeout + 10) or []

    async def get_me(self) -> dict:
        return await self.call("getMe")


def alert_buttons(alert_id: int | None, status: str, app_url: str = "") -> Buttons | None:
    """Action buttons under an alert message. Fired alerts can be re-armed or disabled; after a
    button is used the keyboard is swapped to match the new state."""
    if alert_id is None:
        return None
    row: list[dict[str, str]] = []
    if status != "ACTIVE":
        row.append({"text": "🔁 Re-arm", "callback_data": f"rearm:{alert_id}"})
    if status != "DISABLED":
        row.append({"text": "🔕 Disable", "callback_data": f"disable:{alert_id}"})
    rows: Buttons = [row]
    # Telegram only accepts https links on buttons (no localhost).
    if app_url.startswith("https://"):
        rows.append([{"text": "Open Tracker", "url": f"{app_url.rstrip('/')}/alerts"}])
    return rows


class TelegramSender:
    channel = "TELEGRAM"

    def __init__(self, token: str, chat_id: str = "", client: httpx.AsyncClient | None = None,
                 api_base: str = API, app_url: str = ""):
        self._api = TelegramApi(token, api_base, client)
        self._chat_id = chat_id  # default destination when a message has no recipient
        self._app_url = app_url

    async def send_alert(self, msg: AlertMessage, to: str | None = None) -> str:
        # A just-fired alert is TRIGGERED, so it offers Re-arm and Disable.
        return await self._send(msg.telegram_html(), to,
                                alert_buttons(msg.alert_id, "TRIGGERED", self._app_url))

    async def send_text(self, text: str, to: str | None = None) -> str:
        return await self._send(html.escape(text), to)

    async def _send(self, html_text: str, to: str | None, buttons: Buttons | None = None) -> str:
        chat_id = to or self._chat_id
        if not chat_id:
            raise SendError("no Telegram chat to send to", retryable=False)
        return await self._api.send_message(chat_id, html_text, buttons)


def _json(resp: httpx.Response) -> dict:
    try:
        return resp.json()
    except ValueError:
        return {}


class TelegramLinkError(Exception):
    pass


_bot_usernames: dict[str, str] = {}


async def bot_username(token: str, api_base: str = API) -> str:
    """The bot's @username (cached), needed for t.me deep links."""
    if token not in _bot_usernames:
        try:
            me = await TelegramApi(token, api_base).get_me()
        except SendError as exc:
            raise TelegramLinkError(f"Telegram rejected the bot token or is unreachable: {exc}") from exc
        _bot_usernames[token] = me["username"]
    return _bot_usernames[token]


async def find_chat_ids(token: str) -> None:
    """Print chats that have messaged the bot. Only works while no webhook is set."""
    try:
        updates = await TelegramApi(token).get_updates(None, timeout=0)
    except SendError as exc:
        print(f"Telegram error: {exc}")
        return
    seen = {}
    for update in updates:
        chat = (update.get("message") or update.get("my_chat_member") or {}).get("chat")
        if chat:
            seen[chat["id"]] = chat.get("username") or chat.get("title") or chat.get("first_name")
    if not seen:
        print("No chats found. Open your bot in Telegram, press Start / send any message, retry.")
    for chat_id, name in seen.items():
        print(f"TELEGRAM_CHAT_ID={chat_id}    ({name})")


if __name__ == "__main__":
    from app.config import get_settings

    token = get_settings().telegram_bot_token or (sys.argv[1] if len(sys.argv) > 1 else "")
    if not token:
        sys.exit("Set TELEGRAM_BOT_TOKEN in .env or pass the token as an argument.")
    asyncio.run(find_chat_ids(token))
