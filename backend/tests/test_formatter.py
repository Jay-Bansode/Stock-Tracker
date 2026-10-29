from datetime import UTC, datetime
from decimal import Decimal as D

import pytest

from app.db.models import AlertEvent
from app.notify.formatter import AlertMessage, format_inr, format_ist


@pytest.mark.parametrize(
    "value,expected",
    [
        ("1500", "₹1,500"),
        ("1502.00", "₹1,502"),
        ("1502.35", "₹1,502.35"),
        ("999", "₹999"),
        ("150000.5", "₹1,50,000.50"),
        ("12345678", "₹1,23,45,678"),
        ("0.05", "₹0.05"),
    ],
)
def test_indian_currency_format(value, expected):
    assert format_inr(D(value)) == expected


def test_ist_time():
    assert format_ist(datetime(2026, 10, 29, 5, 12, 15, tzinfo=UTC)) == "29 Oct 2026, 10:42:15 IST"


def _event(**kw):
    defaults = dict(
        watchlist_name="Long-Term Stocks", instrument_key="NSE_EQ|INE002A01018",
        trading_symbol="RELIANCE", company_name="Reliance Industries", condition="ABOVE",
        target_price=D("1500"), trigger_price=D("1502"),
        exchange_ts=datetime(2026, 10, 29, 5, 12, 15, tzinfo=UTC),
        triggered_at=datetime(2026, 10, 29, 5, 12, 16, tzinfo=UTC),
    )
    return AlertEvent(**{**defaults, **kw})


def test_message_matches_spec():
    msg = AlertMessage.from_event(_event())
    assert msg.text() == "\n".join([
        "🔔 Stock Price Alert Triggered",
        "",
        "• Watchlist: Long-Term Stocks",
        "• Stock: Reliance Industries (NSE: RELIANCE)",
        "• Target Price: ₹1,500 (Above)",
        "• Current Price: ₹1,502",
        "• Status: Target Hit",
        "• Time: 29 Oct 2026, 10:42:15 IST",
    ])


def test_telegram_html_escapes_user_text():
    msg = AlertMessage.from_event(_event(watchlist_name="<Swing> & co"))
    html = msg.telegram_html()
    assert "&lt;Swing&gt; &amp; co" in html
    assert html.startswith("🔔 <b>Stock Price Alert Triggered</b>")


def test_whatsapp_params_order_and_single_line():
    params = AlertMessage.from_event(_event(condition="BELOW")).whatsapp_params()
    assert params[:5] == ["Long-Term Stocks", "Reliance Industries (NSE: RELIANCE)",
                          "₹1,500 (Below)", "₹1,502", "Target Hit"]
    assert all("\n" not in p for p in params)  # template params may not contain newlines
