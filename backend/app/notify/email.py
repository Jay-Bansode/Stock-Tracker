"""Transactional email (password resets).

Uses an HTTP API rather than SMTP because free hosts such as Render block outbound SMTP ports.
"""

import logging

import httpx

from app.config import Settings
from app.notify.base import SendError

log = logging.getLogger(__name__)

# Tests and the console provider can inspect what would have been sent.
outbox: list[dict] = []


async def send_email(settings: Settings, to: str, subject: str, text: str, html: str,
                     client: httpx.AsyncClient | None = None) -> None:
    message = {"to": to, "subject": subject, "text": text, "html": html}
    if settings.email_provider == "console":
        outbox.append(message)
        del outbox[:-50]
        log.warning("EMAIL_PROVIDER=console, not sending. To: %s | %s\n%s", to, subject, text)
        return

    if not (settings.email_api_key and settings.email_from):
        raise SendError("email is not configured: set EMAIL_API_KEY and EMAIL_FROM",
                        retryable=False)
    payload = {
        "sender": {"email": settings.email_from, "name": settings.email_from_name},
        "to": [{"email": to}],
        "subject": subject,
        "textContent": text,
        "htmlContent": html,
    }
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=15)
    try:
        resp = await client.post(
            f"{settings.brevo_api_base.rstrip('/')}/v3/smtp/email",
            json=payload,
            headers={"api-key": settings.email_api_key, "accept": "application/json"},
        )
    except httpx.HTTPError as exc:
        raise SendError(f"email network error: {exc!r}", retryable=True) from exc
    finally:
        if own_client:
            await client.aclose()
    if resp.status_code >= 300:
        raise SendError(f"email provider {resp.status_code}: {resp.text[:300]}",
                        retryable=resp.status_code >= 500 or resp.status_code == 429)
