from fastapi import APIRouter, Depends

from api.dependencies import get_service
from api.schemas.scanner import ScannerResponse

router = APIRouter(tags=["scanner"])


@router.get("/scanner", response_model=ScannerResponse, summary="Persisted scanner state")
def scanner(service=Depends(get_service)):
    return service.scanner()
