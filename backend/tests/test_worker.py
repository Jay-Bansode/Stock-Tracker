from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

from sqlalchemy import select, update

from app.db.models import Notification
from app.notify.base import SendError
from app.notify.worker import ChannelWorker
from app.services.alerts import enqueue_system_message, trigger_alert


class FakeSender:
    def __init__(self, channel, failures=()):
        self.channel = channel
        self.failures = list(failures)
        self.sent = []

    async def send_alert(self, msg):
        if self.failures:
            raise self.failures.pop(0)
        self.sent.append(msg)
        return f"{self.channel}-{len(self.sent)}"

    async def send_text(self, text):
        self.sent.append(text)
        return "txt"


async def _rows(sm):
    async with sm() as s:
        return {n.channel: n for n in (await s.scalars(select(Notification))).all()}


async def _make_due(sm):
    async with sm() as s:
        await s.execute(update(Notification).values(
            next_attempt_at=datetime.now(UTC) - timedelta(seconds=1)))
        await s.commit()


async def test_delivers_alert_with_watchlist_context(sm, example):
    await trigger_alert(sm, example["Long-Term Stocks"], D("1502"), None, ["TELEGRAM"])
    sender = FakeSender("TELEGRAM")
    worker = ChannelWorker(sm, sender, max_attempts=6, min_interval=0)
    assert await worker.process_batch() == 1
    [msg] = sender.sent
    assert (msg.watchlist, msg.symbol, msg.target, msg.current) == (
        "Long-Term Stocks", "RELIANCE", D("1500.00"), D("1502.00"))
    row = (await _rows(sm))["TELEGRAM"]
    assert row.status == "SENT" and row.provider_message_id == "TELEGRAM-1"
    assert await worker.process_batch() == 0  # nothing re-sent


async def test_retry_then_success_and_channel_independence(sm, example):
    await trigger_alert(sm, example["Long-Term Stocks"], D("1502"), None, ["TELEGRAM", "WHATSAPP"])
    telegram = FakeSender("TELEGRAM")
    whatsapp = FakeSender("WHATSAPP", failures=[SendError("throttled", retryable=True)])
    tg_worker = ChannelWorker(sm, telegram, max_attempts=6, min_interval=0)
    wa_worker = ChannelWorker(sm, whatsapp, max_attempts=6, min_interval=0)

    await wa_worker.process_batch()
    await tg_worker.process_batch()
    rows = await _rows(sm)
    assert rows["TELEGRAM"].status == "SENT"  # unaffected by the WhatsApp failure
    assert rows["WHATSAPP"].status == "PENDING" and rows["WHATSAPP"].attempts == 1
    assert rows["WHATSAPP"].next_attempt_at > datetime.now(UTC)
    assert await wa_worker.process_batch() == 0  # backoff not elapsed

    await _make_due(sm)
    await wa_worker.process_batch()
    rows = await _rows(sm)
    assert rows["WHATSAPP"].status == "SENT" and rows["WHATSAPP"].attempts == 2
    assert len(whatsapp.sent) == 1 and len(telegram.sent) == 1


async def test_permanent_error_and_max_attempts_mark_failed(sm, example):
    await trigger_alert(sm, example["Long-Term Stocks"], D("1502"), None, ["TELEGRAM", "WHATSAPP"])
    tg = ChannelWorker(sm, FakeSender("TELEGRAM", [SendError("chat not found", retryable=False)]),
                       max_attempts=6, min_interval=0)
    wa = ChannelWorker(sm, FakeSender("WHATSAPP", [SendError("x", retryable=True)] * 2),
                       max_attempts=2, min_interval=0)
    await tg.process_batch()
    await wa.process_batch()
    await _make_due(sm)
    await wa.process_batch()
    rows = await _rows(sm)
    assert rows["TELEGRAM"].status == "FAILED" and "chat not found" in rows["TELEGRAM"].last_error
    assert rows["WHATSAPP"].status == "FAILED" and rows["WHATSAPP"].attempts == 2


async def test_stale_sending_rows_are_recovered(sm, example):
    await trigger_alert(sm, example["Long-Term Stocks"], D("1502"), None, ["TELEGRAM"])
    async with sm() as s:
        await s.execute(update(Notification).values(
            status="SENDING", updated_at=datetime.now(UTC) - timedelta(minutes=10)))
        await s.commit()
    worker = ChannelWorker(sm, FakeSender("TELEGRAM"), max_attempts=6, min_interval=0)
    assert await worker.recover_stale() == 1
    assert await worker.process_batch() == 1


async def test_system_messages_go_to_telegram_only(sm):
    await enqueue_system_message(sm, "feed down", ["TELEGRAM", "WHATSAPP"])
    rows = await _rows(sm)
    assert list(rows) == ["TELEGRAM"] and rows["TELEGRAM"].kind == "SYSTEM"
    sender = FakeSender("TELEGRAM")
    await ChannelWorker(sm, sender, max_attempts=6, min_interval=0).process_batch()
    assert sender.sent == ["feed down"]
