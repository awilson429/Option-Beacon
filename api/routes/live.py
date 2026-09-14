from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse

from api.dependencies import get_service
from api.live_events import stream_live_events
from api.schemas.live import LiveSnapshotResponse
from api.serialization import normalize_json_value

router = APIRouter(tags=["live snapshot"])


@router.get("/live/snapshot", response_model=LiveSnapshotResponse,
            summary="Canonical persisted OptionBeacon snapshot")
def live_snapshot(service=Depends(get_service)):
    validated = LiveSnapshotResponse.model_validate(
        normalize_json_value(service.live_snapshot()))
    return JSONResponse(content=normalize_json_value(validated.model_dump()))


@router.get("/live/events", summary="Authoritative snapshot-change events")
async def live_events(
    request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
):
    return StreamingResponse(
        stream_live_events(request, last_event_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
