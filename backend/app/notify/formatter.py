"""Single source of truth for alert message content across Telegram and WhatsApp."""

import html
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.config import IST
from app.db.models import AlertEvent, Condition

STATUS_HIT = "Target Hit"


def format_inr(value: Decimal) -> str:
    """₹ with Indian digit grouping; paise shown only when non-zero (₹1,500 / ₹1,50,000.50)."""
    q = Decimal(value).quantize(Decimal("0.01"))
    sign = "-" if q < 0 else ""
    int_part, dec = f"{abs(q):.2f}".split(".")
    if len(int_part) > 3:
        head, tail = int_part[:-3], int_part[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        int_part = ",".join([*groups, tail])
    return f"{sign}₹{int_part}" + ("" if dec == "00" else f".{dec}")


def format_ist(dt: datetime) -> str:
    return dt.astimezone(IST).strftime("%d %b %Y, %H:%M:%S IST")


@dataclass(frozen=True)
class AlertMessage:
    watchlist: str
    company: str
    symbol: str
    exchange: str
    condition: str
    target: Decimal
    current: Decimal
    at: datetime
    status: str = STATUS_HIT

    @classmethod
    def from_event(cls, e: AlertEvent) -> "AlertMessage":
        return cls(
            watchlist=e.watchlist_name,
            company=e.company_name,
            symbol=e.trading_symbol,
            exchange=e.instrument_key.split("_", 1)[0],
            condition=e.condition,
            target=e.target_price,
            current=e.trigger_price,
            at=e.exchange_ts or e.triggered_at,
        )

    @property
    def stock(self) -> str:
        return f"{self.company} ({self.exchange}: {self.symbol})"

    @property
    def target_label(self) -> str:
        direction = "Above" if self.condition == Condition.ABOVE else "Below"
        return f"{format_inr(self.target)} ({direction})"

    def fields(self) -> list[tuple[str, str]]:
        return [
            ("Watchlist", self.watchlist),
            ("Stock", self.stock),
            ("Target Price", self.target_label),
            ("Current Price", format_inr(self.current)),
            ("Status", self.status),
            ("Time", format_ist(self.at)),
        ]

    def text(self) -> str:
        lines = ["🔔 Stock Price Alert Triggered", ""]
        lines += [f"• {k}: {v}" for k, v in self.fields()]
        return "\n".join(lines)

    def telegram_html(self) -> str:
        lines = ["🔔 <b>Stock Price Alert Triggered</b>", ""]
        lines += [f"• <b>{k}:</b> {html.escape(v)}" for k, v in self.fields()]
        return "\n".join(lines)

    def whatsapp_params(self) -> list[str]:
        """Body parameters {{1}}..{{6}} of the `stock_price_alert` template, in order."""
        return [v for _, v in self.fields()]


def sample_message() -> AlertMessage:
    return AlertMessage(
        watchlist="Long-Term Stocks",
        company="Reliance Industries",
        symbol="RELIANCE",
        exchange="NSE",
        condition=Condition.ABOVE,
        target=Decimal("1500"),
        current=Decimal("1502"),
        at=datetime.now(IST),
        status="Test notification",
    )
