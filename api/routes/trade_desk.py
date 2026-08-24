from fastapi import APIRouter, Depends

from api.dependencies import get_service
from api.routes.common import normalized_symbol
from api.schemas.trade_desk import TradeDeskHomeResponse, TradeDeskResponse

router = APIRouter(tags=["trade desk"])


@router.get("/trade-desk", response_model=TradeDeskHomeResponse, summary="Trade Desk home state")
def trade_desk_home(service=Depends(get_service)):
    return service.trade_desk_home()


@router.get("/trade-desk/{symbol}", response_model=TradeDeskResponse, summary="Trade Desk state")
def trade_desk(symbol: str, service=Depends(get_service)):
    return service.trade_desk(normalized_symbol(symbol))
