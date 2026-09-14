# React / FastAPI production cutover

This is the operational configuration for making Market Command the primary UI. Streamlit remains deployed and runnable. Trading logic stays in the Python worker.

## Intended production topology

Current committed Railway config deploys **workers only**:

```text
Railway worker (railway.toml)
  python -m optionbeacon.worker.run
  -> PostgreSQL DATABASE_URL
  -> Streamlit Community Cloud (app.py)   # current primary UI

Optional: Railway intraday worker (railway.intraday.toml)
```

React + FastAPI are **not** started by `railway.toml`. The production-pilot topology is documented in `docs/react-fastapi-railway-pilot.md`:

```text
market-data providers
  -> Railway worker (authoritative scans / persistence)
  -> PostgreSQL (DATABASE_URL)
  -> FastAPI read-only API (railway.api.toml, Railway private network only)
       GET /api/live/snapshot   canonical
       GET /api/live/events     change notification only
  -> Next.js Market Command (public; same-origin /api proxy)
Streamlit app.py remains the rollback UI
```

Replicas are not configured in this repository. FastAPI should run **one Uvicorn worker process** (`uvicorn` default). Multiple API processes remain *correct* because REST snapshot is canonical; they may duplicate or miss SSE events and each would run its own identity watcher.

## Required services

| Role | How it runs today | Cutover requirement |
| --- | --- | --- |
| Worker | `railway.toml` `python -m optionbeacon.worker.run` | Keep |
| Database | `DATABASE_URL` PostgreSQL | Keep; `OPTIONBEACON_REQUIRE_DURABLE_STORAGE=true` |
| Streamlit | Community Cloud `streamlit run app.py` | Keep as fallback |
| FastAPI | Local `uvicorn api.main:app` only | Deploy `railway.api.toml` **without** a public domain |
| Next.js | Local `pnpm dev` / `next start` only | Deploy `railway.frontend.toml` with public domain + `OPTIONBEACON_API_ORIGIN` |

FastAPI start command:

```bash
python -m uvicorn api.main:app --host :: --port $PORT
```

Do not add `--workers N`. One process keeps SSE fan-out in-process and avoids N watchers against PostgreSQL.

Health check path: `GET /api/health`. It reports API liveness and database reachability. It does **not** depend on market hours or scanner freshness.

## Environment variables

### Database / worker (existing)

| Variable | Required in production | Notes |
| --- | --- | --- |
| `DATABASE_URL` | yes | PostgreSQL. Never commit. |
| `OPTIONBEACON_REQUIRE_DURABLE_STORAGE` | yes (`true`) | No SQLite fallback |
| `OPTIONBEACON_ENVIRONMENT` | yes (`production`) | Worker/dashboard storage mode |
| `OPTIONBEACON_SCAN_SECONDS` | optional | Default 300, bounded 30–3600 |
| `OPTIONBEACON_SCANNER_ID` | optional | Default production scanner id |
| `OPTIONBEACON_DB_CONNECT_TIMEOUT_SECONDS` | optional | 1–60, default 10 |
| `FINNHUB_API_KEY` | worker | Provider credential |
| `TRADIER_ACCESS_TOKEN` | worker | Provider credential, not API auth |

### FastAPI

| Variable | Required in production | Notes |
| --- | --- | --- |
| `DATABASE_URL` | yes | Same database as the worker |
| `OPTIONBEACON_CORS_ORIGINS` | no in the private topology | Browser traffic is same-origin through Next. Default `http://localhost:3000` remains for local direct-to-API development. `*` is rejected. CORS is not authentication. |
| `OPTIONBEACON_SSE_WATCH_SECONDS` | optional | Identity watch interval, default `1`. Production may use `2`–`5` to reduce DB load. |
| `OPTIONBEACON_SSE_HEARTBEAT_SECONDS` | optional | SSE comment interval, default `15` |

There is **no** `OPTIONBEACON_ACCESS_TOKEN` and no FastAPI auth middleware. Private Railway networking is the production security boundary for FastAPI.

### Next.js

| Variable | Required in production | Notes |
| --- | --- | --- |
| `OPTIONBEACON_API_ORIGIN` | **yes at runtime** | Server-only FastAPI origin, e.g. `http://${{api.RAILWAY_PRIVATE_DOMAIN}}:${{api.PORT}}`. Never `NEXT_PUBLIC_`. |
| `NEXT_PUBLIC_OPTIONBEACON_API_URL` | **omit in production** | Unset production builds use same-origin `/api`. Setting this bakes a hostname into client JS. Development may set `http://localhost:8000`. |
| `NEXT_PUBLIC_OPTIONBEACON_SNAPSHOT_POLL_MS` | optional | REST poll when SSE is down. Default `15000`. Minimum `1000`. |
| `NEXT_PUBLIC_OPTIONBEACON_SNAPSHOT_SAFETY_POLL_MS` | optional | REST safety poll when SSE is open. Default `60000`. |

