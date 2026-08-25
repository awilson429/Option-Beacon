from typing import Annotated

from fastapi import APIRouter, Depends, Query

from api.dependencies import get_service
from api.schemas.provenance import (
    OpportunityProvenanceResponse,
    RecentProvenanceResponse,
    TradeProvenanceResponse,
)

router = APIRouter(tags=["provenance"])


@router.get("/provenance/recent", response_model=RecentProvenanceResponse,
            summary="Recent canonical SPY/QQQ decision observations")
def recent_provenance(
    symbol: Annotated[str | None, Query(pattern="^(SPY|QQQ)$")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    service=Depends(get_service),
):
    return service.recent_provenance(symbol=symbol, limit=limit)


@router.get("/provenance/opportunities/{opportunity_id}",
            response_model=OpportunityProvenanceResponse,
            summary="Exact opportunity decision provenance")
def opportunity_provenance(opportunity_id: str, service=Depends(get_service)):
    return service.opportunity_provenance(opportunity_id)


@router.get("/provenance/trades/{trade_id}", response_model=TradeProvenanceResponse,
            summary="Exact lane-owned trade decision provenance")
def trade_provenance(
    trade_id: str,
    lane: Annotated[str, Query(pattern="^(OB|BROAD)$")],
    service=Depends(get_service),
):
    return service.trade_provenance(trade_id, lane=lane)
