import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import AlertStatus, TriggerMode
from app.engine.evaluator import evaluate
from app.engine.index import AlertIndex
from app.marketdata.base import Tick
from app.services.alerts import rearm_repeat_alert, trigger_alert

log = logging.getLogger(__name__)


class AlertProcessor:
    """Evaluates each tick against the in-memory index; touches the DB only on a match."""

    def __init__(self, sm: async_sessionmaker[AsyncSession], index: AlertIndex,
                 channels: list[str]):
        self._sm = sm
        self._index = index
        self._channels = channels

    async def process(self, tick: Tick, now: datetime | None = None) -> list[int]:
        rules = self._index.rules_for(tick.instrument_key)
        if not rules:
            return []
        now = now or datetime.now(UTC)
        decision = evaluate(rules, tick.ltp, now, tick.candles)
        events: list[int] = []

        for rule in decision.triggers:
            price = decision.hit_prices[rule.id]
            try:
                event_id = await trigger_alert(self._sm, rule.id, price, tick.ts, self._channels)
            except Exception:
                # Rule stays ACTIVE in memory, so the next tick retries instead of losing the alert.
                log.exception("failed to record trigger for alert %s", rule.id)
                continue
            rule.status = AlertStatus.TRIGGERED
            rule.last_triggered_at = now
            if event_id is not None:
                events.append(event_id)
                log.info("alert %s fired: %s %s %s at %s (event %s)", rule.id,
                         tick.instrument_key, rule.condition, rule.target, price, event_id)
            # ONCE alerts leave the index; a lost race means the DB disagrees, so drop until reload.
            if rule.trigger_mode == TriggerMode.ONCE or event_id is None:
                self._index.remove(rule)

        for rule in decision.rearms:
            try:
                if await rearm_repeat_alert(self._sm, rule.id):
                    rule.status = AlertStatus.ACTIVE
                    rule.armed_since = now
                    log.info("alert %s re-armed at %s", rule.id, tick.ltp)
                else:
                    self._index.remove(rule)
            except Exception:
                log.exception("failed to re-arm alert %s", rule.id)
        return events
