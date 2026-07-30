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

## Railway worker deployment

1. Create a Railway project.
2. Deploy from the Option-Beacon GitHub repository.
3. Select the production branch only after the persistence change is approved
   and merged.
4. Use the repository `railway.toml`, whose start command is:

   ```bash
   python -m optionbeacon.worker.run
   ```

5. Add Railway Variables:
   - `DATABASE_URL`
   - `OPTIONBEACON_REQUIRE_DURABLE_STORAGE=true`
   - `OPTIONBEACON_ENVIRONMENT=production`
   - `OPTIONBEACON_SCAN_SECONDS=300` (or another validated 30-3600 value)
   - `OPTIONBEACON_SCANNER_ID=optionbeacon-production`
   - `FINNHUB_API_KEY`
   - `TRADIER_ACCESS_TOKEN`
6. Omit public networking. The worker opens no HTTP port.
7. Verify the sanitized `worker_start` record shows the expected application
   version, PostgreSQL backend, interval, symbol count, environment, and
   scanner id.
8. Run `python -m optionbeacon.worker.healthcheck` as a one-off command and
   verify heartbeat freshness.
9. Compare consecutive `scan_complete` log timestamps with the configured
   cadence.
10. Railway restart/redeploy sends SIGTERM; the worker stops through its
    interruptible wait and the repository scan lock expires if termination
    occurs mid-scan.
11. Roll back by selecting the prior deployment and stopping the incompatible
    worker first. Do not delete PostgreSQL data.
12. Stop the worker through Railway's service controls. For one diagnostic
    scan, run:

    ```bash
    python -m optionbeacon.worker.scan_once
    ```

Resource use is expected to be modest between scans, with short CPU/network
bursts during each universe pass and persistent low-memory Python/database
state. Actual usage and cost depend on symbol count, provider latency, scan
cadence, Railway plan, and Neon plan; no fixed price is assumed.

## Continuous process

For a process manager that supports long-running jobs:

```bash
python -m optionbeacon.worker.run --interval-seconds 300
```

Prefer a platform scheduler invoking `scan_once` every five minutes. The worker
loop is not started by Streamlit. For Railway, use the persistent worker
command rather than a GitHub Actions cron because the required cadence is
faster than GitHub Actions scheduled workflows support.

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

Health command:

```bash
python -m optionbeacon.worker.healthcheck
```

Exit codes:

- `0`: database/schema reachable and heartbeat current;
- `1`: reachable but degraded, stale, errored, or never successfully scanned;
- `2`: configuration or storage unavailable.

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
