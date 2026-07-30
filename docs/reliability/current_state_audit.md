# OptionBeacon Current-State Reliability Audit

## Scope and conclusion

This audit traces the application as of commit
`4071a0771cb5c0846c85c78bead06dbe3e9ca9ca`.

OptionBeacon does not currently have one authoritative trade state. It has
several independent stores:

- `signal_history.jsonl` for scanner-derived `TradeOutcome` candidates,
  entries, and exits;
- `optionbeacon_trades.db` or `DATABASE_URL` for manually entered positions and
  coaching recommendations;
- `paper_option_trades.jsonl` for immutable option contract captures;
- `paper_option_positions.json` for paper option lifecycle;
- `trade_plan_journal.jsonl` for schema-versioned trade plans;
- multiple CSV alert, score, outcome, and journal files;
- `latest_results.json` for a scanner snapshot.

Today's Scorecard and Opened Alerts both derive from `signal_history.jsonl`,
which is internally consistent within one filesystem. The former develop and
main deployments had different ephemeral filesystems and independently ran
scans during page execution. They could therefore naturally show different
trade histories. A Streamlit Community Cloud redeploy or container replacement
can remove local runtime files. The current `DATABASE_URL` support applies to
manual positions/recommendations only, not Scorecard/Open Alerts.

## End-to-end data flow

### 1. Scanner execution

`app.py:main()` executes on every Streamlit script run. Before routing the
selected workspace, it calls `scan_symbols()`.

`scan_symbols()`:

1. checks market-open state;
2. calls `load_latest_results()`;
3. uses a fresh local or remote snapshot when available;
4. otherwise iterates the current universe and calls
   `cached_generate_signal(symbol)`;
5. records qualifying high-score snapshots in CSV;
6. returns in-memory results to the UI.

The scanner therefore runs during Streamlit page execution whenever no fresh
snapshot is available. It is not solely a background service.

### 2. Triggers and caching

Streamlit reruns are triggered by initial load, refresh, navigation buttons,
filters, and other widget interactions. `cached_generate_signal` uses
`st.cache_data(ttl=60)`, so reruns within the TTL reuse a result in that
process. Current quote helpers also use 60-second caches; after-hours and other
data use 15-minute caches.

These caches are performance aids, not durable state. They are process-local,
can disappear on restart, and do not coordinate separate deployments.

### 3. Signal creation

`optionbeacon_live.generate_signal(symbol)` downloads market data, calculates
the stable scanner result/trade plan, calls lifecycle updates for prior
outcomes, and calls `record_scanner_result(result)`.

The Streamlit path may also obtain results from `latest_results.json`, while
`scheduled_scan.py` directly calls `generate_signal` per symbol.

### 4. Candidate and alert creation

`signal_history.record_scanner_result` converts eligible directional scanner
results into `TradeOutcome` candidates and appends them to
`signal_history.jsonl`. Identity is deterministic and repeated scanner results
are checked against existing rows before append.

`app.py` then calls `capture_qualified_signals`, which independently writes
qualified option contract snapshots to `paper_option_trades.jsonl`.

The legacy guide-alert path writes `live_coach_alerts.csv`. High-score history
uses `high_score_history.csv`. `scheduled_scan.py` also writes
`signal_outcomes.csv` and `latest_results.json`.

### 5. Entry and open-trade state

There are three meanings of “open trade”:

1. A `TradeOutcome` in `signal_history.jsonl` with `entry_time` populated and
   `exit_time` absent. This drives Today's Scorecard and Opened Alerts.
2. A manual position in the SQL `positions` table with `status='OPEN'`. This
   drives the older active-trade/coaching UI.
3. A `PaperOptionPosition` in `paper_option_positions.json` with `status='OPEN'`.
   This drives option lifecycle sections.

The scanner-derived entry occurs when price crosses the planned entry and the
confidence gate passes. Candidate expiration, entered-trade expiration, stop,
and target processing rewrite `signal_history.jsonl`.

### 6. Closed-trade state

- Scanner-derived closed outcomes remain in `signal_history.jsonl`.
- Manual positions are updated to `CLOSED` in SQL.
- Paper option positions are updated in `paper_option_positions.json`.
- Legacy outcomes and journal records also exist in CSV files.

There is no cross-store transaction or common identity enforcing consistency.

### 7. Today's Scorecard

`main()` calls `load_trade_evidence_history()`, which calls
`load_trade_outcomes()`. Any exception is caught and converted to `[]` without
an error state.

`render_outcome_trade_journal()` filters those records and calls
`daily_scorecard(filtered_records, today)`. Opened Alerts are entered records
for the current day; closed, winner, loser, and return metrics use the same
filtered `TradeOutcome` list.

If the history loader returns no rows because the file is missing, ephemeral,
or unreadable, the UI renders an ordinary “no history” empty state.

### 8. Opened Alerts

The same `filtered_records` list used by the Scorecard is passed to
`opened_alerts_analytics`. This is consistent inside one render. It is not
durable across deployments because the source is a local JSONL file.

### 9. Scheduled scanner

`scheduled_scan.py` is a separate executable entry point. It:

