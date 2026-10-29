import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

from sqlalchemy import select, update

from app.db.models import Alert, AlertEvent, Notification
from app.engine.index import AlertIndex
from app.engine.processor import AlertProcessor
from app.marketdata.base import Tick
from app.services.alerts import trigger_alert
from tests.conftest import HDFCBANK, RELIANCE

CHANNELS = ["TELEGRAM", "WHATSAPP"]


async def _processor(sm):
    index = AlertIndex()
    await index.reload(sm)
    return index, AlertProcessor(sm, index, CHANNELS)


async def _events(sm):
    async with sm() as s:
        return (await s.scalars(select(AlertEvent).order_by(AlertEvent.id))).all()


async def test_example_scenario_fires_each_watchlist_independently(sm, example):
    index, proc = await _processor(sm)
    assert index.watch_keys == {RELIANCE, HDFCBANK}

    await proc.process(Tick(RELIANCE, D("1490")))  # only Intraday (1480) is met
    await proc.process(Tick(RELIANCE, D("1502")))  # now Long-Term (1500) too
    await proc.process(Tick(HDFCBANK, D("1650")))  # Banking 1700 not hit

    events = await _events(sm)
    assert [(e.watchlist_name, e.target_price, e.trigger_price) for e in events] == [
        ("Intraday Stocks", D("1480.00"), D("1490.00")),
        ("Long-Term Stocks", D("1500.00"), D("1502.00")),
    ]
    assert all(e.company_name == "Reliance Industries" for e in events)

    async with sm() as s:
        notes = (await s.scalars(select(Notification).order_by(Notification.id))).all()
        statuses = dict((await s.execute(select(Alert.id, Alert.status))).all())
    # one outbox row per (event, channel)
    assert sorted((n.alert_event_id, n.channel) for n in notes) == [
        (events[0].id, "TELEGRAM"), (events[0].id, "WHATSAPP"),
        (events[1].id, "TELEGRAM"), (events[1].id, "WHATSAPP"),
    ]
    assert statuses[example["Long-Term Stocks"]] == "TRIGGERED"
    assert statuses[example["Intraday Stocks"]] == "TRIGGERED"
    assert statuses[example["Banking Stocks"]] == "ACTIVE"


async def test_repeated_ticks_do_not_duplicate(sm, example):
    _, proc = await _processor(sm)
    for price in ("1502", "1503", "1505", "1501"):
        await proc.process(Tick(RELIANCE, D(price)))
    assert len(await _events(sm)) == 2  # Long-Term + Intraday, once each


async def test_concurrent_triggers_produce_exactly_one_event(sm, example):
    alert_id = example["Long-Term Stocks"]
    results = await asyncio.gather(
        *[trigger_alert(sm, alert_id, D("1502"), None, CHANNELS) for _ in range(8)]
    )
    assert len([r for r in results if r is not None]) == 1
    assert len(await _events(sm)) == 1


async def test_restarted_engine_does_not_refire_triggered_once_alert(sm, example):
    _, proc = await _processor(sm)
    await proc.process(Tick(RELIANCE, D("1502")))
    _, fresh = await _processor(sm)  # simulates an engine restart reading DB state
    await fresh.process(Tick(RELIANCE, D("1510")))
    assert len(await _events(sm)) == 2


async def test_manual_rearm_fires_again_only_for_that_watchlist(sm, example):
    _, proc = await _processor(sm)
    await proc.process(Tick(RELIANCE, D("1502")))
    async with sm() as s:
        await s.execute(update(Alert).where(Alert.id == example["Long-Term Stocks"])
                        .values(status="ACTIVE"))
        await s.commit()
    _, proc = await _processor(sm)
    await proc.process(Tick(RELIANCE, D("1490")))
    await proc.process(Tick(RELIANCE, D("1502")))
    names = [e.watchlist_name for e in await _events(sm)]
    assert names == ["Long-Term Stocks", "Intraday Stocks", "Long-Term Stocks"]


async def test_repeat_alert_rearms_after_band_and_cooldown(sm, example):
    alert_id = example["Banking Stocks"]
    async with sm() as s:
        await s.execute(update(Alert).where(Alert.id == alert_id)
                        .values(trigger_mode="REPEAT", rearm_pct=D("1"), cooldown_sec=600))
        await s.commit()
    index, proc = await _processor(sm)
    t0 = datetime.now(UTC)
    await proc.process(Tick(HDFCBANK, D("1701")), now=t0)
    await proc.process(Tick(HDFCBANK, D("1600")), now=t0 + timedelta(minutes=5))  # in cooldown
    await proc.process(Tick(HDFCBANK, D("1705")), now=t0 + timedelta(minutes=6))
    assert len(await _events(sm)) == 1

    await proc.process(Tick(HDFCBANK, D("1680")), now=t0 + timedelta(minutes=11))  # re-arms
    await proc.process(Tick(HDFCBANK, D("1700")), now=t0 + timedelta(minutes=12))  # fires again
    assert [e.trigger_price for e in await _events(sm)] == [D("1701.00"), D("1700.00")]


async def test_disabled_alert_in_db_is_not_fired_from_stale_index(sm, example):
    index, proc = await _processor(sm)
    async with sm() as s:  # user disables after the engine loaded its index
        await s.execute(update(Alert).where(Alert.id == example["Long-Term Stocks"])
                        .values(status="DISABLED"))
        await s.commit()
    await proc.process(Tick(RELIANCE, D("1502")))
    assert [e.watchlist_name for e in await _events(sm)] == ["Intraday Stocks"]
