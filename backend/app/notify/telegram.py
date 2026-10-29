import asyncio
import html
import sys

import httpx

from app.notify.base import SendError
from app.notify.formatter import AlertMessage

API = "https://api.telegram.org"


class TelegramSender:
    channel = "TELEGRAM"

    def __init__(self, token: str, chat_id: str, client: httpx.AsyncClient | None = None,
                 api_base: str = API):
        self._url = f"{api_base.rstrip('/')}/bot{token}/sendMessage"
        self._chat_id = chat_id
        self._client = client or httpx.AsyncClient(timeout=15)

    async def send_alert(self, msg: AlertMessage) -> str:
        return await self._send(msg.telegram_html())

    async def send_text(self, text: str) -> str:
        return await self._send(html.escape(text))

    async def _send(self, html_text: str) -> str:
        try:
            resp = await self._client.post(
                self._url,
                json={
                    "chat_id": self._chat_id,
                    "text": html_text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
        except httpx.HTTPError as exc:
            raise SendError(f"telegram network error: {exc!r}", retryable=True) from exc

        body = _json(resp)
        if resp.status_code == 200 and body.get("ok"):
            return str(body["result"]["message_id"])
        desc = body.get("description") or resp.text[:300]
        if resp.status_code == 429:
            retry_after = (body.get("parameters") or {}).get("retry_after")
            raise SendError(f"telegram rate limited: {desc}", retryable=True,
                            retry_after=float(retry_after) if retry_after else None)
        if resp.status_code >= 500:
            raise SendError(f"telegram {resp.status_code}: {desc}", retryable=True)
        # 400 bad chat id / 401 bad token / 403 bot blocked: retrying won't help
        raise SendError(f"telegram {resp.status_code}: {desc}", retryable=False)


def _json(resp: httpx.Response) -> dict:
    try:
        return resp.json()
    except ValueError:
        return {}


async def find_chat_ids(token: str) -> None:
    """Print chats that have messaged the bot. Send /start to your bot first."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{API}/bot{token}/getUpdates")
        body = resp.json()
    if not body.get("ok"):
        print(f"Telegram error: {body}")
        return
    seen = {}
    for update in body.get("result", []):
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
