from collections import defaultdict

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Alert, AlertStatus, TriggerMode, WatchlistItem
from app.engine.evaluator import AlertRule


class AlertIndex:
    """In-memory view of the alerts the engine must watch, keyed by instrument.

    Holds ACTIVE alerts (may trigger) and TRIGGERED REPEAT alerts (may re-arm). The database stays
    the source of truth; the index is rebuilt on change notifications and on a timer.
    """

    def __init__(self) -> None:
        self.by_key: dict[str, list[AlertRule]] = {}
        self.watch_keys: set[str] = set()

    async def reload(self, sm: async_sessionmaker[AsyncSession]) -> None:
        async with sm() as session:
            rows = await session.execute(
                select(Alert, WatchlistItem.instrument_key)
                .join(WatchlistItem, Alert.watchlist_item_id == WatchlistItem.id)
                .where(
                    or_(
                        Alert.status == AlertStatus.ACTIVE,
                        and_(
                            Alert.status == AlertStatus.TRIGGERED,
                            Alert.trigger_mode == TriggerMode.REPEAT,
                        ),
                    )
                )
            )
            by_key: dict[str, list[AlertRule]] = defaultdict(list)
            for alert, key in rows:
                by_key[key].append(
                    AlertRule(
                        id=alert.id,
                        instrument_key=key,
                        condition=alert.condition,
                        target=alert.target_price,
                        trigger_mode=alert.trigger_mode,
                        rearm_pct=alert.rearm_pct,
                        cooldown_sec=alert.cooldown_sec,
                        status=alert.status,
                        last_triggered_at=alert.last_triggered_at,
                        armed_since=alert.updated_at,
                    )
                )
            keys = set((await session.scalars(select(WatchlistItem.instrument_key).distinct())).all())
        self.by_key = dict(by_key)
        self.watch_keys = keys

    def rules_for(self, key: str) -> list[AlertRule]:
        return self.by_key.get(key, [])

    def remove(self, rule: AlertRule) -> None:
        rules = self.by_key.get(rule.instrument_key)
        if rules and rule in rules:
            rules.remove(rule)

    @property
    def alert_count(self) -> int:
        return sum(len(r) for r in self.by_key.values())

    def subscription_keys(self, cap: int) -> set[str]:
        """Every watchlist instrument (for live dashboard prices), alert-bearing ones first if capped."""
        if len(self.watch_keys) <= cap:
            return set(self.watch_keys)
        with_alerts = [k for k in sorted(self.watch_keys) if self.by_key.get(k)]
        rest = [k for k in sorted(self.watch_keys) if not self.by_key.get(k)]
        return set((with_alerts + rest)[:cap])
