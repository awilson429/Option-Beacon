# PAPER Execution Architecture

## Ownership

Railway is the only scheduled production runtime. Its persistent worker acquires the existing scanner lock, advances the scanner, refreshes PAPER option positions, processes exits, evaluates new contracts and risk gates, and writes the resulting state before releasing the lock. The default cadence remains 300 seconds and is configurable with `OPTIONBEACON_SCAN_SECONDS`.

Neon PostgreSQL is the authoritative PAPER store in production. Streamlit reads this state and never refreshes quotes, opens positions, closes positions, or writes lifecycle records. The GitHub Actions scanner is manual-only and does not execute or persist PAPER lifecycle state.

## Durable schema

The repository creates four additive tables with `CREATE TABLE IF NOT EXISTS`:

- `paper_execution_positions` holds restartable current and completed position state, exposure, current valuation, MFE/MAE, timestamps, thresholds, and a version-tolerant metadata projection.
- `paper_execution_trades` deduplicates contract captures by source signal and becomes immutable closed-trade history after the idempotent close transition.
- `paper_execution_journal` holds accepted and rejected decisions, reason codes, risk snapshots, allocations, scanner identity, run number, and timestamps.
- `paper_execution_runtime_state` holds each Railway scanner's latest resolved non-secret profile and effective configuration for read-only consumers.

No existing tables or columns are removed.

## Worker cycle and restart behavior

The worker lock is the single-writer guarantee across Railway replicas. A lock conflict skips the entire scan and PAPER cycle. Once locked, a normal cycle loads open positions from PostgreSQL, refreshes option quotes, persists exits, and advances the authoritative trade lifecycle. PAPER then reads durable `TRADE_ENTERED` events that do not yet have a PAPER disposition. It does not recreate scanner qualification. Each candidate retains the authoritative opportunity ID, captures a contract, evaluates the unchanged execution/risk gates, and persists either an accepted position or a rejected decision. Candidate failures are isolated; repository failures fail the cycle so the worker backoff and database reconnect behavior apply.

On restart, pending authoritative entries, open positions, MFE/MAE, daily realized losses, consecutive losses, and cooldown time are derived from PostgreSQL. Unique authoritative source-signal keys, journal dispositions, and conditional close updates prevent duplicate entries and exits. Multiple rapid entry events remain separate even when they share a symbol.

The structured `paper_authoritative_handoff` event reports authoritative entries generated in the cycle, pending PAPER candidates, and compact source IDs. `paper_cycle_completed` reports candidates received, evaluated, rejected, accepted, opened, and total open positions. Individual rejections continue to emit `paper_entry_rejected` with the reason code; full market payloads are never logged.

After `paper_positions_refreshed`, `paper_handoff_waiting_for_scan` marks that PAPER is healthy but waiting for the serial universe scan. `scanner_universe_ready` reports its bounded symbol count and `scanner_progress` reports every ten attempts. Per-symbol HTTP 429 failures are counted and skipped; they do not bypass PAPER. If universe loading, authoritative-open loading, provider finalization, or snapshot writing fails, `scanner_phase_failed` names the stage and PAPER still runs from durable Neon entries. A pending-entry query or execution failure emits `paper_cycle_failed` with its stage before the scan returns a failure code.

A durable `TRADE_ENTERED` event with missing or malformed authoritative metadata is never skipped. The pending query fails explicitly with `AuthoritativeEntryProjectionError`, leaves the entry pending for repair/retry, and produces `paper_cycle_failed` rather than inventing contract inputs.

An undispositioned entry recovered within 60 minutes remains eligible for normal evaluation after a worker restart. Older backlog is audited as `STALE_AUTHORITATIVE_ENTRY` and cannot open a new position. Candidate-ID diagnostics are capped at 20 IDs per cycle and include a truncated count.

If Tradier cannot supply a valid quote, the existing position object is retained unchanged and retried next cycle. No price or fill is invented. Entry fills are deterministic estimates between midpoint and ask only after a valid contract snapshot exists.

## Risk and execution modes

New entries require both:

- `OPTIONBEACON_EXECUTION_MODE=PAPER`
- `OPTIONBEACON_TRADING_ENABLED=true`

Trading is disabled by default. `CONFIRM`, `AUTO`, `LIVE`, and every other unsupported mode are rejected. There is no live brokerage adapter or order-placement path.

The existing score, Eastern entry window, allocation, concurrent-position, daily-trade, daily-loss, consecutive-loss, cooldown, duplicate, liquidity, contract-validity, expiration, stop, target, max-hold, and EOD rules remain in force. Daily state uses `America/New_York`, including DST-aware timestamps.

## PAPER simulation profiles

`PAPER_SIMULATION_PROFILE` is explicit and accepts `SAFE` or `BROAD`. The default remains `SAFE`. Both profiles require `OPTIONBEACON_EXECUTION_MODE=PAPER`; neither introduces a brokerage-order path.

The approved `BROAD` data-collection profile uses a minimum PAPER participation score of 40, five simultaneous positions, twenty entries per day, $250 maximum per position, $1,250 maximum aggregate deployed capital, a $5,000 starting balance, and a $100 daily realized-loss limit. Consecutive-loss and loss-cooldown gates are disabled only for BROAD. The 9:45 AM–3:00 PM ET entry window, 60-minute authoritative-entry age, 20% spread, 50 open-interest minimum, valid quote/contract requirements, -30% stop, +50% target, 120-minute maximum hold, EOD close, and durable duplicate protection remain unchanged.

Railway configuration for the profile is:

