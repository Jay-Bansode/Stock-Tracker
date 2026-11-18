import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from typing import Annotated

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, Response, status
from redis.asyncio import Redis
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.db.models import User
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


# Compared against when the account doesn't exist, so a miss costs the same time as a hit.
_DUMMY_HASH = bcrypt.hashpw(b"timing-equaliser", bcrypt.gensalt()).decode()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def check_password(password: str, password_hash: str | None) -> bool:
    try:
        ok = bcrypt.checkpw(password.encode(), (password_hash or _DUMMY_HASH).encode())
    except ValueError:  # malformed hash, e.g. the "!" placeholder for "no password set"
        return False
    return ok and password_hash is not None


async def find_user_by_login(session: AsyncSession, login: str) -> User | None:
    """Look a user up by username (case-insensitive) or email."""
    login = login.strip().lower()
    return await session.scalar(
        select(User).where(or_(func.lower(User.username) == login, User.email == login))
    )


def issue_token(settings: Settings, user: User) -> str:
    exp = datetime.now(UTC) + timedelta(hours=settings.session_ttl_hours)
    claims = {"sub": str(user.id), "pv": user.password_version, "exp": exp}
    return jwt.encode(claims, settings.secret_key, algorithm=JWT_ALG)


def set_session_cookie(response: Response, settings: Settings, user: User) -> None:
    response.set_cookie(
        COOKIE_NAME,
        issue_token(settings, user),
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )


async def user_from_token(session: AsyncSession, settings: Settings,
                          token: str | None) -> User | None:
    if not token:
        return None
    try:
        claims = jwt.decode(token, settings.secret_key, algorithms=[JWT_ALG])
        user_id = int(claims["sub"])
    except (jwt.PyJWTError, KeyError, ValueError, TypeError):
        return None
    user = await session.get(User, user_id)
    # A password change/reset bumps password_version, which invalidates older sessions.
    if user is None or claims.get("pv") != user.password_version:
        return None
    return user


async def current_user(request: Request, session: SessionDep, settings: SettingsDep) -> User:
    user = await user_from_token(session, settings, request.cookies.get(COOKIE_NAME))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require_admin(user: CurrentUser) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admins only")
    return user


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


class Throttle:
    """At most `limit` hits per key (client IP) per `window` seconds."""

    def __init__(self, limit: int, window: float):
        self._limit, self._window = limit, window
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str) -> deque[float]:
        q = self._hits[key]
        while q and time.monotonic() - q[0] > self._window:
            q.popleft()
        return q

    def blocked(self, key: str) -> bool:
        return len(self._prune(key)) >= self._limit

    def hit(self, key: str) -> None:
        self._prune(key).append(time.monotonic())

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)

    def clear(self) -> None:
        self._hits.clear()


login_throttle = Throttle(limit=5, window=900)  # failed logins
forgot_throttle = Throttle(limit=5, window=3600)  # reset emails requested
register_throttle = Throttle(limit=10, window=3600)  # accounts created
