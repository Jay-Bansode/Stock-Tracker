from fastapi import APIRouter, HTTPException, status
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.api.deps import SessionDep
from app.api.schemas import ItemIn, ItemOut, OrderIn, WatchlistIn, WatchlistOut, WatchlistPatch
from app.db.models import Alert, AlertStatus, Instrument, Watchlist, WatchlistItem
from app.db.session import CHANNEL_ALERTS_CHANGED, notify

router = APIRouter(prefix="/watchlists", tags=["watchlists"])


async def _get_watchlist(session, watchlist_id: int) -> Watchlist:
    wl = await session.get(Watchlist, watchlist_id)
    if wl is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Watchlist not found")
    return wl


@router.get("", response_model=list[WatchlistOut])
async def list_watchlists(session: SessionDep):
    items = (
        select(WatchlistItem.watchlist_id, func.count().label("n"))
        .group_by(WatchlistItem.watchlist_id)
        .subquery()
    )
    alerts = (
        select(
            WatchlistItem.watchlist_id,
            func.count(case((Alert.status == AlertStatus.ACTIVE, 1))).label("active"),
            func.count(case((Alert.status == AlertStatus.TRIGGERED, 1))).label("triggered"),
        )
        .join(Alert, Alert.watchlist_item_id == WatchlistItem.id)
        .group_by(WatchlistItem.watchlist_id)
        .subquery()
    )
    rows = await session.execute(
        select(
            Watchlist,
            func.coalesce(items.c.n, 0),
            func.coalesce(alerts.c.active, 0),
            func.coalesce(alerts.c.triggered, 0),
        )
        .outerjoin(items, items.c.watchlist_id == Watchlist.id)
        .outerjoin(alerts, alerts.c.watchlist_id == Watchlist.id)
        .order_by(Watchlist.sort_order, Watchlist.id)
    )
    out = []
    for wl, n, active, triggered in rows:
        o = WatchlistOut.model_validate(wl)
        o.item_count, o.active_alerts, o.triggered_alerts = n, active, triggered
        out.append(o)
    return out


@router.post("", response_model=WatchlistOut, status_code=201)
async def create_watchlist(body: WatchlistIn, session: SessionDep):
    max_order = await session.scalar(select(func.coalesce(func.max(Watchlist.sort_order), 0)))
    wl = Watchlist(name=body.name.strip(), description=body.description, sort_order=max_order + 1)
    session.add(wl)
    try:
        await session.commit()
    except IntegrityError:
        raise HTTPException(status.HTTP_409_CONFLICT, "A watchlist with that name already exists")
    return WatchlistOut.model_validate(wl)


@router.put("/order", status_code=204)
async def reorder_watchlists(body: OrderIn, session: SessionDep):
    for position, wl_id in enumerate(body.ids):
        wl = await session.get(Watchlist, wl_id)
        if wl:
            wl.sort_order = position
    await session.commit()


@router.patch("/{watchlist_id}", response_model=WatchlistOut)
async def update_watchlist(watchlist_id: int, body: WatchlistPatch, session: SessionDep):
    wl = await _get_watchlist(session, watchlist_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(wl, field, value.strip() if field == "name" else value)
    try:
        await session.commit()
    except IntegrityError:
        raise HTTPException(status.HTTP_409_CONFLICT, "A watchlist with that name already exists")
    await session.refresh(wl)
    return WatchlistOut.model_validate(wl)


@router.delete("/{watchlist_id}", status_code=204)
async def delete_watchlist(watchlist_id: int, session: SessionDep):
    wl = await _get_watchlist(session, watchlist_id)
    await session.delete(wl)
    await notify(session, CHANNEL_ALERTS_CHANGED)
    await session.commit()


@router.get("/{watchlist_id}/items", response_model=list[ItemOut])
async def list_items(watchlist_id: int, session: SessionDep):
    await _get_watchlist(session, watchlist_id)
    items = await session.scalars(
        select(WatchlistItem)
        .where(WatchlistItem.watchlist_id == watchlist_id)
        .options(selectinload(WatchlistItem.alerts))
        .order_by(WatchlistItem.added_at, WatchlistItem.id)
    )
    out = []
    for item in items:
        item.alerts.sort(key=lambda a: a.id)
        out.append(ItemOut.model_validate(item))
    return out


@router.post("/{watchlist_id}/items", response_model=ItemOut, status_code=201)
async def add_item(watchlist_id: int, body: ItemIn, session: SessionDep):
    await _get_watchlist(session, watchlist_id)
    if await session.get(Instrument, body.instrument_key) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown instrument")
    item = WatchlistItem(watchlist_id=watchlist_id, instrument_key=body.instrument_key,
                         notes=body.notes)
    session.add(item)
    try:
        await session.flush()
    except IntegrityError:
        raise HTTPException(status.HTTP_409_CONFLICT, "Stock is already in this watchlist")
    await notify(session, CHANNEL_ALERTS_CHANGED)
    await session.commit()
    item = await session.scalar(
        select(WatchlistItem)
        .where(WatchlistItem.id == item.id)
        .options(selectinload(WatchlistItem.alerts))
    )
    return ItemOut.model_validate(item)


@router.delete("/{watchlist_id}/items/{item_id}", status_code=204)
async def remove_item(watchlist_id: int, item_id: int, session: SessionDep):
    item = await session.get(WatchlistItem, item_id)
    if item is None or item.watchlist_id != watchlist_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    await session.delete(item)
    await notify(session, CHANNEL_ALERTS_CHANGED)
    await session.commit()
