import hmac
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from typing import Annotated

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.db.session import get_session, get_sessionmaker
from app.runtime.store import PriceStore

COOKIE_NAME = "tracker_session"
JWT_ALG = "HS256"

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_redis(request: Request) -> Redis | None:
    return request.app.state.redis  # None in cron mode


def get_store(request: Request) -> PriceStore:
    return request.app.state.store


def get_sm() -> async_sessionmaker[AsyncSession]:
    return get_sessionmaker()


RedisDep = Annotated[Redis | None, Depends(get_redis)]
StoreDep = Annotated[PriceStore, Depends(get_store)]
SmDep = Annotated[async_sessionmaker[AsyncSession], Depends(get_sm)]


def verify_credentials(settings: Settings, username: str, password: str) -> bool:
    if not hmac.compare_digest(username.encode(), settings.admin_username.encode()):
        return False
    if settings.admin_password_hash:
        try:
            return bcrypt.checkpw(password.encode(), settings.admin_password_hash.encode())
        except ValueError:
            return False
    if settings.admin_password:
        return hmac.compare_digest(password.encode(), settings.admin_password.encode())
    return False


def issue_token(settings: Settings, username: str) -> str:
    exp = datetime.now(UTC) + timedelta(hours=settings.session_ttl_hours)
    return jwt.encode({"sub": username, "exp": exp}, settings.secret_key, algorithm=JWT_ALG)


def user_from_token(settings: Settings, token: str | None) -> str | None:
    if not token:
        return None
    try:
        claims = jwt.decode(token, settings.secret_key, algorithms=[JWT_ALG])
    except jwt.PyJWTError:
        return None
    sub = claims.get("sub")
    return sub if sub == settings.admin_username else None


def require_user(request: Request, settings: SettingsDep) -> str:
    user = user_from_token(settings, request.cookies.get(COOKIE_NAME))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    return user


class LoginThrottle:
    """At most 5 failed logins per client IP per 15 minutes."""

    def __init__(self, limit: int = 5, window: float = 900):
        self._limit, self._window = limit, window
        self._fails: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, ip: str) -> deque[float]:
        q = self._fails[ip]
        while q and time.monotonic() - q[0] > self._window:
            q.popleft()
        return q

    def blocked(self, ip: str) -> bool:
        return len(self._prune(ip)) >= self._limit

    def fail(self, ip: str) -> None:
        self._prune(ip).append(time.monotonic())

    def reset(self, ip: str) -> None:
        self._fails.pop(ip, None)


login_throttle = LoginThrottle()
