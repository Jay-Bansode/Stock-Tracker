from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Condition(StrEnum):
    ABOVE = "ABOVE"
    BELOW = "BELOW"


class TriggerMode(StrEnum):
    ONCE = "ONCE"
    REPEAT = "REPEAT"


class AlertStatus(StrEnum):
    ACTIVE = "ACTIVE"
    TRIGGERED = "TRIGGERED"
    DISABLED = "DISABLED"


class Channel(StrEnum):
    TELEGRAM = "TELEGRAM"
    WHATSAPP = "WHATSAPP"


class NotificationKind(StrEnum):
    ALERT = "ALERT"
    SYSTEM = "SYSTEM"


class NotificationStatus(StrEnum):
    PENDING = "PENDING"
    SENDING = "SENDING"
    SENT = "SENT"
    FAILED = "FAILED"


class Base(DeclarativeBase):
    pass


def _ts(**kw) -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), **kw)


class Instrument(Base):
    __tablename__ = "instruments"

    instrument_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    trading_symbol: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255))
    exchange: Mapped[str] = mapped_column(String(16))
    segment: Mapped[str] = mapped_column(String(16))
    instrument_type: Mapped[str] = mapped_column(String(16))
    isin: Mapped[str | None] = mapped_column(String(16))
    updated_at: Mapped[datetime] = _ts(onupdate=func.now())

    __table_args__ = (Index("ix_instruments_symbol", "trading_symbol"),)


class Watchlist(Base):
    __tablename__ = "watchlists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts(onupdate=func.now())

    items: Mapped[list["WatchlistItem"]] = relationship(
        back_populates="watchlist", cascade="all, delete-orphan", passive_deletes=True
    )


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    watchlist_id: Mapped[int] = mapped_column(ForeignKey("watchlists.id", ondelete="CASCADE"))
    instrument_key: Mapped[str] = mapped_column(ForeignKey("instruments.instrument_key"))
    notes: Mapped[str | None] = mapped_column(Text)
    added_at: Mapped[datetime] = _ts()

    watchlist: Mapped[Watchlist] = relationship(back_populates="items")
    instrument: Mapped[Instrument] = relationship(lazy="joined")
    alerts: Mapped[list["Alert"]] = relationship(
        back_populates="item", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (UniqueConstraint("watchlist_id", "instrument_key"),)


class Alert(Base):
    """One price condition on one watchlist item.

    Alerts hang off watchlist items, not instruments, so the same stock in two watchlists always
    has separate, independently evaluated alerts.
    """

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    watchlist_item_id: Mapped[int] = mapped_column(
        ForeignKey("watchlist_items.id", ondelete="CASCADE"), index=True
    )
    condition: Mapped[str] = mapped_column(String(8))
    target_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    trigger_mode: Mapped[str] = mapped_column(String(8), default=TriggerMode.ONCE)
    rearm_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("0.5"), server_default="0.5"
    )
    cooldown_sec: Mapped[int] = mapped_column(Integer, default=900, server_default="900")
    status: Mapped[str] = mapped_column(String(12), default=AlertStatus.ACTIVE, index=True)
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_trigger_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    trigger_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts(onupdate=func.now())

    item: Mapped[WatchlistItem] = relationship(back_populates="alerts")


class AlertEvent(Base):
    """Append-only trigger history. Names are snapshotted so history survives renames/deletes."""

    __tablename__ = "alert_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    alert_id: Mapped[int | None] = mapped_column(
        ForeignKey("alerts.id", ondelete="SET NULL"), index=True
    )
    watchlist_id: Mapped[int | None] = mapped_column(Integer, index=True)
    watchlist_name: Mapped[str] = mapped_column(String(100))
    instrument_key: Mapped[str] = mapped_column(String(64))
    trading_symbol: Mapped[str] = mapped_column(String(64), index=True)
    company_name: Mapped[str] = mapped_column(String(255))
    condition: Mapped[str] = mapped_column(String(8))
    target_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    trigger_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    exchange_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    triggered_at: Mapped[datetime] = _ts(index=True)

    notifications: Mapped[list["Notification"]] = relationship(
        back_populates="event", order_by="Notification.channel"
    )


class Notification(Base):
    """Outbox row: one per (event, channel). The unique constraint is the last line of dedupe."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    alert_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("alert_events.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(8), default=NotificationKind.ALERT)
    channel: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(10), default=NotificationStatus.PENDING)
    body: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    next_attempt_at: Mapped[datetime] = _ts()
    last_error: Mapped[str | None] = mapped_column(Text)
    provider_message_id: Mapped[str | None] = mapped_column(String(128))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts(onupdate=func.now())

    event: Mapped[AlertEvent | None] = relationship(back_populates="notifications")

    __table_args__ = (
        UniqueConstraint("alert_event_id", "channel"),
        Index("ix_notifications_pending", "channel", "status", "next_attempt_at"),
    )


class Quote(Base):
    """Latest price per instrument. Used instead of Redis in cron (free-hosting) mode."""

    __tablename__ = "quotes"

    instrument_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    ltp: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    close: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = _ts(onupdate=func.now())


class SystemState(Base):
    """Small key/value store for state that must survive stateless requests (poll status,
    system-notice dedupe)."""

    __tablename__ = "system_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = _ts(onupdate=func.now())
