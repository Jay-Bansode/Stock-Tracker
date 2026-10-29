import httpx

from app.notify.base import SendError
from app.notify.formatter import AlertMessage

# Graph API error codes worth retrying: throttling (4, 80007, 130429), per-recipient pair rate
# limit (131056), and transient/unknown service errors (1, 2, 131000).
RETRYABLE_CODES = {1, 2, 4, 80007, 130429, 131000, 131056}
PAIR_RATE_LIMIT_CODE = 131056


class WhatsAppSender:
    """Meta WhatsApp Cloud API. Business-initiated messages must use an approved template, so
    alerts go out as the `stock_price_alert` utility template with six body parameters."""

    channel = "WHATSAPP"

    def __init__(self, token: str, phone_number_id: str, to: str, template: str,
                 language: str = "en", graph_version: str = "v21.0",
                 client: httpx.AsyncClient | None = None,
                 api_base: str = "https://graph.facebook.com"):
        self._url = f"{api_base.rstrip('/')}/{graph_version}/{phone_number_id}/messages"
        self._headers = {"Authorization": f"Bearer {token}"}
        self._to = to.lstrip("+").replace(" ", "")
        self._template = template
        self._language = language
        self._client = client or httpx.AsyncClient(timeout=20)

    def payload(self, msg: AlertMessage) -> dict:
        return {
            "messaging_product": "whatsapp",
            "to": self._to,
            "type": "template",
            "template": {
                "name": self._template,
                "language": {"code": self._language},
                "components": [
                    {
                        "type": "body",
                        "parameters": [{"type": "text", "text": p} for p in msg.whatsapp_params()],
                    }
                ],
            },
        }

    async def send_alert(self, msg: AlertMessage) -> str:
        try:
            resp = await self._client.post(self._url, json=self.payload(msg), headers=self._headers)
        except httpx.HTTPError as exc:
            raise SendError(f"whatsapp network error: {exc!r}", retryable=True) from exc

        try:
            body = resp.json()
        except ValueError:
            body = {}
        if resp.status_code == 200 and body.get("messages"):
            return body["messages"][0]["id"]

        err = body.get("error") or {}
        code = err.get("code")
        detail = f"whatsapp {resp.status_code} code={code}: {err.get('message') or resp.text[:300]}"
        if code == PAIR_RATE_LIMIT_CODE:
            raise SendError(detail, retryable=True, retry_after=6)
        if resp.status_code == 429 or resp.status_code >= 500 or code in RETRYABLE_CODES:
            raise SendError(detail, retryable=True)
        # e.g. 190 expired token, 132001 template missing/not approved, 131030 recipient not allowed
        raise SendError(detail, retryable=False)

    async def send_text(self, text: str) -> str:
        raise SendError("free-form WhatsApp messages need an open 24h session; "
                        "system messages go to Telegram only", retryable=False)
