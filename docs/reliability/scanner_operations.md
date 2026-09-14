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
   - `OPTIONBEACON_DB_CONNECT_TIMEOUT_SECONDS=10` (optional, valid range 1-60)
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

- `CURRENT`: latest successful **completed** cycle is within the 15-minute
  freshness window (`DEFAULT_STALE_MINUTES`).
- `SCANNING`: the worker holds a live lock and has recent progress. This is
  worker liveness, not a completed-cycle heartbeat. After 15 minutes the last
  completed snapshot is `refreshing`, not `fresh` and not `stale`.
- `STALE`: latest success is older than the window **and** the worker is not
  actively progressing.
- `ERROR`: an error occurred after the latest success.
- `NEVER RUN` / `WAITING`: no successful heartbeat exists.
- market data `AVAILABLE`, `PARTIAL`, or `UNAVAILABLE` is stored separately.

`last_success_at` advances only when a whole cycle finalizes successfully.
Lock renewals, `scanner_progress`, and `scanner_symbol_timing` never update it.
A healthy sequential 69-symbol cycle can take ~17 minutes, so the 15-minute
window can expire **during** the next scan; that condition is `refreshing`.

Health command:

```bash
python -m optionbeacon.worker.healthcheck
```

Exit codes:

- `0`: database/schema reachable and heartbeat current, **or** the worker is
  actively scanning with a live lock and fresh progress;
- `1`: reachable but degraded, stale, errored, or never successfully scanned;
- `2`: configuration or storage unavailable.

## Diagnostics

Logs contain symbol and exception type, not tokens or provider payloads.
`scanner_symbol_timing` with `success=true` is one symbol, not a completed cycle.
Whole-cycle persistence is `scanner_health.last_success_at` via `finish_scan_run`.
Search Railway logs for `scanner_cycle_started`, `scanner_stage_started`,
`scanner_stage_completed`, `scanner_stage_failed`, `scanner_progress`,
`scanner_symbol_timing`, `scanner_universe_ready`,
`authoritative_entry_funnel_started`, `paper_cycle_started`,
`mirror_cycle_started`, `scanner_cycle_finalizing`,
`scanner_cycle_persisted`, `scanner_cycle_completed`, `scanner_cycle_failed`,
and `scanner_cycle_skipped`. `scanner_cycle_skipped` with
`reason="lock_unavailable"` means `run_scan_once` returned exit code 2 before
the authoritative cycle started because another owner holds the unexpired
`scanner_locks` row. There is no `scan_completed` or `scan_failed` event.
`scan_complete` (no `d`) is emitted by `optionbeacon.worker.run` after
`run_scan_once` returns, including lock contention. `scanner_lock_renewed`
means the lease is alive, not that the cycle finished.
Stage names on `scanner_stage_*` are `paper_pre_scan`, `universe_loading`,
`symbol_scan`, `authoritative_entry_funnel`, `paper_execution`,
`mirror_execution`, and `finalization`. The symbol loop is sequential and has
no whole-cycle timeout; `FULL_SCAN_SLOW` only warns after the run ends when
duration exceeds 5 minutes. A 74-symbol cycle at 10–17 seconds per symbol can
legitimately take 12–21+ minutes before `scanner_cycle_finalizing`.
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
