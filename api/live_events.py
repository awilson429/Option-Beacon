"""Read-only SSE fan-out for committed snapshot identity changes.

This module does not scan, score, trade, or write persistence. A single
process-local watcher re-reads the existing live-snapshot identity and
publishes ``snapshot.changed`` when that digest changes. There is no durable
outbox, so event IDs are process-local and reconnect cannot replay missed
events.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import Request

from api.dependencies import get_service

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1"
EVENT_SNAPSHOT_CHANGED = "snapshot.changed"
EVENT_RESYNC_REQUIRED = "resync.required"


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def heartbeat_seconds() -> float:
    return _env_float("OPTIONBEACON_SSE_HEARTBEAT_SECONDS", 15.0)


def watch_seconds() -> float:
    return _env_float("OPTIONBEACON_SSE_WATCH_SECONDS", 1.0)


def json_dumps(value: Any) -> str:
    def default(item: Any) -> str:
        if isinstance(item, datetime):
            return item.isoformat()
        return str(item)

    return json.dumps(value, default=default, separators=(",", ":"))


def encode_sse(event: dict[str, Any]) -> str:
    payload = json_dumps(event)
    return (
        f"id: {event['event_id']}\n"
        f"event: {event['event_type']}\n"
        f"data: {payload}\n\n"
    )


def encode_heartbeat() -> str:
    return ": heartbeat\n\n"


def parse_event_frame(frame: str) -> dict[str, Any] | None:
    data_lines: list[str] = []
    for line in frame.splitlines():
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if not data_lines:
        return None
    return json.loads("\n".join(data_lines))


class LiveEventHub:
    """In-process fan-out. One watcher, N SSE subscribers. No DB connection per client."""

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue] = []
        self._seq = 0
        self.connected_clients = 0
        self.published = 0
        self.resyncs = 0

    def make_event(
        self,
        event_type: str,
        *,
        snapshot_id: str | None,
        cycle_id: str | None,
        entity_id: str | None = None,
        occurred_at: datetime | str | None = None,
    ) -> dict[str, Any]:
        self._seq += 1
        if event_type == EVENT_RESYNC_REQUIRED:
            self.resyncs += 1
        stamp = occurred_at or datetime.now(timezone.utc)
        identity = snapshot_id or "none"
        return {
            "event_id": f"{identity}:{self._seq}",
            "event_type": event_type,
            "occurred_at": stamp if isinstance(stamp, str) else stamp.isoformat(),
            "snapshot_id": snapshot_id,
            "cycle_id": cycle_id,
            "entity_id": entity_id,
            "schema_version": SCHEMA_VERSION,
        }

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=32)
        self._subscribers.append(queue)
        self.connected_clients = len(self._subscribers)
        logger.info("sse.client.connected count=%s", self.connected_clients)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        if queue in self._subscribers:
            self._subscribers.remove(queue)
        self.connected_clients = len(self._subscribers)
        logger.info("sse.client.disconnected count=%s", self.connected_clients)

    def publish(self, event: dict[str, Any]) -> None:
        self.published += 1
        logger.info(
            "sse.event.published type=%s id=%s clients=%s",
            event.get("event_type"), event.get("event_id"), self.connected_clients,
        )
        stale: list[asyncio.Queue] = []
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                stale.append(queue)
        for queue in stale:
            try:
                queue.put_nowait(self.make_event(
                    EVENT_RESYNC_REQUIRED,
                    snapshot_id=event.get("snapshot_id"),
                    cycle_id=event.get("cycle_id"),
                ))
            except asyncio.QueueFull:
                continue


def read_snapshot_cursor(service: Any) -> dict[str, Any] | None:
    reader = getattr(service, "live_snapshot_cursor", None)
    if callable(reader):
        return reader()
    snapshot_fn = getattr(service, "live_snapshot", None)
    if not callable(snapshot_fn):
        return None
    payload = snapshot_fn()
    scanner = payload.get("scanner") or {}
    return {
        "snapshot_id": payload.get("snapshot_id"),
        "cycle_id": scanner.get("cycle_id"),
        "occurred_at": payload.get("generated_at"),
    }


def apply_cursor(hub: LiveEventHub, last_id: str | None, cursor: dict[str, Any] | None) -> str | None:
    snapshot_id = None if cursor is None else cursor.get("snapshot_id")
    if not snapshot_id:
        return last_id
    snapshot_id = str(snapshot_id)
    if snapshot_id != last_id and last_id is not None:
        hub.publish(hub.make_event(
            EVENT_SNAPSHOT_CHANGED,
            snapshot_id=snapshot_id,
            cycle_id=None if cursor is None else cursor.get("cycle_id"),
            entity_id=snapshot_id,
            occurred_at=None if cursor is None else cursor.get("occurred_at"),
        ))
    return snapshot_id


async def run_identity_watcher(
    service: Any,
    hub: LiveEventHub,
    stop: asyncio.Event,
    interval: float | None = None,
) -> None:
    last_id: str | None = None
    delay = interval if interval is not None else watch_seconds()
    logger.info("sse.watch.loop interval=%s", delay)
    while not stop.is_set():
        try:
            cursor = read_snapshot_cursor(service)
        except Exception:
            logger.exception("sse.watch.read_failed")
            cursor = None
        last_id = apply_cursor(hub, last_id, cursor)
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
        except asyncio.TimeoutError:
            continue


def hub_for(request: Request) -> LiveEventHub:
    hub = getattr(request.app.state, "live_events", None)
    if isinstance(hub, LiveEventHub):
        return hub
    hub = LiveEventHub()
    request.app.state.live_events = hub
    return hub


async def stream_live_events(request: Request, last_event_id: str | None):
    hub = hub_for(request)
    service = get_service(request)
    queue = hub.subscribe()
    try:
        cursor = read_snapshot_cursor(service)
        snapshot_id = None if cursor is None else cursor.get("snapshot_id")
        cycle_id = None if cursor is None else cursor.get("cycle_id")
        occurred_at = None if cursor is None else cursor.get("occurred_at")
        if last_event_id:
            logger.info("sse.resync.required last_event_id=%s", last_event_id)
            yield encode_sse(hub.make_event(
                EVENT_RESYNC_REQUIRED, snapshot_id=snapshot_id, cycle_id=cycle_id,
                entity_id=last_event_id, occurred_at=occurred_at,
            ))
        else:
            yield encode_sse(hub.make_event(
                EVENT_SNAPSHOT_CHANGED, snapshot_id=snapshot_id, cycle_id=cycle_id,
                entity_id=snapshot_id, occurred_at=occurred_at,
            ))
        timeout = heartbeat_seconds()
        while True:
            try:
                disconnected = await request.is_disconnected()
            except RuntimeError:
                disconnected = False
            if disconnected:
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=timeout)
            except asyncio.TimeoutError:
                yield encode_heartbeat()
                continue
            except asyncio.CancelledError:
                break
            yield encode_sse(event)
    finally:
        hub.unsubscribe(queue)
        logger.info("sse.stream.closed clients=%s", hub.connected_clients)
