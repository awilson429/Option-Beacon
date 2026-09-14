# Railway React / FastAPI production pilot

This runbook prepares a **production pilot** where Market Command is a public Next.js UI and FastAPI stays on Railway private networking. Streamlit remains live as rollback. The worker remains the only writer of trading state.

Do not retire Streamlit. Do not make React the only production UI until this pilot is accepted and the Streamlit gap list is acceptable.

## Final topology

```text
Providers
  → Railway worker (railway.toml)     PRIVATE
  → PostgreSQL DATABASE_URL           PRIVATE
  → FastAPI (railway.api.toml)        PRIVATE  http://${{api.RAILWAY_PRIVATE_DOMAIN}}:${{api.PORT}}
  → Next.js (railway.frontend.toml)   PUBLIC   same-origin /api/* proxy
  → Browser
Streamlit Community Cloud             PUBLIC rollback/reference
```

Suggested Railway service names in one project/environment: `worker`, `api`, `frontend`. If the FastAPI service is named something else, replace `api` in every reference variable with that name.

Internal Railway traffic uses **http://**, never public https://.

## Public vs private

| Service | Public? | Notes |
| --- | --- | --- |
| Next.js `frontend` | **Yes** | Browser UI. Attach a Railway or custom domain. |
| FastAPI `api` | **No** | Do not generate or keep an `*.up.railway.app` domain. |
| Worker `worker` | **No** | No HTTP server. |
| PostgreSQL | **No** | Application exposure is not required. |
| Streamlit | **Yes** | Separate rollback UI. |

Railway healthchecks query the container `PORT` and use hostname `healthcheck.railway.app`. They do **not** require a public domain. FastAPI can stay private with `healthcheckPath = /api/health`.

Repository files cannot delete an already-attached public domain. If Railway auto-created one on the API service, remove it in the service **Settings → Networking**.

## Next.js proxy architecture

The browser uses same-origin paths only:

```text
/api/live/snapshot
/api/live/events
/api/health
/api/system/status
...
```

`frontend/src/app/api/[...path]/route.ts` is a Node.js GET reverse proxy. It reads **runtime** `OPTIONBEACON_API_ORIGIN` and streams the FastAPI response body. This is not a `next.config` rewrite: rewrites can buffer SSE.

Production Next.js does **not** set `NEXT_PUBLIC_OPTIONBEACON_API_URL`. The client bundle resolves an empty API base (`""`), so `EventSource` and `fetch` call `/api/...` on the Next origin.

If production `OPTIONBEACON_API_ORIGIN` is missing, `/api/*` returns **503** and does not fall back to localhost. `next build` does not require the variable.

Development default remains `http://localhost:8000` in the browser unless you opt into the proxy (empty `NEXT_PUBLIC_OPTIONBEACON_API_URL` plus `OPTIONBEACON_API_ORIGIN=http://localhost:8000`).

## SSE through Next.js

The proxy:

- copies `text/event-stream`
- sets `Cache-Control: no-cache, no-transform`
- sets `X-Accel-Buffering: no` and `Connection: keep-alive`
- forwards `Last-Event-ID`
- pipes `upstream.body` (no `text()` / full-buffer)
- aborts upstream when the browser disconnects (`request.signal`)

Heartbeats (`: heartbeat`) are FastAPI comments and pass through unchanged. Reconnect still uses native EventSource against `/api/live/events`. REST snapshot remains canonical; polling fallback is unchanged.

## Railway configuration files

| File | Service | Root directory |
| --- | --- | --- |
| `railway.toml` | worker | repository root |
| `railway.intraday.toml` | optional intraday worker | repository root |
| `railway.api.toml` | FastAPI | repository root |
| `railway.frontend.toml` | Next.js | **`frontend`** |

Do not change the worker start command. Do not add `--workers` to Uvicorn. Keep replica count at 1 for FastAPI.

FastAPI starts with `python -m api.serve`, which listens on `0.0.0.0` and `::` for the same `$PORT`. That covers Railway IPv4 healthchecks and IPv6-only private DNS without a public domain. Newer Railway environments may resolve `*.railway.internal` to both families; do not migrate environments solely for this. Local development still uses `--host 0.0.0.0` / `--reload` as documented in `frontend/README.md`.

## Required variables

### Worker (unchanged)

`DATABASE_URL`, `OPTIONBEACON_REQUIRE_DURABLE_STORAGE=true`, `OPTIONBEACON_ENVIRONMENT=production`, provider secrets.

### FastAPI service (`api`)

| Variable | Required | Value |
| --- | --- | --- |
| `DATABASE_URL` | yes | Same reference as the worker, e.g. `${{Postgres.DATABASE_URL}}` |
| `OPTIONBEACON_SSE_WATCH_SECONDS` | recommended | `2` or `5` in production |
| `OPTIONBEACON_SSE_HEARTBEAT_SECONDS` | optional | default `15` |
| `OPTIONBEACON_CORS_ORIGINS` | no in this topology | Default `http://localhost:3000` is unused for browser traffic. May be left default or set empty. Not authentication. |

