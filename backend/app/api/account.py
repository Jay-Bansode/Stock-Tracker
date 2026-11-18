import secrets

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.api.deps import (
    CurrentUser,
    SessionDep,
    SettingsDep,
    check_password,
    client_ip,
    login_throttle,
)
from app.api.schemas import ChangeEmailIn, Me
from app.db.models import User
from app.notify.base import SendError
from app.notify.telegram import TelegramLinkError, TelegramSender, bot_username, find_start_code

router = APIRouter(prefix="/account", tags=["account"])


def _require_bot(settings) -> str:
    if not settings.telegram_bot_token:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Telegram isn't set up on this server (TELEGRAM_BOT_TOKEN)")
    return settings.telegram_bot_token


@router.put("/email", response_model=Me)
async def change_email(body: ChangeEmailIn, request: Request, user: CurrentUser,
                       session: SessionDep):
    ip = client_ip(request)
    if login_throttle.blocked(ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed attempts; try later")
    if not check_password(body.current_password, user.password_hash):
        login_throttle.hit(ip)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is wrong")
    email = body.email.strip().lower()
    if email != user.email:
        if await session.scalar(select(User.id).where(User.email == email)):
            raise HTTPException(status.HTTP_409_CONFLICT, "That email is already registered")
        user.email = email
        await session.commit()
    return Me.of(user)


@router.post("/telegram/link")
async def telegram_link(user: CurrentUser, session: SessionDep, settings: SettingsDep):
    """Start linking: the user opens the returned t.me link and presses Start."""
    token = _require_bot(settings)
    try:
        bot = await bot_username(token, settings.telegram_api_base)
    except TelegramLinkError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))
    user.telegram_link_code = secrets.token_urlsafe(16)
    await session.commit()
    return {"url": f"https://t.me/{bot}?start={user.telegram_link_code}", "bot": bot}


@router.post("/telegram/verify", response_model=Me)
async def telegram_verify(user: CurrentUser, session: SessionDep, settings: SettingsDep):
    """Finish linking: find the /start message carrying this user's code."""
    token = _require_bot(settings)
    if not user.telegram_link_code:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Click Connect Telegram first")
    try:
        chat_id = await find_start_code(token, user.telegram_link_code,
                                        settings.telegram_api_base)
    except TelegramLinkError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))
    if chat_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "No Start message found yet. Open the link, press Start in "
                            "Telegram, then try again.")
    user.telegram_chat_id, user.telegram_link_code = chat_id, None
    await session.commit()
    try:
        await TelegramSender(token, api_base=settings.telegram_api_base).send_text(
            f"✅ Connected to Tracker as {user.username}. Your price alerts will arrive here.",
            to=chat_id)
    except SendError:
        pass  # linked either way; the Settings page has a test button
    return Me.of(user)


@router.delete("/telegram", response_model=Me)
async def telegram_unlink(user: CurrentUser, session: SessionDep):
    user.telegram_chat_id = user.telegram_link_code = None
    await session.commit()
    return Me.of(user)
