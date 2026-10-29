from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.api.deps import (
    COOKIE_NAME,
    SettingsDep,
    issue_token,
    login_throttle,
    require_user,
    verify_credentials,
)
from app.api.schemas import LoginIn, Me

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=Me)
async def login(body: LoginIn, request: Request, response: Response, settings: SettingsDep):
    ip = request.client.host if request.client else "unknown"
    if login_throttle.blocked(ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed logins; try later")
    if not verify_credentials(settings, body.username, body.password):
        login_throttle.fail(ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    login_throttle.reset(ip)
    response.set_cookie(
        COOKIE_NAME,
        issue_token(settings, body.username),
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )
    return Me(username=body.username)


@router.post("/logout", status_code=204)
async def logout(response: Response):
    response.delete_cookie(COOKIE_NAME)


@router.get("/me", response_model=Me)
async def me(user: Annotated[str, Depends(require_user)]):
    return Me(username=user)