Do not set a public `PORT` mapping. Railway injects `PORT`.

### Next.js service (`frontend`)

| Variable | Required | Value |
| --- | --- | --- |
| `OPTIONBEACON_API_ORIGIN` | **yes at runtime** | `http://${{api.RAILWAY_PRIVATE_DOMAIN}}:${{api.PORT}}` |
| `NEXT_PUBLIC_OPTIONBEACON_API_URL` | **omit** | If set, it is baked into client JS at build time and can bypass the proxy. |
| `NEXT_PUBLIC_OPTIONBEACON_SNAPSHOT_POLL_MS` | optional | default `15000` |
| `NEXT_PUBLIC_OPTIONBEACON_SNAPSHOT_SAFETY_POLL_MS` | optional | default `60000` |

`OPTIONBEACON_API_ORIGIN` is server-only. Never create `NEXT_PUBLIC_OPTIONBEACON_API_ORIGIN`.

## CORS vs authentication

After this cutover, browsers talk to Next.js. FastAPI CORS is not on the production browser path. Localhost CORS remains so `pnpm dev` can call FastAPI directly.

CORS is not access control. FastAPI is unauthenticated. **Private networking is the security boundary.** If FastAPI is given a public domain, anyone can read snapshots and trades.

## Security / exposure

- There is no login system in this task.
- No repository code path gives the browser a FastAPI hostname in production, provided `NEXT_PUBLIC_OPTIONBEACON_API_URL` is unset.
- Next.js server can reach FastAPI; the browser cannot resolve `*.railway.internal`.
- If public exposure of FastAPI is unavoidable, **stop** — do not add a weak token on native EventSource.

## Manual Railway steps (not performed by this repository)

1. Confirm the worker is healthy and Streamlit still loads persisted state.
2. Create service `api` from this repo, config `railway.api.toml`, root directory `/`.
3. Attach the same PostgreSQL `DATABASE_URL`. Set watcher interval. **Do not add a public domain.**
4. Create service `frontend` from this repo, config `railway.frontend.toml`, **root directory `frontend`**.
5. Set `OPTIONBEACON_API_ORIGIN=http://${{api.RAILWAY_PRIVATE_DOMAIN}}:${{api.PORT}}` on `frontend`.
6. Attach a public domain only to `frontend`.
7. If `api` already has a public domain, delete it.
8. Do not run destructive cutovers. Leave Streamlit published.

## Step-by-step pilot

1. Confirm worker remains healthy (scans persist, Streamlit Trade Desk still truthful).
2. Deploy FastAPI service from `railway.api.toml` with start command `python -m api.serve` (IPv4+IPv6, one process). If the Railway service Settings override the start command, set it to that same value.
3. Connect `DATABASE_URL` (same database as the worker).
4. Set `OPTIONBEACON_SSE_WATCH_SECONDS` (start at `2`).
5. Keep FastAPI private-only. Verify it has no public domain.
6. Deploy Next.js from `railway.frontend.toml` with root `frontend`.
7. Configure `OPTIONBEACON_API_ORIGIN` with the private reference variable (http, not https).
8. Give Next.js a public Railway or custom domain.
9. Verify `https://<next>/api/health` (proxied). Expect `api=online` and database connected/degraded independently of market hours.
10. Verify `https://<next>/api/live/snapshot`.
11. Verify `https://<next>/api/live/events` is `text/event-stream` and heartbeats arrive.
12. Open Market Command. Confirm the browser network tab shows same-origin `/api/...` only.
13. Compare SPY/QQQ and TAKE/REJECTED against Streamlit for the same persisted cycle.
14. Leave Streamlit live.
15. Rollback: keep worker + database; point operators at Streamlit; stop or ignore Next/FastAPI (read-only).

## Pilot acceptance checklist

- [ ] Next public URL loads Market Command
- [ ] Browser network requests are same-origin `/api/...` (no FastAPI hostname)
- [ ] Client JS contains no `railway.internal` / private API origin
- [ ] `GET /api/health` through Next returns 2xx
- [ ] `GET /api/live/snapshot` through Next returns canonical JSON
- [ ] `GET /api/live/events` through Next is SSE (`text/event-stream`)
- [ ] `snapshot.changed` refreshes Market Command without a full page reload
- [ ] SSE failure falls back to REST polling; TAKE is not marked stale from transport loss
- [ ] FastAPI has no public domain
- [ ] Worker continues scanning/persisting
- [ ] Streamlit continues operating
- [ ] SPY/QQQ output matches persisted Streamlit reference
- [ ] Stale TAKE safety still holds
- [ ] `/diagnostics/live-snapshot` uses the same `/api/live/snapshot`

## Rollback

1. Worker and PostgreSQL stay up.
2. Operators use Streamlit.
3. Next.js and FastAPI may be stopped independently. They do not own trades.
