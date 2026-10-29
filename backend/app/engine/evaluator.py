"""Pure alert-evaluation rules. No I/O, so every edge case is unit-testable."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from app.db.models import AlertStatus, Condition, TriggerMode
from app.marketdata.base import Candle


@dataclass(slots=True)
class AlertRule:
    id: int
    instrument_key: str
    condition: str
    target: Decimal
    trigger_mode: str
    rearm_pct: Decimal
    cooldown_sec: int
    status: str
    last_triggered_at: datetime | None = None
    # When the alert last became ACTIVE (create / re-arm / edit). Candles that started before
    # this can't fire it, so a just re-armed alert ignores the spike that fired it last time.
    armed_since: datetime | None = None


@dataclass(slots=True)
class Decision:
    triggers: list[AlertRule] = field(default_factory=list)
    rearms: list[AlertRule] = field(default_factory=list)
    hit_prices: dict[int, Decimal] = field(default_factory=dict)  # rule id -> price that met it


def condition_met(condition: str, target: Decimal, price: Decimal) -> bool:
    if condition == Condition.ABOVE:
        return price >= target
    if condition == Condition.BELOW:
        return price <= target
    raise ValueError(f"unknown condition {condition!r}")


def hit_price(rule: AlertRule, price: Decimal, candles: Iterable[Candle] = ()) -> Decimal | None:
    """The price that satisfied the rule: the last traded price if it does, otherwise the most
    extreme eligible candle high (ABOVE) / low (BELOW), else None."""
    if condition_met(rule.condition, rule.target, price):
        return price
    above = rule.condition == Condition.ABOVE
    best: Decimal | None = None
    for c in candles:
        if rule.armed_since is not None and c.start < rule.armed_since:
            continue
        extreme = c.high if above else c.low
        if condition_met(rule.condition, rule.target, extreme):
            best = extreme if best is None else (max(best, extreme) if above else min(best, extreme))
    return best


def rearm_ready(rule: AlertRule, price: Decimal, now: datetime) -> bool:
    """REPEAT alerts re-arm only after price retreats beyond the hysteresis band AND the cooldown
    has passed, so a price hovering at the target can't spam notifications."""
    if rule.trigger_mode != TriggerMode.REPEAT or rule.status != AlertStatus.TRIGGERED:
        return False
    if rule.last_triggered_at and now - rule.last_triggered_at < timedelta(seconds=rule.cooldown_sec):
        return False
    band = rule.target * rule.rearm_pct / Decimal(100)
    if rule.condition == Condition.ABOVE:
        return price < rule.target - band
    return price > rule.target + band


def evaluate(rules: list[AlertRule], price: Decimal, now: datetime,
             candles: Iterable[Candle] = ()) -> Decision:
    """Each rule is judged on its own: two watchlists holding the same stock never interact."""
    candles = tuple(candles)
    decision = Decision()
    for rule in rules:
        if rule.status == AlertStatus.ACTIVE:
            hit = hit_price(rule, price, candles)
            if hit is not None:
                decision.triggers.append(rule)
                decision.hit_prices[rule.id] = hit
                continue
        if rearm_ready(rule, price, now):
            decision.rearms.append(rule)
    return decision
