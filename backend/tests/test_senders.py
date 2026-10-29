import httpx
import pytest
import respx

from app.notify.base import SendError
from app.notify.formatter import sample_message
from app.notify.telegram import TelegramSender
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
