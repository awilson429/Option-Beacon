from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from api.dependencies import get_service
from api.schemas.system import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="API and database health")
def health(service=Depends(get_service)):
    database = "connected" if service.database_available() else "unavailable"
    return {"status": "ok" if database == "connected" else "degraded", "database": database,
        "timestamp": datetime.now(timezone.utc), "version": "1"}
