from typing import Annotated

from fastapi import APIRouter, Depends, Query

from api.dependencies import get_service
from api.schemas.trades import TradeResponse

router = APIRouter(tags=["trades"])


@router.get("/trades/active", response_model=list[TradeResponse], summary="Active authoritative trades")
def active_trades(service=Depends(get_service)):
    return service.active_trades()


@router.get("/trades/recent", response_model=list[TradeResponse], summary="Recent authoritative trades")
def recent_trades(limit: Annotated[int, Query(ge=1, le=500)] = 100, service=Depends(get_service)):
    return service.recent_trades(limit)
