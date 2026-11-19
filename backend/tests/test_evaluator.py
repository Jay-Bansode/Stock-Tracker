from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from app.engine.evaluator import AlertRule, condition_met, evaluate, rearm_ready

NOW = datetime(2026, 10, 29, 5, 0, tzinfo=UTC)


def rule(id=1, condition="ABOVE", target="1500", mode="ONCE", status="ACTIVE",
         rearm_pct="0.5", cooldown=900, last=None, key="NSE_EQ|X"):
    return AlertRule(id=id, instrument_key=key, condition=condition, target=D(target),
                     trigger_mode=mode, rearm_pct=D(rearm_pct), cooldown_sec=cooldown,
                     status=status, last_triggered_at=last)


@pytest.mark.parametrize(
    "condition,target,price,expected",
    [
        ("ABOVE", "1500", "1500.00", True),  # touching the target counts
        ("ABOVE", "1500", "1499.95", False),
        ("ABOVE", "1500", "1502", True),
        ("BELOW", "1500", "1500", True),
        ("BELOW", "1500", "1500.05", False),
        ("BELOW", "1500", "1480", True),
    ],
)
def test_condition_boundaries(condition, target, price, expected):
    assert condition_met(condition, D(target), D(price)) is expected


def test_same_stock_in_two_watchlists_is_evaluated_independently():
    long_term = rule(id=1, target="1500")
    intraday = rule(id=2, target="1480")
    assert evaluate([long_term, intraday], D("1490"), NOW).triggers == [intraday]
    assert evaluate([long_term, intraday], D("1502"), NOW).triggers == [long_term, intraday]


def test_triggered_and_disabled_alerts_do_not_fire():
    rules = [rule(id=1, status="TRIGGERED"), rule(id=2, status="DISABLED")]
    assert evaluate(rules, D("1600"), NOW).triggers == []


def test_once_alert_never_rearms():
    r = rule(mode="ONCE", status="TRIGGERED", last=NOW - timedelta(days=1))
    assert not rearm_ready(r, D("1000"), NOW)


def test_repeat_alert_rearms_only_outside_band_and_after_cooldown():
    r = rule(mode="REPEAT", status="TRIGGERED", rearm_pct="0.5", cooldown=900,
             last=NOW - timedelta(minutes=20))
    # band = 7.50 below 1500 -> must trade below 1492.50
    assert not rearm_ready(r, D("1495"), NOW)
    assert not rearm_ready(r, D("1492.50"), NOW)
    assert rearm_ready(r, D("1492.45"), NOW)

    recent = rule(mode="REPEAT", status="TRIGGERED", cooldown=900, last=NOW - timedelta(minutes=5))
    assert not rearm_ready(recent, D("1400"), NOW)


def test_repeat_below_alert_rearms_above_band():
    r = rule(condition="BELOW", target="1000", mode="REPEAT", status="TRIGGERED", rearm_pct="1",
             cooldown=0, last=NOW)
    assert not rearm_ready(r, D("1010"), NOW)
    assert rearm_ready(r, D("1010.05"), NOW)


def test_zero_band_still_requires_strict_retreat():
    r = rule(mode="REPEAT", status="TRIGGERED", rearm_pct="0", cooldown=0, last=NOW)
    assert not rearm_ready(r, D("1500"), NOW)
    assert rearm_ready(r, D("1499.99"), NOW)


# --- candle touch detection (cron mode polls once a minute) -------------------------------

from app.engine.evaluator import hit_price  # noqa: E402
from app.marketdata.base import Candle  # noqa: E402

ARMED = datetime(2026, 10, 29, 5, 0, tzinfo=UTC)


def candle(minutes_after_arm, high, low):
    return Candle(start=ARMED + timedelta(minutes=minutes_after_arm), high=D(high), low=D(low))


