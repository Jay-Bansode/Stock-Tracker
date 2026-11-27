import hmac
import logging
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, status

from app.api.deps import SettingsDep, SmDep, StoreDep
from app.bot import bot_api
from app.bot.handlers import Bot

router = APIRouter(prefix="/telegram", tags=["telegram"])
log = logging.getLogger(__name__)


@router.post("/webhook", include_in_schema=False)
async def webhook(
    request: Request,
    settings: SettingsDep,
    sm: SmDep,
    store: StoreDep,
    secret: Annotated[str | None, Header(alias="X-Telegram-Bot-Api-Secret-Token")] = None,
):
    """Telegram delivers bot messages and button taps here (free-hosting / webhook mode).
    No login cookie: Telegram proves itself with the secret token set in setWebhook."""
    if not secret or not hmac.compare_digest(secret, settings.telegram_webhook_secret):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Bad secret")
    update = await request.json()
    api = bot_api(settings.telegram_bot_token, settings.telegram_api_base)
    await Bot(sm, store, api, settings).handle(update)  # never raises
    return {"ok": True}  # always 200, so Telegram doesn't redeliver a handled update
