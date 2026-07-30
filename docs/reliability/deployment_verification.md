# Production Deployment Verification Record

Date: 2026-07-30

This record distinguishes local verification from live PostgreSQL verification.
No credential values are recorded.

## A. Local development

- `DATABASE_URL`: absent
- durable-storage requirement: false/absent
- selected backend: SQLite
- schema initialization: idempotent
- repository reinitialization: retained opportunity/trade data
- Streamlit import/syntax: passed
- Streamlit startup smoke check: HTTP 200 on the temporary local endpoint
- `scan_once`: covered with deterministic scanner/provider fixtures
- result: **verified locally**

## B. Correct production configuration

- expected backend with `DATABASE_URL`: PostgreSQL
- SQLite fallback when durable storage is required: prohibited by code/tests
- schema initialization: implemented as idempotent `CREATE TABLE IF NOT EXISTS`
- Streamlit and Railway share the database when given connection strings for
  the same Neon project/database/schema
- real PostgreSQL lifecycle test: available through `TEST_DATABASE_URL`
- current workspace result: **not live-verified because `TEST_DATABASE_URL` is
  absent**

This state must not be described as completed Neon verification.

## C. Broken production configuration

- `DATABASE_URL`: absent
- `OPTIONBEACON_REQUIRE_DURABLE_STORAGE=true`
- repository construction: raises sanitized `RepositoryUnavailable`
- SQLite file creation: does not occur
- worker/scan command: nonzero
- dashboard: storage-unavailable error, not "No open trades"
- result: **verified by automated test**

## D. Invalid production database

- malformed/unreachable PostgreSQL URL: repository unavailable
- SQLite fallback: does not occur
- dashboard: visible storage-unavailable state
- error output: exception type only; URL/password not exposed
- result: **verified by automated test against an unreachable sanitized URL**

## Required live gate

Before merge or production declaration:

```bash
TEST_DATABASE_URL=postgresql://... python -m pytest \
  tests/test_production_storage_modes.py -q
```

The conditional PostgreSQL test covers schema creation, opportunity creation,
trade opening, duplicate/concurrent idempotency, open retrieval, heartbeat,
scanner error persistence, update, closure, and repository reinitialization.
