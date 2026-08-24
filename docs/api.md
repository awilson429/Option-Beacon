# OptionBeacon API (Phase 2)

The FastAPI service is a read-only boundary over existing OptionBeacon persistence. It runs alongside, and independently from, the Streamlit dashboard.

Install the repository requirements, then start it from the repository root:

```bash
uvicorn api.main:app --reload
```

Open `http://127.0.0.1:8000/docs` for OpenAPI documentation.

The API requires `DATABASE_URL` for authoritative production reads. It never reads Streamlit secrets. Configure allowed frontend origins with a comma-separated value:

```text
OPTIONBEACON_CORS_ORIGINS=http://localhost:3000,https://app.example.com
```

The default is only `http://localhost:3000`; wildcard origins are rejected. Phase 2 has no mutation, execution, authentication, or provider endpoints.
# SPY/QQQ Options Desk and scalp research

The React-ready, read-only contracts are:

- `GET /api/trade-desk` — persisted session summary, active-trade projection, conservative OB/BROAD/control lane rollups, and recent activity for the React home.
- `GET /api/trades/active` — persisted active trades used as a separately refreshable home section.
- `GET /api/trades/recent` — persisted recent trades used as a separately refreshable home section.
- `GET /api/options-desk` — independent persisted existing-strategy projections for SPY and QQQ.
- `GET /api/options-desk/{symbol}` — one detailed existing-strategy projection.
- `GET /api/scalp/{symbol}` — latest persisted `SCALP_RESEARCH` / `SHADOW` observation.
- `GET /api/scalp/{symbol}/performance` — realistic-execution-first shadow metrics.
- `GET /api/scalp/compare` — normalized SPY/QQQ shadow comparison.

Request handlers do not call market-data providers, evaluate signals, or persist data. Missing scalp tables or observations are represented as unavailable state.