Production browser path: same-origin Next proxy. See `docs/react-fastapi-railway-pilot.md`.

```text
OPTIONBEACON_API_ORIGIN=http://${{api.RAILWAY_PRIVATE_DOMAIN}}:${{api.PORT}}
# do not set NEXT_PUBLIC_OPTIONBEACON_API_URL
```

## CORS

Production browsers do not call FastAPI. Next.js proxies same-origin `/api` server-side, so CORS is not on the pilot browser path.

Local development may still call FastAPI from `http://localhost:3000`:

- Allow-list only. Wildcards are stripped.
- `Last-Event-ID` is allowed so EventSource reconnect can preflight.
- Credentials are **disabled**.
- SSE `Content-Type` is `text/event-stream` with `Cache-Control: no-cache, no-transform`, `Connection: keep-alive`, and `X-Accel-Buffering: no`.

## Auth / exposure

The FastAPI surface is read-only over persisted state and is **unauthenticated**. The production pilot keeps FastAPI on Railway private networking so the browser cannot reach it. Anyone who can reach a **public** FastAPI origin can still read snapshots, trades, and scanner projections.

- Do not treat CORS as access control.
- Do not add `Authorization` to native `EventSource`; it cannot set custom headers.
- Do not attach a public domain to FastAPI to make EventSource "easier".
- Future token auth should stay behind the same-origin Next proxy or cookie/session transport.

`TRADIER_ACCESS_TOKEN` is a market-data provider secret for the worker, not an API login.

## SSE multi-process behavior

`LiveEventHub` is process-local. Restart, reconnect to another process, or multiple Uvicorn workers can miss or duplicate events. The client must treat `resync.required` / reconnect / polling as the correctness path via `GET /api/live/snapshot`. That cannot invent trading state.

## Watcher cost

The SSE watcher re-reads snapshot **identity** (scanner + active trades + 20 recent trades), not `system_status`. It does not reconstruct the HTTP snapshot document, but it still uses the same bounded repository projections that identity hashes. At the default 1s interval that is on the order of tens of read queries per second per API process. Prefer one API process; raise `OPTIONBEACON_SSE_WATCH_SECONDS` in production if PostgreSQL load is visible.

`GET /api/live/snapshot` additionally reads `system_status` (database ping + latest scan health). Under the in-process test projection it returns in well under 1s; do not add a second snapshot implementation.

## Streamlit remains

```powershell
python -m streamlit run app.py
```

No production workflow should depend on a Streamlit-only write. Workers persist to PostgreSQL independently of the dashboard.

### React gap list (do not block FastAPI/Next deploy, do block "replace Streamlit")

Streamlit production navigation still exposes workspaces React does not:

- Paper Trading
- Strategy Lab
- Advanced (legacy history, event dumps, developer tools)
- Full Opportunities scanner (all symbols, sector strength, ranked table)
- Intraday extras beyond the Options Desk snapshot
- Forensic / Winner DNA / selectivity analytics
- Dedicated capital/risk operator cards (API exists; Market Command does not present them as a workspace)

React currently covers Market Command, SPY/QQQ Options, Scanner, Active Trades, Journal, and live-snapshot diagnostics.

## Production readiness checklist

- [ ] PostgreSQL `DATABASE_URL` on worker, FastAPI, and Streamlit
- [ ] Worker running (`railway.toml`) with durable storage required
- [ ] FastAPI service deployed (`railway.api.toml`), one Uvicorn process, `/api/health` as liveness, **no public domain**
- [ ] Next.js deployed (`railway.frontend.toml`) with runtime `OPTIONBEACON_API_ORIGIN` and **no** `NEXT_PUBLIC_OPTIONBEACON_API_URL`
- [ ] `GET /api/live/snapshot` succeeds same-origin from the Next public host
- [ ] `GET /api/live/events` connects through the Next proxy; fallback poll still configured
- [ ] Operators know FastAPI is unauthenticated if it is ever given a public domain
- [ ] Health checks use `/api/health` on FastAPI and `/` on Next; market/scanner freshness is not liveness
- [ ] Worker/API logs exclude secrets
- [ ] Streamlit still reachable as rollback
- [ ] Rollback: point operators at Streamlit; leave the worker running; FastAPI/Next can be stopped independently

## Rollback

1. Keep the Railway worker and PostgreSQL unchanged.
2. Direct operators to the Streamlit Trade Desk.
3. Stop or ignore FastAPI/Next. They are read-only and do not own trades.
