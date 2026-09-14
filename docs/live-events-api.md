# Live events SSE API

`GET /api/live/events` is a read-only Server-Sent Events stream that tells the React client when already-committed OptionBeacon state has a new canonical snapshot identity. It is not a second OptionBeacon implementation.

`GET /api/live/snapshot` remains the canonical bootstrap, reconnect, and resynchronization source. SSE only accelerates delivery of a change signal.

## What the stream does not do

The event layer does not run scans, call market-data providers, execute strategy logic, score candidates, generate decisions, open or close trades, calculate indicators, mutate persistence, or invent trading state.

## Event source

There is no durable outbox or `LISTEN/NOTIFY` bus in this repository. The FastAPI process therefore:

1. Starts one identity watcher per API process, not per browser.
2. Re-reads `live_snapshot_cursor()` on `OPTIONBEACON_SSE_WATCH_SECONDS` (default 1s).
3. Publishes `snapshot.changed` only after the persisted `snapshot_id` digest changes.

`live_snapshot_cursor()` hashes the same committed identities as `GET /api/live/snapshot` but skips `system_status`. Multiple API processes each run a watcher; missed/duplicated events are corrected by REST resync. Prefer a single Uvicorn worker.

The first observed identity is stored without publishing; the SSE handshake already emits the current `snapshot_id`. Missed events cannot be replayed after process restart.

## Endpoint

```http
GET /api/live/events
Accept: text/event-stream
```

Response headers include `Content-Type: text/event-stream`, `Cache-Control: no-cache, no-transform`, `Connection: keep-alive`, and `X-Accel-Buffering: no`.

## Envelope

Each `data:` frame is JSON:

```json
{
  "event_id": "abc123:{seq}",
  "event_type": "snapshot.changed",
  "occurred_at": "2026-09-13T14:30:00+00:00",
  "snapshot_id": "abc123...",
  "cycle_id": "cycle-42",
  "entity_id": "abc123...",
  "schema_version": "1"
}
```

The full live snapshot is never placed in the event. Clients that need trading state must fetch `GET /api/live/snapshot`.

## Event types

| Type | Meaning |
| --- | --- |
| `snapshot.changed` | Persisted snapshot identity changed, or handshake of the current identity. |
| `resync.required` | Replay is not available. Fetch the REST snapshot immediately. |

Granular `trade.*` / `decision.*` types are omitted until a durable committed log exists. The frontend must not invent them by diffing snapshots.

## Ordering and event IDs

`event_id` is `{snapshot_id}:{process_local_seq}`. It is suitable for in-process duplicate suppression. It is **not** a durable monotonic log:

- Sequence resets when the API process restarts.
- Timestamps are not a perfect global order.
- Two API replicas do not share sequence space.

## Reconnect and Last-Event-ID

The stream inspects the standard `Last-Event-ID` header. Replay from that cursor is **not** safely available, so the first frame is `resync.required`. Malformed or unknown cursors get the same event. The client must then GET `/api/live/snapshot`.

A first connection without `Last-Event-ID` receives `snapshot.changed` for the current identity. If that `snapshot_id` matches the snapshot already on screen, the UI should not churn.

## Heartbeats

Comment frames (`: heartbeat`) are emitted on `OPTIONBEACON_SSE_HEARTBEAT_SECONDS` (default 15). They keep idle proxies from closing the socket. They are not trading-state changes.

## Frontend fallback polling

`useLiveEvents()` is an isolated EventSource client. `useLiveSnapshot()` keeps REST polling:

| SSE state | Snapshot poll |
| --- | --- |
| open | `NEXT_PUBLIC_OPTIONBEACON_SNAPSHOT_SAFETY_POLL_MS` (default 60s) plus immediate revalidation on `snapshot.changed` / `resync.required` |
| connecting, closed, unavailable, or EventSource missing | `NEXT_PUBLIC_OPTIONBEACON_SNAPSHOT_POLL_MS` (default 15s) |

Manual Refresh still calls `mutate()` on the snapshot cache. A dropped SSE connection does not mark an otherwise-current persisted snapshot stale.

## Auth, CORS, and proxy

The current API has no access-token middleware; `fetchJson` sends only `Accept: application/json`. Native `EventSource` therefore uses the same unauthenticated GET as the snapshot client. CORS is an allow-list from `OPTIONBEACON_CORS_ORIGINS` (default `http://localhost:3000`). Wildcards are rejected. Credentials are disabled because the client does not use cookies. `Last-Event-ID` is an allowed request header so browser reconnect can preflight.

Production browsers call same-origin `/api/live/events` on Next.js. `frontend/src/app/api/[...path]/route.ts` streams FastAPI bytes, including heartbeats and `Last-Event-ID`, without buffering the body. FastAPI stays on Railway private HTTP; the client bundle must not contain `OPTIONBEACON_API_ORIGIN`. See `docs/react-fastapi-railway-pilot.md`.

## Configuration

| Variable | Default | Role |
| --- | --- | --- |
| `OPTIONBEACON_SSE_WATCH_SECONDS` | `1` | Process-local identity watch interval |
| `OPTIONBEACON_SSE_HEARTBEAT_SECONDS` | `15` | SSE comment interval |
| `OPTIONBEACON_API_ORIGIN` | (runtime, server-only) | Next.js upstream FastAPI origin |
| `NEXT_PUBLIC_OPTIONBEACON_SNAPSHOT_POLL_MS` | `15000` | REST poll when SSE is not healthy |
| `NEXT_PUBLIC_OPTIONBEACON_SNAPSHOT_SAFETY_POLL_MS` | `60000` | REST safety poll while SSE is open |

## Mock development helpers

The frontend mock API (`pnpm dev:mock-api`) implements the same SSE contract plus:

- `GET /dev/snapshot-bump` — change `snapshot_id` / SPY score and broadcast `snapshot.changed`
- `GET /dev/sse?enabled=0` — disable SSE (503) so polling fallback can be exercised
- `GET /dev/sse?enabled=1` — restore SSE