def test_touch_between_polls_fires_at_the_candle_extreme():
    above = rule(target="1500", last=None)
    above.armed_since = ARMED
    below = rule(id=2, condition="BELOW", target="1450")
    below.armed_since = ARMED
    c = [candle(1, "1501.5", "1449")]
    decision = evaluate([above, below], D("1495"), NOW, c)
    assert decision.triggers == [above, below]
    assert decision.hit_prices == {1: D("1501.5"), 2: D("1449")}


def test_last_price_wins_when_it_already_meets_the_target():
    r = rule(target="1500")
    r.armed_since = ARMED
    assert hit_price(r, D("1502"), [candle(1, "1510", "1490")]) == D("1502")


def test_candles_from_before_the_alert_was_armed_are_ignored():
    r = rule(target="1500")
    r.armed_since = ARMED
    assert hit_price(r, D("1490"), [candle(-1, "1505", "1480")]) is None
    assert hit_price(r, D("1490"), [candle(-1, "1505", "1480"), candle(0, "1503", "1488")]) == D("1503")


def test_streaming_ticks_without_candles_behave_as_before():
    r = rule(target="1500")
    assert evaluate([r], D("1499.95"), NOW).triggers == []


# --- daily check windows (IST) -------------------------------------------------------------
from datetime import time as _t  # noqa: E402

from app.config import IST  # noqa: E402
from app.engine.evaluator import in_window  # noqa: E402
from app.marketdata.base import Candle  # noqa: E402


def ist(h, m, s=0, day=29):
    return datetime(2026, 10, day, h, m, s, tzinfo=IST)


def timed(frm, until, **kw):
    r = rule(mode="REPEAT", **kw)
    r.check_from, r.check_until = _t(*frm), _t(*until)
    return r


def test_only_at_covers_that_whole_minute_and_nothing_else():
    r = timed((15, 15), (15, 15))
    assert not in_window(r, ist(15, 14, 59))
    assert in_window(r, ist(15, 15, 0)) and in_window(r, ist(15, 15, 59))
    assert not in_window(r, ist(15, 16, 0))
    assert in_window(r, ist(15, 15).astimezone(UTC))  # UTC input is converted to IST


def test_timed_alert_fires_only_inside_its_window():
    r = timed((15, 15), (15, 15))
    assert evaluate([r], D("1510"), ist(15, 14)).triggers == []
    assert evaluate([r], D("1510"), ist(15, 15, 30)).triggers == [r]
    assert evaluate([r], D("1510"), ist(15, 16)).triggers == []


def test_between_window_uses_both_ends():
    r = timed((14, 30), (15, 30))
    assert evaluate([r], D("1510"), ist(14, 29)).triggers == []
    assert evaluate([r], D("1510"), ist(14, 30)).triggers == [r]
    assert evaluate([r], D("1510"), ist(15, 30, 59)).triggers == [r]
    assert evaluate([r], D("1510"), ist(15, 31)).triggers == []


def test_late_check_still_sees_the_window_candle_but_not_earlier_spikes():
    r = timed((15, 15), (15, 15))
    spike_before = Candle(start=ist(15, 14), high=D("1520"), low=D("1490"))
    in_minute = Candle(start=ist(15, 15), high=D("1505"), low=D("1490"))
    # 15:16 check, price now below target: the 15:15 candle's high still counts...
    late = evaluate([r], D("1495"), ist(15, 16, 10), [spike_before, in_minute])
    assert late.triggers == [r] and late.hit_prices[r.id] == D("1505")
    # ...but a 15:14 spike alone can't fire a 15:15 alert
    assert evaluate([r], D("1495"), ist(15, 15, 5), [spike_before]).triggers == []


def test_timed_alert_rearms_next_day_regardless_of_band_and_cooldown():
    fired = ist(15, 15, 20)
    r = timed((15, 15), (15, 15), status="TRIGGERED", last=fired, cooldown=86400)
    # same day, even far past the band: stays fired
    assert not rearm_ready(r, D("1000"), ist(15, 40))
    # next day, price still above target: daily check re-arms anyway
    assert rearm_ready(r, D("1510"), ist(9, 0, day=30))
