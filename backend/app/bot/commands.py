"""Parse Telegram messages into commands. Pure functions: no I/O."""

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.db.models import Condition


@dataclass(frozen=True)
class Start:
    code: str | None  # the one-time link code from Settings → Connect Telegram


@dataclass(frozen=True)
class Help:
    pass


@dataclass(frozen=True)
class Price:
    symbol: str


@dataclass(frozen=True)
class Alerts:
    pass


@dataclass(frozen=True)
class Add:
    symbol: str
    condition: Condition
    target: Decimal
    watchlist: str | None


@dataclass(frozen=True)
class Invalid:
    message: str  # what to tell the user


Command = Start | Help | Price | Alerts | Add | Invalid

ADD_USAGE = (
    "Usage: /add SYMBOL >= PRICE [in WATCHLIST]\n"
    "e.g. /add RELIANCE >= 1500  or  /add TCS below 3,800 in Long-Term"
)

_CONDITIONS = {
    ">=": Condition.ABOVE, ">": Condition.ABOVE, "≥": Condition.ABOVE, "above": Condition.ABOVE,
    "<=": Condition.BELOW, "<": Condition.BELOW, "≤": Condition.BELOW, "below": Condition.BELOW,
}
_ADD = re.compile(
    r"^(?P<symbol>[A-Za-z0-9&_.|-]+?)\s*(?P<op>>=|<=|≥|≤|>|<|\babove\b|\bbelow\b)\s*"
    r"₹?\s*(?P<price>[\d,]+(?:\.\d+)?)(?:\s+in\s+(?P<watchlist>.+))?$",
    re.IGNORECASE,
)


def parse(text: str) -> Command:
    text = (text or "").strip()
    if not text.startswith("/"):
        return Help()
    head, _, rest = text.partition(" ")
    name = head[1:].split("@", 1)[0].lower()  # "/price@MyTrackerBot" in group chats
    rest = rest.strip()

    if name == "start":
        return Start(code=rest or None)
    if name == "help":
        return Help()
    if name == "alerts":
        return Alerts()
    if name == "price":
        if not rest:
            return Invalid("Usage: /price SYMBOL   e.g. /price RELIANCE")
        return Price(symbol=rest.split()[0].upper())
    if name == "add":
        return _parse_add(rest)
    return Invalid(f"I don't know /{name}. Send /help to see what I can do.")


def _parse_add(rest: str) -> Command:
    m = _ADD.match(rest)
    if not m:
        return Invalid(ADD_USAGE)
    try:
        target = Decimal(m["price"].replace(",", ""))
    except InvalidOperation:
        return Invalid(ADD_USAGE)
    if target <= 0 or target >= Decimal("1e10"):
        return Invalid("The price must be more than 0.")
    return Add(
        symbol=m["symbol"].upper(),
        condition=_CONDITIONS[m["op"].lower()],
        target=target.quantize(Decimal("0.01")),
        watchlist=(m["watchlist"] or "").strip() or None,
    )
