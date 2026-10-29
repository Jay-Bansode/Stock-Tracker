from datetime import date, datetime, time
from functools import lru_cache
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

IST = ZoneInfo("Asia/Kolkata")


class Settings(BaseSettings):
    # Repo-root .env when run from backend/, local .env otherwise; real env vars always win.
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"), extra="ignore", env_ignore_empty=True
    )

    # services = always-on Docker processes (live feed + Redis);
    # cron     = free-hosting mode: an external scheduler calls /api/cron/poll every minute.
    run_mode: Literal["services", "cron"] = "services"
    cron_secret: str = ""
    poll_budget_seconds: float = 25.0  # cron-job.org gives up after 30 s
    frontend_dist: str = ""  # built SPA served by the API (single-origin deploys)

    database_url: str = "postgresql+asyncpg://tracker:tracker@localhost:55432/tracker"
    redis_url: str = "redis://localhost:56379/0"

    # Dashboard auth (single user)
    secret_key: str = "change-me-please"
    admin_username: str = "admin"
    admin_password_hash: str = ""
    admin_password: str = ""  # plain-text fallback for local dev; prefer ADMIN_PASSWORD_HASH
    session_ttl_hours: int = 72
    cookie_secure: bool = False
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:8080"]

    # Market data
    market_data_provider: Literal["simulated", "upstox"] = "simulated"
    upstox_analytics_token: str = ""
    upstox_token_expires_on: date | None = None
    upstox_api_base: str = "https://api.upstox.com"
    upstox_instruments_url: str = (
        "https://assets.upstox.com/market-quote/instruments/exchange/{exchange}.json.gz"
    )
    instrument_exchanges: list[str] = ["NSE", "BSE"]
    instruments_sync_on_start: bool = True
    max_subscriptions: int = 2000
    market_open: time = time(9, 0)
    market_close: time = time(15, 40)
    enforce_market_hours: bool = True

    # Simulated provider
    simulated_random_walk: bool = True
    simulated_tick_seconds: float = 1.0
    simulated_volatility_pct: float = 0.05

    # Notifications
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    whatsapp_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_to: str = ""
    whatsapp_template: str = "stock_price_alert"
    whatsapp_template_lang: str = "en"
    whatsapp_graph_version: str = "v21.0"
    notify_max_attempts: int = 6
    # Overridable for proxies or a local mock during testing
    telegram_api_base: str = "https://api.telegram.org"
    whatsapp_api_base: str = "https://graph.facebook.com"

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_db_url(cls, value):
        return normalize_database_url(value) if isinstance(value, str) else value

    @field_validator("upstox_token_expires_on", mode="before")
    @classmethod
    def _parse_expiry(cls, value):
        """Accept 2027-09-29 as well as Indian-style 29/09/2027 or 29-09-2027."""
        if isinstance(value, str):
            value = value.strip()
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
                try:
                    return datetime.strptime(value, fmt).date()
                except ValueError:
                    continue
        return value

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def whatsapp_enabled(self) -> bool:
        return bool(self.whatsapp_token and self.whatsapp_phone_number_id and self.whatsapp_to)

    @property
    def enabled_channels(self) -> list[str]:
        channels = []
        if self.telegram_enabled:
            channels.append("TELEGRAM")
        if self.whatsapp_enabled:
            channels.append("WHATSAPP")
        return channels

    @property
    def asyncpg_dsn(self) -> str:
        """Plain asyncpg DSN (no SQLAlchemy driver suffix) for LISTEN/NOTIFY and advisory locks."""
        dsn = self.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
        parts = urlsplit(dsn)
        query = [
            ("sslmode", v) if k == "ssl" else (k, v)
            for k, v in parse_qsl(parts.query)
            if k != "prepared_statement_cache_size"
        ]
        return urlunsplit(parts._replace(query=urlencode(query)))


def normalize_database_url(url: str) -> str:
    """Accept the URLs hosting providers hand out (e.g. Supabase's
    `postgresql://…?sslmode=require`) and turn them into a SQLAlchemy asyncpg URL."""
    url = url.strip()
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            url = "postgresql+asyncpg://" + url[len(prefix):]
    parts = urlsplit(url)
    query = []
    for key, val in parse_qsl(parts.query):
        if key == "sslmode":  # libpq spelling -> asyncpg's
            key = "ssl"
        query.append((key, val))
    # Transaction-mode poolers (port 6543) can't keep prepared statements between queries.
    if parts.port == 6543 and not any(k == "prepared_statement_cache_size" for k, _ in query):
        query.append(("prepared_statement_cache_size", "0"))
    return urlunsplit(parts._replace(query=urlencode(query)))


@lru_cache
def get_settings() -> Settings:
    return Settings()
