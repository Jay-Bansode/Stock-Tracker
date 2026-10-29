import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from redis.asyncio import Redis

from app.api import alerts, auth, cron, history, instruments, system, watchlists, ws
from app.api.deps import require_user
from app.config import get_settings
from app.db.session import get_sessionmaker
from app.logging_setup import setup_logging
from app.marketdata.instruments_sync import refresh_instruments
from app.runtime.store import PgStore, RedisStore

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    settings = get_settings()
    if settings.run_mode == "cron":
        app.state.redis = None
        app.state.store = PgStore(get_sessionmaker())
        # First boot on a fresh database: fetch the stock list in the background so search
        # works without waiting for the daily cron call.
        async def ensure_instruments():
            try:
                log.info("instruments: %s",
                         await refresh_instruments(get_sessionmaker(), settings))
            except Exception:
                log.exception("instrument refresh failed")

        task = asyncio.create_task(ensure_instruments())
    else:
        app.state.redis = Redis.from_url(settings.redis_url, decode_responses=True)
        app.state.store = RedisStore(app.state.redis)
        task = None
    yield
    if task:
        task.cancel()
    if app.state.redis is not None:
        await app.state.redis.aclose()


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    """Serve the built dashboard from the API so both share one origin (the login cookie then
    works without third-party-cookie problems on free hosts)."""
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")
    index = dist / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path.startswith(("api/", "ws/")):
            raise HTTPException(404)
        file = (dist / path).resolve()
        if path and file.is_file() and dist.resolve() in file.parents:
            return FileResponse(file)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Tracker", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    api = APIRouter(prefix="/api")
    api.include_router(auth.router)
    protected = [Depends(require_user)]
    for module in (watchlists, alerts, instruments, history, system):
        api.include_router(module.router, dependencies=protected)
    if settings.run_mode == "cron":
        api.include_router(cron.router)  # guarded by X-Cron-Secret, not the login cookie
    app.include_router(api)
    app.include_router(ws.router)

    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        return {"ok": True}

    dist = Path(settings.frontend_dist) if settings.frontend_dist else None
    if dist and (dist / "index.html").is_file():
        _mount_frontend(app, dist)

    return app


app = create_app()
