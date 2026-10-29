"""Endpoints an external scheduler (e.g. cron-job.org) calls in cron (free-hosting) mode."""

import hmac
import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, status

from app.api.deps import SettingsDep, SmDep
from app.engine.poll import get_runtime
from app.marketdata.instruments_sync import refresh_instruments

log = logging.getLogger(__name__)


def require_cron_secret(settings: SettingsDep,
                        x_cron_secret: Annotated[str | None, Header()] = None) -> None:
    if not settings.cron_secret:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    if not x_cron_secret or not hmac.compare_digest(x_cron_secret.encode(),
                                                    settings.cron_secret.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bad cron secret")


router = APIRouter(prefix="/cron", tags=["cron"], dependencies=[Depends(require_cron_secret)])


@router.post("/poll")
async def poll(settings: SettingsDep, sm: SmDep):
    """Fetch prices, evaluate alerts and deliver notifications. Call every minute in market hours."""
    return await get_runtime(settings, sm).run_cycle()


@router.post("/instruments", status_code=202)
async def instruments(settings: SettingsDep, sm: SmDep, background: BackgroundTasks,
                      force: bool = False):
    """Refresh the stock list (skipped if refreshed within 20 h unless force=true). Runs after
    the response so the scheduler's 30 s timeout doesn't matter."""

    async def run():
        log.info("instrument refresh: %s", await refresh_instruments(sm, settings, force=force))

    background.add_task(run)
    return {"status": "started"}
