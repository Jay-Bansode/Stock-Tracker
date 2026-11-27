from decimal import Decimal as D

import pytest

from app.bot.commands import ADD_USAGE, Add, Alerts, Help, Invalid, Price, Start, parse


@pytest.mark.parametrize("text,expected", [
    ("/add RELIANCE >= 1500", Add("RELIANCE", "ABOVE", D("1500.00"), None)),
    ("/add reliance<=1,480.5", Add("RELIANCE", "BELOW", D("1480.50"), None)),
    ("/add TCS below ₹3,800 in Long-Term", Add("TCS", "BELOW", D("3800.00"), "Long-Term")),
    ("/add M&M above 2500 in my  list ", Add("M&M", "ABOVE", D("2500.00"), "my  list")),
    ("/add@TrackerBot INFY ≥ 1600", Add("INFY", "ABOVE", D("1600.00"), None)),
])
def test_add(text, expected):
    assert parse(text) == expected


@pytest.mark.parametrize("text", ["/add", "/add RELIANCE", "/add RELIANCE 1500", "/add RELIANCE >= abc"])
def test_add_usage(text):
    assert parse(text) == Invalid(ADD_USAGE)


def test_other_commands():
    assert parse("/price reliance") == Price("RELIANCE")
    assert isinstance(parse("/price"), Invalid)
    assert parse("/alerts") == Alerts()
    assert parse("/start abc123") == Start("abc123")
    assert parse("/start") == Start(None)
    assert parse("/help") == Help()
    assert parse("hello there") == Help()  # plain text gets the help list
    assert "I don't know /foo" in parse("/foo").message
    assert parse("/add X >= 0") == Invalid("The price must be more than 0.")
