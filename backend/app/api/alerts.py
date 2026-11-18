from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import contains_eager

from app.api.deps import CurrentUser, SessionDep, StoreDep
from app.api.schemas import (
    AlertIn,
    AlertOut,
    AlertPatch,
    AlertSaved,
    AlertWithContext,
    InstrumentOut,
)
from app.db.models import Alert, AlertStatus, Watchlist, WatchlistItem
from app.db.session import CHANNEL_ALERTS_CHANGED, notify
from app.engine.evaluator import condition_met

router = APIRouter(tags=["alerts"])


async def _saved(alert: Alert, instrument_key: str, store) -> AlertSaved:
    out = AlertSaved.model_validate(alert)
    price = await store.get_ltp(instrument_key)
    out.current_price = price
    out.already_met = (
        price is not None
        and alert.status == AlertStatus.ACTIVE
        and condition_met(alert.condition, alert.target_price, price)
    )
    return out


async def _get_alert(session, alert_id: int, user) -> tuple[Alert, str]:
    row = (
        await session.execute(
            select(Alert, WatchlistItem.instrument_key)
            .join(WatchlistItem, Alert.watchlist_item_id == WatchlistItem.id)
            .join(Watchlist, WatchlistItem.watchlist_id == Watchlist.id)
            .where(Alert.id == alert_id, Watchlist.user_id == user.id)
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found")
    return row[0], row[1]


@router.get("/alerts", response_model=list[AlertWithContext])
async def list_alerts(
    session: SessionDep,
    user: CurrentUser,
    alert_status: Annotated[AlertStatus | None, Query(alias="status")] = None,
    watchlist_id: int | None = None,
):
    q = (
        select(Alert, Watchlist)
        .join(Alert.item)
        .join(Watchlist, WatchlistItem.watchlist_id == Watchlist.id)
        .options(contains_eager(Alert.item).joinedload(WatchlistItem.instrument))
        .where(Watchlist.user_id == user.id)
        .order_by(Watchlist.sort_order, Watchlist.id, Alert.id)
    )
    if alert_status:
        q = q.where(Alert.status == alert_status)
    if watchlist_id:
        q = q.where(Watchlist.id == watchlist_id)
    out = []
    for alert, wl in await session.execute(q):
        out.append(
            AlertWithContext(
                **AlertOut.model_validate(alert).model_dump(),
                watchlist_id=wl.id,
                watchlist_name=wl.name,
                instrument=InstrumentOut.model_validate(alert.item.instrument),
            )
        )
    return out


@router.post("/watchlist-items/{item_id}/alerts", response_model=AlertSaved, status_code=201)
async def create_alert(item_id: int, body: AlertIn, session: SessionDep, store: StoreDep,
                       user: CurrentUser):
    item = await session.scalar(
        select(WatchlistItem)
        .join(Watchlist, WatchlistItem.watchlist_id == Watchlist.id)
        .where(WatchlistItem.id == item_id, Watchlist.user_id == user.id)
    )
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Watchlist item not found")
    alert = Alert(watchlist_item_id=item_id, status=AlertStatus.ACTIVE, **body.model_dump())
    session.add(alert)
    await notify(session, CHANNEL_ALERTS_CHANGED)
    await session.commit()
    await session.refresh(alert)
    return await _saved(alert, item.instrument_key, store)


@router.patch("/alerts/{alert_id}", response_model=AlertSaved)
async def update_alert(alert_id: int, body: AlertPatch, session: SessionDep, store: StoreDep,
                       user: CurrentUser):
    alert, key = await _get_alert(session, alert_id, user)
    changes = body.model_dump(exclude_unset=True)
    redefined = any(
        k in changes and changes[k] != getattr(alert, k) for k in ("condition", "target_price")
    )
    for field, value in changes.items():
        setattr(alert, field, value)
    if redefined and alert.status != AlertStatus.DISABLED:
        alert.status = AlertStatus.ACTIVE  # a new condition is a new alert: arm it again
    await notify(session, CHANNEL_ALERTS_CHANGED)
    await session.commit()
    await session.refresh(alert)
    return await _saved(alert, key, store)


async def _set_status(alert_id: int, new_status: AlertStatus, session, store,
                      user) -> AlertSaved:
    alert, key = await _get_alert(session, alert_id, user)
    alert.status = new_status
    await notify(session, CHANNEL_ALERTS_CHANGED)
    await session.commit()
    await session.refresh(alert)
    return await _saved(alert, key, store)


@router.post("/alerts/{alert_id}/rearm", response_model=AlertSaved)
async def rearm_alert(alert_id: int, session: SessionDep, store: StoreDep, user: CurrentUser):
    return await _set_status(alert_id, AlertStatus.ACTIVE, session, store, user)


@router.post("/alerts/{alert_id}/disable", response_model=AlertSaved)
async def disable_alert(alert_id: int, session: SessionDep, store: StoreDep, user: CurrentUser):
    return await _set_status(alert_id, AlertStatus.DISABLED, session, store, user)


@router.delete("/alerts/{alert_id}", status_code=204)
async def delete_alert(alert_id: int, session: SessionDep, user: CurrentUser):
    alert, _ = await _get_alert(session, alert_id, user)
    await session.delete(alert)
    await notify(session, CHANNEL_ALERTS_CHANGED)
    await session.commit()
