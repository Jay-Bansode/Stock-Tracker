import hashlib
import html
import logging
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import (
    COOKIE_NAME,
    CurrentUser,
    SessionDep,
    SettingsDep,
    check_password,
    client_ip,
    find_user_by_login,
    forgot_throttle,
    hash_password,
    login_throttle,
    register_throttle,
    set_session_cookie,
)
from app.api.schemas import (
    ChangePasswordIn,
    ForgotPasswordIn,
    LoginIn,
    Me,
    RegisterIn,
    ResetPasswordIn,
)
from app.config import Settings
from app.db.models import PasswordResetToken, User
from app.notify.base import SendError
from app.notify.email import send_email

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger(__name__)

FORGOT_REPLY = {"detail": "If that email has an account, a reset link is on its way."}


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@router.post("/register", response_model=Me, status_code=201)
async def register(body: RegisterIn, request: Request, response: Response,
                   session: SessionDep, settings: SettingsDep):
    if not settings.registration_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Registration is closed")
    ip = client_ip(request)
    if register_throttle.blocked(ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many sign-ups; try later")
    username, email = body.username.strip(), body.email.strip().lower()
    taken = await session.scalar(
        select(User.id).where((func.lower(User.username) == username.lower())
                              | (User.email == email))
    )
    if taken:
        raise HTTPException(status.HTTP_409_CONFLICT, "That username or email is already registered")
    user = User(username=username, email=email, password_hash=hash_password(body.password))
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:  # lost a race with an identical sign-up
        raise HTTPException(status.HTTP_409_CONFLICT, "That username or email is already registered")
    register_throttle.hit(ip)
    await session.refresh(user)
    set_session_cookie(response, settings, user)
    return Me.of(user)


@router.post("/login", response_model=Me)
async def login(body: LoginIn, request: Request, response: Response, session: SessionDep,
                settings: SettingsDep):
    ip = client_ip(request)
    if login_throttle.blocked(ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed logins; try later")
    user = await find_user_by_login(session, body.username)
    if not check_password(body.password, user.password_hash if user else None) or user is None:
        login_throttle.hit(ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    login_throttle.reset(ip)
    set_session_cookie(response, settings, user)
    return Me.of(user)


@router.post("/logout", status_code=204)
async def logout(response: Response):
    response.delete_cookie(COOKIE_NAME)


@router.get("/me", response_model=Me)
async def me(user: CurrentUser):
    return Me.of(user)


async def _send_reset_email(settings: Settings, to: str, username: str, link: str) -> None:
    minutes = settings.reset_token_ttl_minutes
    text = (f"Hi {username},\n\nSomeone asked to reset your Tracker password. Open this link to "
            f"choose a new one (valid for {minutes} minutes):\n\n{link}\n\n"
            "If it wasn't you, ignore this email; your password stays the same.")
    body = (f"<p>Hi {html.escape(username)},</p><p>Someone asked to reset your Tracker password. "
            f'<a href="{html.escape(link)}">Choose a new password</a> (valid for {minutes} '
            "minutes).</p><p>If it wasn't you, ignore this email; your password stays the "
            "same.</p>")
    try:
        await send_email(settings, to, "Reset your Tracker password", text, body)
    except SendError as exc:
        log.error("password reset email to %s failed: %s", to, exc)


@router.post("/forgot-password", status_code=202)
async def forgot_password(body: ForgotPasswordIn, request: Request, background: BackgroundTasks,
                          session: SessionDep, settings: SettingsDep):
    """Always answers the same way, so it can't be used to find out who has an account."""
    ip = client_ip(request)
    if forgot_throttle.blocked(ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests; try later")
    forgot_throttle.hit(ip)
    user = await session.scalar(select(User).where(User.email == body.email.strip().lower()))
    if user is None:
        return FORGOT_REPLY
    token = secrets.token_urlsafe(32)
    session.add(PasswordResetToken(
        user_id=user.id,
        token_hash=_token_hash(token),
        expires_at=datetime.now(UTC) + timedelta(minutes=settings.reset_token_ttl_minutes),
    ))
    await session.commit()
    base = (settings.app_base_url or str(request.base_url)).rstrip("/")
    # Sent after the response, so response time doesn't reveal whether the account exists.
    background.add_task(_send_reset_email, settings, user.email, user.username,
                        f"{base}/reset-password?token={token}")
    return FORGOT_REPLY


@router.post("/reset-password", response_model=Me)
async def reset_password(body: ResetPasswordIn, response: Response, session: SessionDep,
                         settings: SettingsDep):
    row = await session.scalar(
        select(PasswordResetToken)
        .where(PasswordResetToken.token_hash == _token_hash(body.token),
               PasswordResetToken.used_at.is_(None),
               PasswordResetToken.expires_at > func.now())
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "This reset link is invalid or has expired. Request a new one.")
    user = await session.get(User, row.user_id)
    user.password_hash = hash_password(body.password)
    user.password_version += 1  # signs out every existing session
    await session.execute(
        delete(PasswordResetToken).where(PasswordResetToken.user_id == user.id))
    await session.commit()
    await session.refresh(user)
    set_session_cookie(response, settings, user)
    return Me.of(user)


@router.post("/change-password", response_model=Me)
async def change_password(body: ChangePasswordIn, request: Request, response: Response,
                          user: CurrentUser, session: SessionDep, settings: SettingsDep):
    ip = client_ip(request)
    if login_throttle.blocked(ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed attempts; try later")
    if not check_password(body.current_password, user.password_hash):
        login_throttle.hit(ip)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is wrong")
    user.password_hash = hash_password(body.new_password)
    user.password_version += 1  # other devices get signed out; this one gets a fresh cookie
    await session.commit()
    await session.refresh(user)
    set_session_cookie(response, settings, user)
    return Me.of(user)
