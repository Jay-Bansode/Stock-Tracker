import httpx
import pytest
import respx

from app.notify.base import SendError
from app.notify.formatter import sample_message
import json
from dataclasses import replace

from app.notify.telegram import TelegramSender, alert_buttons
from app.notify.whatsapp import WhatsAppSender

TG_URL = "https://api.telegram.org/botTOKEN/sendMessage"
WA_URL = "https://graph.facebook.com/v21.0/PHONEID/messages"


@respx.mock
async def test_telegram_success_sends_html():
    route = respx.post(TG_URL).mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {"message_id": 42}})
    )
    assert await TelegramSender("TOKEN", "123").send_alert(sample_message()) == "42"
    sent = route.calls.last.request.read().decode()
    assert '"parse_mode":"HTML"' in sent.replace(" ", "")
    assert "Long-Term Stocks" in sent


@respx.mock
async def test_telegram_recipient_overrides_default_chat():
    route = respx.post(TG_URL).mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
    )
    await TelegramSender("TOKEN", "123").send_text("hi", to="777")
    assert '"chat_id":"777"' in route.calls.last.request.read().decode().replace(" ", "")
    with pytest.raises(SendError) as e:
        await TelegramSender("TOKEN").send_text("hi")  # no default and no recipient
    assert not e.value.retryable


@respx.mock
async def test_alert_message_has_rearm_and_disable_buttons():
    route = respx.post(TG_URL).mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {"message_id": 7}})
    )
    msg = replace(sample_message(), alert_id=42)
    await TelegramSender("TOKEN", "123", app_url="https://tracker.example.com").send_alert(msg)
    keyboard = json.loads(route.calls.last.request.read())["reply_markup"]["inline_keyboard"]
    assert [b["callback_data"] for b in keyboard[0]] == ["rearm:42", "disable:42"]
    assert keyboard[1][0]["url"] == "https://tracker.example.com/alerts"

    await TelegramSender("TOKEN", "123", app_url="http://localhost:8080").send_alert(msg)
    keyboard = json.loads(route.calls.last.request.read())["reply_markup"]["inline_keyboard"]
    assert len(keyboard) == 1  # Telegram rejects non-https link buttons

    await TelegramSender("TOKEN", "123").send_alert(sample_message())  # test message: no alert id
    assert "reply_markup" not in json.loads(route.calls.last.request.read())


def test_buttons_follow_the_alert_state():
    data = lambda status: [b["callback_data"] for b in alert_buttons(5, status)[0]]  # noqa: E731
    assert data("TRIGGERED") == ["rearm:5", "disable:5"]
    assert data("ACTIVE") == ["disable:5"]
    assert data("DISABLED") == ["rearm:5"]


@respx.mock
async def test_telegram_429_is_retryable_with_retry_after():
    respx.post(TG_URL).mock(return_value=httpx.Response(
        429, json={"ok": False, "description": "Too Many Requests", "parameters": {"retry_after": 7}}
    ))
    with pytest.raises(SendError) as e:
        await TelegramSender("TOKEN", "123").send_alert(sample_message())
    assert e.value.retryable and e.value.retry_after == 7


@respx.mock
async def test_telegram_bad_chat_is_permanent():
    respx.post(TG_URL).mock(return_value=httpx.Response(
        400, json={"ok": False, "description": "Bad Request: chat not found"}
    ))
    with pytest.raises(SendError) as e:
        await TelegramSender("TOKEN", "123").send_alert(sample_message())
    assert not e.value.retryable


def _wa():
    return WhatsAppSender("WATOKEN", "PHONEID", "+91 98765 43210", "stock_price_alert")


@respx.mock
async def test_whatsapp_sends_template_with_six_params():
    route = respx.post(WA_URL).mock(
        return_value=httpx.Response(200, json={"messages": [{"id": "wamid.1"}]})
    )
    assert await _wa().send_alert(sample_message()) == "wamid.1"
    req = route.calls.last.request
    assert req.headers["Authorization"] == "Bearer WATOKEN"
    body = httpx.Response(200, content=req.read()).json()
    assert body["to"] == "919876543210"
    assert body["template"]["name"] == "stock_price_alert"
    params = body["template"]["components"][0]["parameters"]
    assert [p["text"] for p in params][:4] == [
        "Long-Term Stocks", "Reliance Industries (NSE: RELIANCE)", "₹1,500 (Above)", "₹1,502"
    ]
    assert len(params) == 6


@respx.mock
@pytest.mark.parametrize("status,code,retryable,retry_after", [
    (400, 131056, True, 6),     # pair rate limit
    (400, 130429, True, None),  # throughput limit
    (500, 1, True, None),
    (401, 190, False, None),    # expired token
    (400, 132001, False, None),  # template not approved / missing
])
async def test_whatsapp_error_classification(status, code, retryable, retry_after):
    respx.post(WA_URL).mock(return_value=httpx.Response(
        status, json={"error": {"code": code, "message": "x"}}
    ))
    with pytest.raises(SendError) as e:
        await _wa().send_alert(sample_message())
    assert e.value.retryable is retryable
    assert e.value.retry_after == retry_after
