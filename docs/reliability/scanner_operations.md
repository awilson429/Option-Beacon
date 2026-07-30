# Scanner Operations

## One scan

Run:

```bash
python -m optionbeacon.worker.scan_once
```

The command:

1. connects to the authoritative repository;
2. acquires the scanner lock;
3. records scan start and application version;
4. runs the existing signal generator without changing strategy rules;
5. writes the compatibility snapshot;
6. synchronizes legacy-compatible outcomes into the repository;
7. records completion, success, duration, symbol count, and market-data state;
8. releases the lock.

Exit codes:

- `0`: scan completed with results;
- `1`: fatal failure or no usable results;
- `2`: another invocation owns the unexpired lock.

## Continuous process

For a process manager that supports long-running jobs:

```bash
python -m optionbeacon.worker.run --interval-seconds 300
```

Prefer a platform scheduler invoking `scan_once` every five minutes. The worker
loop is not started by Streamlit.

Realistic schedulers include GitHub Actions cron, a cloud cron/worker service,
or an existing server process manager. Verify provider terms and execution-time
limits. Streamlit Community Cloud is not the worker scheduler.

## Overlap protection

`scanner_locks` allows one owner per scanner id. Lock acquisition is
transactional. Locks expire after a bounded TTL so a crashed worker does not
block future scans indefinitely. Repeated signals use deterministic keys and
database uniqueness, so a retry cannot open the same opportunity/trade twice.

## Health interpretation

- `CURRENT`: latest successful scan is within the freshness window.
- `STALE`: latest success is older than the window.
- `ERROR`: an error occurred after the latest success.
- `NEVER RUN`: no successful heartbeat exists.
- market data `AVAILABLE`, `PARTIAL`, or `UNAVAILABLE` is stored separately.

## Diagnostics

Logs contain symbol and exception type, not tokens or provider payloads.
Useful checks:

```sql
SELECT * FROM scanner_health;
SELECT state, count(*) FROM opportunities GROUP BY state;
SELECT status, count(*) FROM authoritative_trades GROUP BY status;
```

## Failure recovery

1. Read the scanner-health message and worker logs.
2. Confirm database/provider credentials in the scheduler environment.
3. Confirm the prior lock has expired or that no worker is still active.
4. Run one `scan_once`.
5. Verify `last_success_at`, symbol count, and market-data state.

Do not delete locks or trade records as a routine retry mechanism.
