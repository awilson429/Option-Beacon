# OptionBeacon React frontend

The primary OptionBeacon application is the snapshot-driven Market Command terminal at `/`. Existing focused workspaces and the internal snapshot diagnostics at `/diagnostics/live-snapshot` remain available. The React application runs alongside Streamlit and consumes FastAPI only.

## Primary terminal state

The root dashboard loads trading state from `GET /api/live/snapshot`. `GET /api/live/events` is a same-envelope SSE change signal: when the connection is open, snapshot revalidation is event-driven with a slower safety poll (`NEXT_PUBLIC_OPTIONBEACON_SNAPSHOT_SAFETY_POLL_MS`, default 60 seconds). If EventSource is missing, the stream errors, or SSE is disabled, the existing REST poll (`NEXT_PUBLIC_OPTIONBEACON_SNAPSHOT_POLL_MS`, default 15 seconds) remains the safety net. SWR prevents full-page reloads, retains the prior valid snapshot during revalidation, and reports a transient connection failure separately from the authoritative freshness and health carried by that snapshot. SSE transport state is not snapshot freshness.

Missing numeric values render as `Unavailable`, never zero. Stale, missing, unavailable, rejected, blocked, and disconnected states have separate visual treatments. Indicator values are displayed only from the persisted canonical observation; the browser performs no strategy calculations.

Future durable event logs can add granular lifecycle types. REST remains the bootstrap, reconnect, and resynchronization source, keyed by deterministic `snapshot_id` and authoritative cycle metadata. See `docs/live-events-api.md`.

## Local development

From the repository root, start FastAPI:

```powershell
python -m uvicorn api.main:app --reload --port 8000
```

In a second terminal:

```powershell
cd frontend
Copy-Item .env.example .env.local
pnpm install
pnpm dev
```

Configure another API using `NEXT_PUBLIC_OPTIONBEACON_API_URL`. An empty value uses same-origin `/api` (pair with server-only `OPTIONBEACON_API_ORIGIN` so Next can rewrite to FastAPI). Production topology is documented in `docs/react-fastapi-production-cutover.md`.

For isolated visual development without FastAPI, run `pnpm dev:mock-api` in place of the Python command. The mock server is development-only and never participates in production builds. `GET http://localhost:8000/dev/snapshot-bump` changes the mock snapshot identity; `GET http://localhost:8000/dev/sse?enabled=0` disables SSE so polling fallback can be checked.

## Refresh policy

- Strategy state: 10 seconds
- Scalp research state: 5 seconds
- Trade Desk session and lane summary: 10 seconds
- Active trades: 5 seconds
- Recent activity: 15 seconds
- System status: 15 seconds
- Scalp performance and comparison: 60 seconds

SWR keeps the prior successful value during revalidation. Endpoint errors stay local to the affected section and provide a retry control.

## Validation

```powershell
pnpm test
pnpm lint
pnpm build
```

## Known API gaps

The Trade Desk reports only persisted fields. Contract details and unrealized P&L appear only when existing trade metadata supplies them; unavailable values are shown explicitly. MIRROR/control remains labeled as research/shadow and is never promoted to a primary live lane.

The Trade Desk also shows independent OB/BROAD simulated account cards and recent capital decisions when the worker has persisted the canonical readiness tables. An unavailable card means the account is configured but has no durable worker snapshot; the browser never creates capital state or calculates position size.

The current persisted Options Desk response does not yet supply strategy score, entry zone, maximum chase, stop, targets, risk/reward, exit score/state, contract bid/ask, delta, volume, or open interest. Components support those optional fields and render intentional empty states instead of manufacturing values. Add these fields in a future additive backend contract task; do not calculate them in TypeScript.
