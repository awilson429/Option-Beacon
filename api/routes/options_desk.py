from fastapi import APIRouter, Depends

from api.dependencies import get_service
from api.routes.common import normalized_symbol
from api.schemas.options_desk import ComparisonResponse, OptionsDeskResponse, PerformanceResponse, ScalpStateResponse
from api.schemas.trade_desk import TradeDeskResponse

router = APIRouter(tags=["options desk", "scalp research"])


@router.get("/options-desk", response_model=OptionsDeskResponse)
def options_desk(service=Depends(get_service)):
    return service.options_desk()


@router.get("/options-desk/{symbol}", response_model=TradeDeskResponse)
def options_desk_symbol(symbol: str, service=Depends(get_service)):
    return service.trade_desk(normalized_symbol(symbol))


@router.get("/scalp/compare", response_model=ComparisonResponse)
def scalp_compare(service=Depends(get_service)):
    return service.scalp_compare()


@router.get("/scalp/{symbol}", response_model=ScalpStateResponse)
def scalp_state(symbol: str, service=Depends(get_service)):
    return service.scalp_state(normalized_symbol(symbol))


@router.get("/scalp/{symbol}/performance", response_model=PerformanceResponse)
def scalp_performance(symbol: str, service=Depends(get_service)):
    return service.scalp_performance(normalized_symbol(symbol))
