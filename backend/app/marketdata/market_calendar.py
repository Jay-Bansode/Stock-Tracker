import logging
from datetime import date, datetime

from app.config import IST, Settings
from app.marketdata.upstox.rest import UpstoxRest

log = logging.getLogger(__name__)


class MarketCalendar:
    """Decides whether the live feed should be connected: weekdays, inside the configured IST
    window, and not an NSE trading holiday (holidays fetched from Upstox once a day)."""

    def __init__(self, settings: Settings, rest: UpstoxRest | None = None):
        self._settings = settings
        self._rest = rest
        self._holidays: set[date] = set()
        self._loaded_on: date | None = None

    async def _refresh(self, today: date) -> None:
        if self._rest is None or self._loaded_on == today:
            return
        try:
            self._holidays = await self._rest.trading_holidays("NSE")
            self._loaded_on = today
        except Exception as exc:  # keep the last known list; weekday/time rules still apply
            log.warning("could not load market holidays: %s", exc)

    def in_window(self, now: datetime) -> bool:
        local = now.astimezone(IST)
        if local.weekday() >= 5 or local.date() in self._holidays:
            return False
        return self._settings.market_open <= local.time() <= self._settings.market_close

    async def is_open(self, now: datetime | None = None) -> bool:
        if not self._settings.enforce_market_hours:
            return True
        now = now or datetime.now(IST)
        await self._refresh(now.astimezone(IST).date())
        return self.in_window(now)
