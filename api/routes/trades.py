from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from api.dependencies import get_service
from api.schemas.trades import ActiveTradeResponse, TradeManagementSnapshotResponse, TradeResponse

router = APIRouter(tags=["trades"])


@router.get("/trades/active", response_model=list[ActiveTradeResponse], summary="Active authoritative and paper trades")
def active_trades(service=Depends(get_service)):
    return service.active_trades()


@router.get("/trades/recent", response_model=list[TradeResponse], summary="Recent authoritative trades")
def recent_trades(limit: Annotated[int, Query(ge=1, le=500)] = 100, service=Depends(get_service)):
    return service.recent_trades(limit)


@router.get("/trades/{trade_id}/management", response_model=list[TradeManagementSnapshotResponse],
            summary="Canonical management snapshot history")
def trade_management_history(
    trade_id: str,
    lane: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    service=Depends(get_service),
):
    rows = service.trade_management_history(trade_id, lane=lane)
    if not rows:
        raise HTTPException(status_code=404, detail="Canonical trade management history not found.")
    return rows
