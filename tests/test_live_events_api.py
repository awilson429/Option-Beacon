from __future__ import annotations

import asyncio
import inspect
import json

from fastapi.testclient import TestClient
from starlette.requests import Request

import api.live_events
from api.live_events import (EVENT_RESYNC_REQUIRED, EVENT_SNAPSHOT_CHANGED, LiveEventHub,
                             apply_cursor, encode_heartbeat, encode_sse, heartbeat_seconds,
                             parse_event_frame, stream_live_events, watch_seconds)
from api.main import create_app
from api.routes import live as live_routes
from tests.test_live_snapshot_api import ProjectionService


def _request(service, headers=None, hub=None) -> Request:
    app = create_app(service=service)
    app.state.live_events = hub or LiveEventHub()
    header_list = []
    for key, value in (headers or {}).items():
        header_list.append((key.lower().encode("latin-1"), value.encode("latin-1")))
    return Request({
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
        "scheme": "http", "path": "/api/live/events", "raw_path": b"/api/live/events",
        "query_string": b"", "headers": header_list, "client": ("testclient", 50000),
        "server": ("testserver", 80), "app": app,
    })


async def _take(request: Request, last_event_id: str | None, count: int) -> list[str]:
    frames: list[str] = []
    generator = stream_live_events(request, last_event_id)
    try:
        async for frame in generator:
            frames.append(frame)
            if len(frames) >= count:
                break
    finally:
        await generator.aclose()
    return frames


def _frames(service, count, last_event_id=None, headers=None, hub=None) -> tuple[Request, list[str]]:
    request = _request(service, headers=headers, hub=hub)
    return request, asyncio.run(_take(request, last_event_id, count))


def test_sse_route_content_type_uses_bounded_stream(monkeypatch):
    async def finite(request, last_event_id):
        yield encode_sse({
            "event_id": "test:1", "event_type": EVENT_SNAPSHOT_CHANGED,
            "occurred_at": "2026-09-13T14:30:00+00:00", "snapshot_id": "abc",
            "cycle_id": "cycle-1", "entity_id": "abc", "schema_version": "1",
        })

    monkeypatch.setattr(live_routes, "stream_live_events", finite)
    response = TestClient(create_app(service=ProjectionService())).get("/api/live/events")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "no-cache" in response.headers.get("cache-control", "")
    event = parse_event_frame(response.text)
    assert event["event_type"] == EVENT_SNAPSHOT_CHANGED


def test_handshake_envelope_is_valid():
    _, frames = _frames(ProjectionService(), 1)
    event = parse_event_frame(frames[0])
    assert event["event_type"] == EVENT_SNAPSHOT_CHANGED
    assert event["schema_version"] == "1"
    assert event["event_id"]
    assert event["snapshot_id"]
    assert event["cycle_id"] == "cycle-1"
    assert event["occurred_at"]
    assert frames[0].startswith("id: ")


def test_heartbeat_is_comment_not_trading_state(monkeypatch):
    monkeypatch.setenv("OPTIONBEACON_SSE_HEARTBEAT_SECONDS", "0.05")
    _, frames = _frames(ProjectionService(), 2)
    assert encode_heartbeat() in frames or any(frame.startswith(":") for frame in frames)
    payloads = [parse_event_frame(frame) for frame in frames]
    assert all(item is None or item["event_type"] != "heartbeat" for item in payloads)


def test_last_event_id_requests_resync_because_replay_is_unavailable():
    _, frames = _frames(ProjectionService(), 1, last_event_id="not-a-durable-cursor")
    event = parse_event_frame(frames[0])
    assert event["event_type"] == EVENT_RESYNC_REQUIRED
    assert event["entity_id"] == "not-a-durable-cursor"


def test_malformed_last_event_id_still_resyncs():
    _, frames = _frames(ProjectionService(), 1, last_event_id="\x00garbage")
    assert parse_event_frame(frames[0])["event_type"] == EVENT_RESYNC_REQUIRED


def test_sse_does_not_invoke_providers_strategy_or_writes():
    class Guarded(ProjectionService):
        def __init__(self):
            super().__init__()
            self.mutations = []
            self.provider_calls = []
            self.strategy_calls = []

        def scan(self):
            self.provider_calls.append("scan")

        def execute(self):
            self.strategy_calls.append("execute")

        def commit(self):
            self.mutations.append("commit")

    service = Guarded()
    _frames(service, 1)
    snapshot = TestClient(create_app(service=service)).get("/api/live/snapshot")
    assert snapshot.status_code == 200
    assert service.mutations == []
    assert service.provider_calls == []
    assert service.strategy_calls == []
    assert "scanner" in service.calls
    source = inspect.getsource(api.live_events)
    for forbidden in ("scan_once", "place_order", "yfinance", "commit()", "INSERT ", "UPDATE "):
        assert forbidden not in source


def test_disconnect_unsubscribes_client():
    hub = LiveEventHub()
    request, frames = _frames(ProjectionService(), 1, hub=hub)
    assert frames and request.app.state.live_events.connected_clients == 0


def test_watcher_publishes_only_after_committed_identity_changes():
    hub = LiveEventHub()
    first = apply_cursor(hub, None, {"snapshot_id": "aaa", "cycle_id": "c1"})
    assert first == "aaa" and hub.published == 0
    second = apply_cursor(hub, first, {"snapshot_id": "aaa", "cycle_id": "c1"})
    assert second == "aaa" and hub.published == 0
    third = apply_cursor(hub, second, {"snapshot_id": "bbb", "cycle_id": "c2"})
    assert third == "bbb" and hub.published == 1
    queue = hub.subscribe()
    apply_cursor(hub, third, {"snapshot_id": "ccc", "cycle_id": "c3"})
    event = queue.get_nowait()
    assert event["event_type"] == EVENT_SNAPSHOT_CHANGED
    assert event["snapshot_id"] == "ccc"


def test_encode_sse_envelope_is_stable_json():
    frame = encode_sse({
        "event_id": "abc:1",
        "event_type": EVENT_SNAPSHOT_CHANGED,
        "occurred_at": "2026-09-13T14:30:00+00:00",
        "snapshot_id": "abc",
        "cycle_id": "cycle-1",
        "entity_id": "abc",
        "schema_version": "1",
    })
    assert frame.startswith("id: abc:1\n")
    payload = parse_event_frame(frame)
    assert payload["event_type"] == "snapshot.changed"
    assert json.loads(frame.split("data: ", 1)[1])["schema_version"] == "1"


def test_openapi_includes_live_events():
    schema = TestClient(create_app(service=ProjectionService())).get("/openapi.json").json()
    assert "/api/live/events" in schema["paths"]
    assert "/api/live/snapshot" in schema["paths"]


def test_sse_handshake_skips_system_status():
    service = ProjectionService()
    _frames(service, 1)
    assert "system_status" not in service.calls
    assert "scanner" in service.calls


def test_watch_and_heartbeat_intervals_reject_invalid_values(monkeypatch):
    monkeypatch.setenv("OPTIONBEACON_SSE_WATCH_SECONDS", "0")
    monkeypatch.setenv("OPTIONBEACON_SSE_HEARTBEAT_SECONDS", "nope")
    assert watch_seconds() == 1.0
    assert heartbeat_seconds() == 15.0
