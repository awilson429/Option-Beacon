# OptionBeacon React frontend

The primary OptionBeacon application is the snapshot-driven Market Command terminal at `/`. Existing focused workspaces and the internal snapshot diagnostics at `/diagnostics/live-snapshot` remain available. The React application runs alongside Streamlit and consumes FastAPI only.

## Primary terminal state

The root dashboard polls only `GET /api/live/snapshot` for trading state. The default interval is 15 seconds and can be configured with `NEXT_PUBLIC_OPTIONBEACON_SNAPSHOT_POLL_MS` (minimum 1000 ms). SWR prevents full-page reloads, retains the prior valid snapshot during revalidation, and reports a transient connection failure separately from the authoritative freshness and health carried by that snapshot.

Missing numeric values render as `Unavailable`, never zero. Stale, missing, unavailable, rejected, blocked, and disconnected states have separate visual treatments. Indicator values are displayed only from the persisted canonical observation; the browser performs no strategy calculations.

Future SSE delivery should invalidate or replace this same versioned snapshot cache. REST remains the bootstrap, reconnect, and resynchronization source, keyed by deterministic `snapshot_id` and authoritative cycle metadata.

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

Open `http://localhost:3000/` for the Trade Desk or `http://localhost:3000/options` for the Options Desk. Configure another API using `NEXT_PUBLIC_OPTIONBEACON_API_URL`.

For isolated visual development without FastAPI, run `pnpm dev:mock-api` in place of the Python command. The mock server is development-only and never participates in production builds.

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
