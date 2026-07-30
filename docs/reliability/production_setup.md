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

## Neon PostgreSQL

1. Create a Neon project and database.
2. In the Neon dashboard, copy a PostgreSQL connection string for the intended
   database and role.
3. Keep SSL required. Neon connection strings normally include
   `sslmode=require`; the repository adds it when absent.
4. Store the same `DATABASE_URL` value in Streamlit Secrets and Railway
   Variables. Never paste it into source, logs, screenshots, or issue text.
5. Set `OPTIONBEACON_REQUIRE_DURABLE_STORAGE=true` and
   `OPTIONBEACON_ENVIRONMENT=production` in Railway. The Streamlit build from
   `main` also requires durable storage.
6. Initialize the schema with a trusted one-off process.
7. Run the healthcheck and PostgreSQL integration test without printing the
   connection value.

Neon offers direct and pooled connection strings. The worker is a long-running,
low-concurrency process and may use a direct connection. Streamlit creates
short-lived connections across reruns and can use Neon's pooled connection
string. Both strings must target the same project, database, role permissions,
and schema. The current psycopg2 driver works with either; transaction-pooling
limitations should be reviewed before introducing session-level database
features.

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
python -m optionbeacon.worker.healthcheck
```

Inspect the dashboard reliability area or query `scanner_health` and
`authoritative_trades` with read-only database tooling.

Run the real integration path against a disposable/test Neon database:

```bash
TEST_DATABASE_URL=postgresql://... python -m pytest \
  tests/test_production_storage_modes.py -q
```

The test is skipped when `TEST_DATABASE_URL` is absent. A skipped result is not
production database verification.
