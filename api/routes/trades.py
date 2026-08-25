from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from api.dependencies import get_service
from api.schemas.trades import (ActiveTradeResponse, TradeHistoryResponse,
                                TradeManagementSnapshotResponse, TradeResponse)

router = APIRouter(tags=["trades"])


@router.get("/trades/active", response_model=list[ActiveTradeResponse], summary="Active authoritative and paper trades")
def active_trades(service=Depends(get_service)):
    return service.active_trades()


@router.get("/trades/recent", response_model=list[TradeResponse], summary="Recent authoritative trades")
def recent_trades(limit: Annotated[int, Query(ge=1, le=500)] = 100, service=Depends(get_service)):
    return service.recent_trades(limit)


@router.get("/trades/history", response_model=TradeHistoryResponse,
            summary="Canonical OB/BROAD trade Journal history")
def trade_history(
    lane: Annotated[str | None, Query(pattern="^(OB|BROAD)$")] = None,
    symbol: Annotated[str | None, Query(pattern="^(SPY|QQQ)$")] = None,
    status: Annotated[str | None, Query(pattern="^(OPEN|CLOSED)$")] = None,
    result: Annotated[str | None, Query(pattern="^(WIN|LOSS|BREAKEVEN|UNAVAILABLE)$")] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    service=Depends(get_service),
):
    return service.trade_history(lane=lane, symbol=symbol, status=status, result=result,
                                 date_from=date_from, date_to=date_to,
                                 limit=limit, offset=offset)


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
