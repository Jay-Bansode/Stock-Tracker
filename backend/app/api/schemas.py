from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from app.db.models import AlertStatus, Condition, TriggerMode

# Decimals go over the wire as JSON numbers; they are only displayed client-side.
Money = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LoginIn(BaseModel):
    username: str
    password: str


class Me(BaseModel):
    username: str


class InstrumentOut(ORM):
    instrument_key: str
    trading_symbol: str
    name: str
    exchange: str
    segment: str
    instrument_type: str


class AlertIn(BaseModel):
    condition: Condition
    target_price: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    trigger_mode: TriggerMode = TriggerMode.ONCE
    rearm_pct: Decimal = Field(default=Decimal("0.5"), ge=0, le=20, decimal_places=2)
    cooldown_sec: int = Field(default=900, ge=0, le=86400)
    note: str | None = Field(default=None, max_length=500)


class AlertPatch(BaseModel):
    condition: Condition | None = None
    target_price: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    trigger_mode: TriggerMode | None = None
    rearm_pct: Decimal | None = Field(default=None, ge=0, le=20, decimal_places=2)
    cooldown_sec: int | None = Field(default=None, ge=0, le=86400)
    note: str | None = Field(default=None, max_length=500)


class AlertOut(ORM):
    id: int
    watchlist_item_id: int
    condition: Condition
    target_price: Money
    trigger_mode: TriggerMode
    rearm_pct: Money
    cooldown_sec: int
    status: AlertStatus
    last_triggered_at: datetime | None
    last_trigger_price: Money | None
    trigger_count: int
    note: str | None
    created_at: datetime


class AlertSaved(AlertOut):
    current_price: Money | None = None
    already_met: bool = False


class AlertWithContext(AlertOut):
    watchlist_id: int
    watchlist_name: str
    instrument: InstrumentOut


class WatchlistIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)


class WatchlistPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    sort_order: int | None = None


class WatchlistOut(ORM):
    id: int
    name: str
    description: str | None
    sort_order: int
    item_count: int = 0
    active_alerts: int = 0
    triggered_alerts: int = 0
    created_at: datetime


class ItemIn(BaseModel):
    instrument_key: str
    notes: str | None = Field(default=None, max_length=1000)


class ItemOut(ORM):
    id: int
    watchlist_id: int
    instrument: InstrumentOut
    notes: str | None
    added_at: datetime
    alerts: list[AlertOut]


class NotificationOut(ORM):
    id: int
    channel: str
    status: str
    attempts: int
    last_error: str | None
    sent_at: datetime | None
    next_attempt_at: datetime


class EventOut(ORM):
    id: int
    alert_id: int | None
    watchlist_id: int | None
    watchlist_name: str
    instrument_key: str
    trading_symbol: str
    company_name: str
    condition: Condition
    target_price: Money
    trigger_price: Money
    exchange_ts: datetime | None
    triggered_at: datetime
    notifications: list[NotificationOut]


class EventPage(BaseModel):
    items: list[EventOut]
    total: int
    page: int
    page_size: int


class TestNotificationIn(BaseModel):
    channel: str


class OrderIn(BaseModel):
    ids: list[int]