```text
PAPER_SIMULATION_PROFILE=BROAD
OPTIONBEACON_EXECUTION_MODE=PAPER
OPTIONBEACON_TRADING_ENABLED=true
OPTIONBEACON_PAPER_ACCOUNT_SIZE=5000
OPTIONBEACON_MIN_BEACON_SCORE=40
OPTIONBEACON_MAX_OPEN_POSITIONS=5
OPTIONBEACON_MAX_TRADES_PER_DAY=20
OPTIONBEACON_MAX_DOLLARS_PER_TRADE=250
OPTIONBEACON_MAX_TOTAL_DEPLOYED_CAPITAL=1250
OPTIONBEACON_MAX_DAILY_LOSS_DOLLARS=100
OPTIONBEACON_MAX_CONSECUTIVE_LOSSES=0
OPTIONBEACON_LOSS_COOLDOWN_MINUTES=0
```

The last nine values are explicit deployment assertions; BROAD supplies the same defaults when they are absent. Existing conflicting overrides must be changed or removed. No reset or deletion is performed when profiles change.

Profile parsing trims surrounding whitespace and uppercases the value. Only `SAFE` and `BROAD` are accepted. The selected profile supplies defaults; explicitly configured per-setting variables take precedence. At the start of each PAPER cycle Railway emits `paper_execution_config_resolved` and upserts the complete resolved non-secret configuration into `paper_execution_runtime_state` before refreshing positions.

Streamlit never derives the displayed worker profile from its own environment. It reads the latest runtime-state row from Neon and reconstructs display-only limits from `resolved_config_json`. Until Railway has persisted a row, the page displays `AWAITING WORKER STATE` rather than a local profile default.

Future entry-decision journal metadata records `simulation_profile`, `effective_min_score`, and `journal_type=ENTRY_DECISION`. Today's funnel groups decisions by this stamped profile. Pre-stamping historical rows remain `LEGACY_UNLABELED`; they are not relabeled as BROAD. Position-refresh failures use a distinct journal type and are excluded from entry-disposition counts.

Execution decisions distinguish `SPREAD_TOO_WIDE`, `INSUFFICIENT_OPEN_INTEREST`, `INSUFFICIENT_VOLUME`, `INSUFFICIENT_BUYING_POWER`, `NO_VALID_CONTRACT`, and `CONTRACT_QUOTE_UNAVAILABLE`. The Paper Trading page reconciles today's authoritative entries to evaluated, opened, rejected, and pending dispositions and derives account equity, realized/unrealized/total P&L, return, profit factor, intraday drawdown, and peak deployment from durable history.

## Legacy migration

Legacy JSON files are import-only backup artifacts:

```text
python -m optionbeacon.migrations.paper_execution_to_postgres --dry-run
python -m optionbeacon.migrations.paper_execution_to_postgres
```

The command reads `paper_option_trades.jsonl`, `paper_option_positions.json`, and `paper_execution_journal.jsonl`. It preserves timestamps and values, skips malformed rows, uses durable signal/trade/deduplication keys, and reports found, imported, skipped, duplicate, malformed, and final SQL counts. Run the dry-run in a staging environment first. Automated tests use SQLite and mocked providers; production credentials are not required.

## Deployment verification

1. Back up the legacy files and Neon database.
2. Deploy the additive schema code with PAPER entries disabled.
3. Run the migration dry-run and reconcile counts.
4. Run the migration once, then rerun it to verify only duplicates are reported.
5. Confirm the Railway worker logs `paper_state_restored`, `paper_authoritative_handoff`, and `paper_cycle_completed`.
6. Confirm GitHub Actions has no scheduled trigger.
7. Confirm Streamlit shows the SQL-backed positions, history, metrics, and journal.
8. Set `OPTIONBEACON_EXECUTION_MODE=PAPER` and `OPTIONBEACON_TRADING_ENABLED=true` only after verification.
9. For one authoritative `TRADE_ENTERED`, confirm the same opportunity ID appears in `paper_authoritative_handoff` and that exactly one `paper_entry_opened` or `paper_entry_rejected` follows.
10. Verify `paper_cycle_completed` candidate counts reconcile and the read-only Paper Trading page reports `ENABLED — WORKER ACTIVE`, even in a zero-candidate cycle.
11. Monitor entry rejections, quote failures, database health, and scanner-lock conflicts for the first session.

Recovery consists of disabling `OPTIONBEACON_TRADING_ENABLED`, leaving Railway running so existing positions remain managed, correcting the provider or database issue, and allowing the next locked cycle to resume from PostgreSQL.

## Scanner lock operations

`scanner_locks` is a durable PostgreSQL lease table, not a session-level advisory lock. A row is keyed by `scanner_id`, contains its owner identity and UTC acquisition/expiration timestamps, and is deleted only by the matching owner. It therefore survives a crashed process, lost database connection, or Railway deployment until its lease expires. Connection pooling cannot retain it because ownership is data rather than connection state.

Acquisition is an atomic PostgreSQL `INSERT ... ON CONFLICT ... DO UPDATE` that succeeds only when no lease exists or the existing lease has expired. No active lease is displaced, including by a repeated acquisition from the same identity. Railway owner identities include scanner, deployment, replica, process, and a random process-start suffix.

The active scan renews its 120-second lease every 30 seconds through an atomic exact-owner update. Renewal cannot resurrect an expired lease, and an old owner cannot renew or release a replacement owner's lease. The lock is released in the scan's `finally` block after successful scans, provider failures, PAPER failures, and ordinary exceptions; the renewal thread is stopped before release. A hard-killed process stops renewing and a replacement can take over after at most the remaining lease duration. If Neon is unavailable during release, the same expiry recovery applies. Railway control-plane status such as `REMOVED` is not itself proof that a process has stopped; persisted owner and lease timestamps are authoritative. Structured events expose attempts, acquisition, contention, expiry, takeover, renewal, rejection, release, and release failure without credentials.
