import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

from sqlalchemy import select, update

from datetime import time

from app.config import IST
from app.db.models import Alert, AlertEvent, Notification, Watchlist, WatchlistItem
from app.engine.index import AlertIndex
from app.engine.processor import AlertProcessor
from app.marketdata.base import Tick
from app.services.alerts import trigger_alert
from tests.conftest import HDFCBANK, RELIANCE, make_user

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


async def _alert_for(sm, user, key=RELIANCE, target="1500"):
    async with sm() as s:
        wl = Watchlist(name=f"{user.username}'s list", user_id=user.id)
        item = WatchlistItem(watchlist=wl, instrument_key=key)
        alert = Alert(item=item, condition="ABOVE", target_price=D(target), status="ACTIVE")
        s.add_all([wl, item, alert])
        await s.commit()
        return alert.id


async def _notes(sm, event_id):
    async with sm() as s:
        rows = await s.scalars(select(Notification).where(Notification.alert_event_id == event_id))
        return sorted((n.channel, n.recipient) for n in rows)


async def test_alerts_go_to_the_owners_own_chat(sm, example, owner):
    linked = await make_user(sm, "linked", telegram_chat_id="555")
    unlinked = await make_user(sm, "unlinked")

    admin_event = await trigger_alert(sm, example["Long-Term Stocks"], D("1502"), None, CHANNELS)
    linked_event = await trigger_alert(sm, await _alert_for(sm, linked), D("1502"), None, CHANNELS)
    unlinked_event = await trigger_alert(sm, await _alert_for(sm, unlinked), D("1502"), None,
                                         CHANNELS)

    assert await _notes(sm, admin_event) == [("TELEGRAM", "123"), ("WHATSAPP", None)]
    assert await _notes(sm, linked_event) == [("TELEGRAM", "555")]  # WhatsApp is admin-only
    assert await _notes(sm, unlinked_event) == []  # still recorded in their history
    async with sm() as s:
        owners = dict((await s.execute(select(AlertEvent.id, AlertEvent.user_id))).all())
    assert owners == {admin_event: owner.id, linked_event: linked.id, unlinked_event: unlinked.id}


async def test_only_at_alert_is_a_daily_check(sm, example):
    alert_id = example["Banking Stocks"]  # HDFCBANK >= 1700
    async with sm() as s:
        await s.execute(update(Alert).where(Alert.id == alert_id).values(
            trigger_mode="REPEAT", check_from=time(15, 15), check_until=time(15, 15)))
        await s.commit()
    index, proc = await _processor(sm)
    day1 = datetime(2026, 10, 29, tzinfo=IST)
    at = lambda d, h, m: d.replace(hour=h, minute=m)  # noqa: E731

    await proc.process(Tick(HDFCBANK, D("1710")), now=at(day1, 15, 10))  # before the window
    await proc.process(Tick(HDFCBANK, D("1710")), now=at(day1, 15, 15))  # fires
    await proc.process(Tick(HDFCBANK, D("1712")), now=at(day1, 15, 15))  # same minute: no repeat
    await proc.process(Tick(HDFCBANK, D("1715")), now=at(day1, 15, 20))  # after the window
    assert [e.trigger_price for e in await _events(sm)] == [D("1710.00")]

    day2 = day1 + timedelta(days=1)
    await proc.process(Tick(HDFCBANK, D("1708")), now=at(day2, 9, 15))  # re-arms, too early to fire
    assert len(await _events(sm)) == 1
    await proc.process(Tick(HDFCBANK, D("1706")), now=at(day2, 15, 15))  # fires again
    assert [e.trigger_price for e in await _events(sm)] == [D("1710.00"), D("1706.00")]
