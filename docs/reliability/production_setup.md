# Reliable Production Setup

## Production topology

The supported topology is:

```text
scheduled scan worker -> PostgreSQL DATABASE_URL -> Streamlit dashboard
```

Streamlit Community Cloud renders the dashboard. It does not guarantee an
always-running background worker or durable local files. Production trade state
must use PostgreSQL through `DATABASE_URL`.

## Required environment variables

- `DATABASE_URL`: PostgreSQL connection URL. Store it in Streamlit Secrets for
  the dashboard and in the scheduler's secret store for the worker.
- `OPTIONBEACON_REQUIRE_DURABLE_STORAGE=true`: forces a visible unavailable
  state instead of local SQLite fallback.
- `FINNHUB_API_KEY`: existing quote/news provider credential.
- `TRADIER_ACCESS_TOKEN`: existing options provider credential.

Do not commit values. The application sanitizes repository/provider errors.

## Local development

SQLite is the default when `DATABASE_URL` is absent:

```bash
python -m optionbeacon.worker.scan_once
streamlit run app.py
```

The local database is `optionbeacon_state.db` and is ignored. It survives
ordinary local reruns but is not a production durability mechanism.

## PostgreSQL initialization

Schema initialization is explicit and idempotent:

```bash
DATABASE_URL=postgresql://... python -c "from trade_repository import TradeRepository; TradeRepository()"
```

Created tables:

- `opportunities`
- `authoritative_trades`
- `scanner_health`
- `scanner_locks`
- `legacy_imports`

All stored timestamps are timezone-aware UTC ISO values. Database unique
constraints enforce opportunity and trade idempotency.

## Streamlit Community Cloud

1. Deploy `app.py` from `main`.
2. Add `DATABASE_URL`, `FINNHUB_API_KEY`, and `TRADIER_ACCESS_TOKEN` to Secrets.
3. Add `OPTIONBEACON_REQUIRE_DURABLE_STORAGE=true` to the hosted environment if
   environment variables are supported; `main` builds already require durable
   storage in the dashboard service.
4. Run the schema initialization from a trusted worker environment.
5. Schedule `python -m optionbeacon.worker.scan_once` outside Streamlit.
6. Confirm the Trade Desk reports `Storage: DURABLE` and a recent successful
   scan.

## Degraded behavior

When durable storage is required but unavailable:

- the dashboard remains readable;
- it displays a storage-unavailable reliability state;
- it does not present an empty Scorecard as authoritative;
- it does not silently substitute local SQLite;
- provider and scanner calculations are unchanged.

## What is durable

With PostgreSQL:

- opportunities;
- authoritative entered/closed trades;
- scanner heartbeat/error state;
- idempotency/import ledger.

Not durable unless separately externalized:

- legacy JSONL/CSV files;
- scanner snapshot JSON;
- Streamlit/session caches;
- local option ledgers and paper-position JSON;
- temporary diagnostics and research shadow logs.

## Verification

```bash
python -c "from trade_state_service import authoritative_trade_state; print(authoritative_trade_state()['storage_state'])"
python -m optionbeacon.worker.scan_once
```

Inspect the dashboard reliability area or query `scanner_health` and
`authoritative_trades` with read-only database tooling.
