import csv
import io
from datetime import date, datetime, time, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, update
from sqlalchemy.orm import selectinload

from app.api.deps import SessionDep
from app.api.schemas import EventOut, EventPage
from app.config import IST
from app.db.models import AlertEvent, Notification, NotificationStatus
from app.db.session import CHANNEL_OUTBOX, notify
from app.notify.formatter import format_ist

router = APIRouter(tags=["history"])


def _filtered(watchlist_id, symbol, date_from, date_to):
    q = select(AlertEvent)
    if watchlist_id:
        q = q.where(AlertEvent.watchlist_id == watchlist_id)
    if symbol:
        q = q.where(AlertEvent.trading_symbol.ilike(f"{symbol.strip()}%"))
    if date_from:
        q = q.where(AlertEvent.triggered_at >= datetime.combine(date_from, time.min, IST))
    if date_to:
        q = q.where(
            AlertEvent.triggered_at < datetime.combine(date_to + timedelta(days=1), time.min, IST)
        )
    return q


@router.get("/history", response_model=EventPage)
async def history(
    session: SessionDep,
    watchlist_id: int | None = None,
    symbol: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
):
    q = _filtered(watchlist_id, symbol, date_from, date_to)
    total = await session.scalar(select(func.count()).select_from(q.subquery()))
    rows = await session.scalars(
        q.options(selectinload(AlertEvent.notifications))
        .order_by(AlertEvent.triggered_at.desc(), AlertEvent.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return EventPage(
        items=[EventOut.model_validate(r) for r in rows],
        total=total or 0,
        page=page,
        page_size=page_size,
    )


@router.get("/history/export.csv")
async def export_history(
    session: SessionDep,
    watchlist_id: int | None = None,
    symbol: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
):
    rows = await session.scalars(
        _filtered(watchlist_id, symbol, date_from, date_to)
        .options(selectinload(AlertEvent.notifications))
        .order_by(AlertEvent.triggered_at.desc())
    )
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Triggered At (IST)", "Watchlist", "Symbol", "Company", "Condition",
                "Target Price", "Trigger Price", "Telegram", "WhatsApp"])
    for e in rows:
        by_channel = {n.channel: n.status for n in e.notifications}
        w.writerow([format_ist(e.triggered_at), e.watchlist_name, e.trading_symbol, e.company_name,
                    e.condition, e.target_price, e.trigger_price,
                    by_channel.get("TELEGRAM", "-"), by_channel.get("WHATSAPP", "-")])
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="alert-history.csv"'},
    )


@router.post("/notifications/{notification_id}/retry", status_code=202)
async def retry_notification(notification_id: int, session: SessionDep):
    n = await session.get(Notification, notification_id)
    if n is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")
    if n.status == NotificationStatus.SENT:
        raise HTTPException(status.HTTP_409_CONFLICT, "Already delivered")
    await session.execute(
        update(Notification)
        .where(Notification.id == notification_id)
        .values(status=NotificationStatus.PENDING, attempts=0, next_attempt_at=func.now(),
                updated_at=func.now())
    )
    await notify(session, CHANNEL_OUTBOX)
    await session.commit()
    return {"status": "queued"}