- skips closed markets;
- scans the active universe;
- writes high-score and guide-alert CSVs;
- writes `latest_results.json`;
- updates legacy signal outcomes;
- runs coaching against SQL manual positions.

It has no cross-process scan lock, no durable scanner heartbeat, and no
database-backed idempotent opportunity transaction. A second process can run
concurrently.

## State and cache inventory

### `st.session_state`

Session state is used for:

- trade replay results/errors/labels;
- Developer Tools diagnostic button running flags;
- navigation state inside `ui_navigation.py`;
- UI filters and selected rows managed by Streamlit widgets.

It is not the direct persistence mechanism for Scorecard/Open Alerts, but it is
ephemeral and must remain presentation-only.

### `st.cache_data`

Used for:

- header image encoding;
- generated scanner signals (60 seconds);
- current open-trade quotes (60 seconds);
- after-hours briefing (15 minutes);
- option-chain/setup enrichment (15 minutes).

No `st.cache_resource` use was found. Cache invalidation is per process and
does not provide coordination or durability.

### Local files

Runtime files include:

- `signal_history.jsonl`
- `paper_option_trades.jsonl`
- `paper_option_positions.json`
- `trade_plan_journal.jsonl`
- `latest_results.json`
- `finnhub_movers_cache.json`
- `runtime_diagnostics.json`
- `high_score_history.csv`
- `live_coach_alerts.csv`
- `signal_outcomes.csv`
- `optionbeacon_live_signals.csv`
- `optionbeacon_trade_journal.csv`
- `optionbeacon_signal_log.csv`
- research shadow JSONLs and generated CSV/JSON reports.

Many are ignored appropriately, but ignored does not mean durable.

### SQL

`trade_storage.py` supports:

- PostgreSQL when `DATABASE_URL` is available;
- local SQLite `optionbeacon_trades.db` otherwise;
- `positions` and `recommendations` tables.

It initializes schemas in application calls. Timestamps are formatted Eastern
strings rather than timezone-aware UTC storage values. It has no opportunities
or scanner-health tables and no idempotency constraint for opening positions.

### Temporary directories

Temporary directories are used by diagnostic and verification utilities.
Atomic JSONL rewrites use same-directory temporary files. They do not provide
production persistence.

### Environment-dependent paths

Most runtime paths are relative to the process working directory. `DATABASE_URL`
may come from the environment or Streamlit Secrets. Snapshot reads may fall
back to a configured raw GitHub data URL. Separate deployments and working
directories therefore naturally see separate state.

## Concurrency and duplication

- `signal_history.jsonl` checks deterministic identity before append, but the
  read-then-append sequence is not protected by an inter-process lock. Two
  processes can both observe absence and append a duplicate.
- Atomic history rewrite prevents partial replacement, but concurrent writers
  can lose updates because each rewrites from its own loaded snapshot.
- `OptionTradeLedger.append_once` is also an unlocked read-then-append.
- `paper_option_positions.json` and `trade_plan_journal.jsonl` use local
  rewrites without database transactions or cross-process locks.
- SQL manual `create_position` has no signal idempotency key or unique
  constraint.
- Streamlit and `scheduled_scan.py` can process the same signal independently.

Application-level deterministic IDs reduce duplicates during ordinary
single-process reruns, but they do not guarantee exactly-once behavior across
processes.

## Failure visibility

The following paths can conceal uncertainty:

- `load_trade_evidence_history()` catches all exceptions and returns an empty
  list;
- `load_latest_results()` swallows local and remote snapshot exceptions and
  returns `(None, None)`;
- individual scanner failures become `DATA UNAVAILABLE` rows, but the Scorecard
  can still appear as an ordinary empty state;
- option-position refresh is failure-safe but does not provide one central
  storage-health status;
- local-database fallback can look healthy in hosted production even though it
  is not durable.

The top-level app does display uncaught scanner exceptions, but several
important read failures are converted to empty results earlier.

## Streamlit Community Cloud durability

The local application filesystem is not an authoritative durable production
store. Process restart, container replacement, redeployment, branch-specific
deployment, or filesystem recreation can remove or isolate runtime data.
SQLite on that filesystem has the same limitation.

Durable production state requires an external database through `DATABASE_URL`
or another explicitly durable service. Without it, production must declare a
degraded/read-only state rather than silently treating local data as complete.

## Root cause of the former develop/main discrepancy

The deployments were separate processes with separate local files, caches,
scan timing, code revisions, and possibly provider/request outcomes. Because
Scorecard/Open Alerts read local `signal_history.jsonl`, an open outcome created
in the development deployment was not expected to appear in main. The absence
was architectural, not necessarily a UI defect.

## Migration requirements

The repair must:

1. introduce one repository contract for opportunities, trades, and scanner
   health;
2. use PostgreSQL for durable production and SQLite only for local/tests;
3. use database uniqueness and transactions for idempotent signal processing;
4. add a separately runnable, locked scan worker;
5. make the dashboard read authoritative records and health state;
6. retain tolerant, explicit legacy import paths without automatic migration;
7. preserve stable scanner/trade calculations;
8. retain existing stores until migration is validated, without deleting data.
