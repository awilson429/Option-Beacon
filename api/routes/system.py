from fastapi import APIRouter, Depends

from api.dependencies import get_service
from api.schemas.system import SystemStatus

router = APIRouter(tags=["system"])


@router.get("/system/status", response_model=SystemStatus, summary="Non-secret operational status")
def system_status(service=Depends(get_service)):
    return service.system_status()
