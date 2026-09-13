from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from api.dependencies import get_service
from api.schemas.live import LiveSnapshotResponse
from api.serialization import normalize_json_value

router = APIRouter(tags=["live snapshot"])


@router.get("/live/snapshot", response_model=LiveSnapshotResponse,
            summary="Canonical persisted OptionBeacon snapshot")
def live_snapshot(service=Depends(get_service)):
    validated = LiveSnapshotResponse.model_validate(
        normalize_json_value(service.live_snapshot()))
    return JSONResponse(content=normalize_json_value(validated.model_dump()))
