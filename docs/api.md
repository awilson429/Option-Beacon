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
- `GET /api/capital` — independent OB/BROAD simulated account state; MIRROR is explicitly excluded.
- `GET /api/capital/{lane}` — one OB or BROAD account, including canonical position metadata.
- `GET /api/capital/compare` — normalized realistic-execution comparison with evidence gating.
- `GET /api/capital/decisions/recent` — accepted and rejected allocation decisions with reason codes.
- `GET /api/risk/status` — daily-loss, open-risk, and drawdown entry-lock status.
- `GET /api/trades/active` — persisted active trades used as a separately refreshable home section.
- `GET /api/trades/recent` — persisted recent trades used as a separately refreshable home section.
- `GET /api/options-desk` — independent persisted existing-strategy projections for SPY and QQQ.
- `GET /api/options-desk/{symbol}` — one detailed existing-strategy projection.
- `GET /api/scalp/{symbol}` — latest persisted `SCALP_RESEARCH` / `SHADOW` observation.
- `GET /api/scalp/{symbol}/performance` — realistic-execution-first shadow metrics.
- `GET /api/scalp/compare` — normalized SPY/QQQ shadow comparison.

Request handlers do not call market-data providers, evaluate signals, or persist data. Missing scalp tables or observations are represented as unavailable state.

Capital endpoints are also read-only. The Railway worker owns additive capital-ledger writes. See `docs/capital-readiness.md` for risk defaults, execution assumptions, and conservative readiness thresholds.

## Decision provenance

The provenance API composes bounded canonical SPY/QQQ observations with the
existing opportunity, capital-decision, lane-position, management-snapshot,
and outcome records. It never calls a provider or evaluates strategy:

- `GET /api/provenance/recent?symbol=SPY&limit=100`
- `GET /api/provenance/opportunities/{opportunity_id}`
- `GET /api/provenance/trades/{trade_id}?lane=OB`

Trade provenance requires an explicit `OB` or `BROAD` lane. Legacy records
without an exact originating observation return an explicit unavailable state;
the API does not backfill by symbol or timestamp proximity. `GET /api/scanner`
also exposes the last canonical SPY/QQQ observation and provenance health as
additive fields.
