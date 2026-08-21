from fastapi import APIRouter, Depends

from api.dependencies import get_service
from api.routes.common import normalized_symbol
from api.schemas.market import MarketSummary

router = APIRouter(tags=["market"])


@router.get("/market/{symbol}", response_model=MarketSummary, summary="Persisted market summary")
def market(symbol: str, service=Depends(get_service)):
    return service.market(normalized_symbol(symbol))
