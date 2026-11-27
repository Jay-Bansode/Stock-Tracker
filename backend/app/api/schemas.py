from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    PlainSerializer,
    field_validator,
    model_validator,
)

from app.config import IST
from app.db.models import AlertStatus, Condition, TriggerMode

# Decimals go over the wire as JSON numbers; they are only displayed client-side.
Money = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


Password = Annotated[str, Field(min_length=8, max_length=72)]  # bcrypt ignores bytes past 72


class LoginIn(BaseModel):
    username: str = Field(description="Username or email")
    password: str


class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")
    email: EmailStr
    password: Password


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: Password


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: Password


class ChangeEmailIn(BaseModel):
    email: EmailStr
    current_password: str


class Me(BaseModel):
    id: int
    username: str
    email: str
    is_admin: bool
    telegram_linked: bool

    @classmethod
    def of(cls, user) -> "Me":
        return cls(id=user.id, username=user.username, email=user.email,
                   is_admin=user.is_admin, telegram_linked=bool(user.telegram_chat_id))


class InstrumentOut(ORM):
    instrument_key: str
    trading_symbol: str
    name: str
    exchange: str
    segment: str
    instrument_type: str


def check_window(check_from: time | None, check_until: time | None) -> None:
    """A daily check window needs both ends (equal = "only at" that minute), in order."""
    if (check_from is None) != (check_until is None):
        raise ValueError("Set both check_from and check_until, or neither")
    if check_from is not None and check_from > check_until:
        raise ValueError("check_from must not be after check_until")


class _WindowFields(BaseModel):
    # IST wall-clock times, whole minutes.
    check_from: time | None = None
    check_until: time | None = None

    @field_validator("check_from", "check_until")
    @classmethod
    def _whole_minute(cls, value: time | None) -> time | None:
        return value.replace(second=0, microsecond=0, tzinfo=None) if value else value


class AlertIn(_WindowFields):
    condition: Condition
    target_price: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    trigger_mode: TriggerMode = TriggerMode.ONCE
    rearm_pct: Decimal = Field(default=Decimal("0.5"), ge=0, le=20, decimal_places=2)
    cooldown_sec: int = Field(default=900, ge=0, le=86400)
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _window(self) -> "AlertIn":
        check_window(self.check_from, self.check_until)
        if self.check_from is not None:
            self.trigger_mode = TriggerMode.REPEAT  # timed alerts are daily checks
        return self


class AlertPatch(_WindowFields):
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
    check_from: time | None
    check_until: time | None
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


class ItemPatch(BaseModel):
    bought_on: date | None = None  # null clears it

    @field_validator("bought_on")
    @classmethod
    def _sensible_date(cls, value: date | None) -> date | None:
        if value is not None:
            if value > datetime.now(IST).date():
                raise ValueError("The buying date can't be in the future")
            if value < date(1990, 1, 1):
                raise ValueError("The buying date looks too early; check the year")
        return value


class ItemOut(ORM):
    id: int
    watchlist_id: int
    instrument: InstrumentOut
    notes: str | None
    bought_on: date | None
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
