# PAPER Execution Architecture

## Ownership

Railway is the only scheduled production runtime. Its persistent worker acquires the existing scanner lock, advances the scanner, refreshes PAPER option positions, processes exits, evaluates new contracts and risk gates, and writes the resulting state before releasing the lock. The default cadence remains 300 seconds and is configurable with `OPTIONBEACON_SCAN_SECONDS`.

Neon PostgreSQL is the authoritative PAPER store in production. Streamlit reads this state and never refreshes quotes, opens positions, closes positions, or writes lifecycle records. The GitHub Actions scanner is manual-only and does not execute or persist PAPER lifecycle state.

## Durable schema

The repository creates three additive tables with `CREATE TABLE IF NOT EXISTS`:

- `paper_execution_positions` holds restartable current and completed position state, exposure, current valuation, MFE/MAE, timestamps, thresholds, and a version-tolerant metadata projection.
- `paper_execution_trades` deduplicates contract captures by source signal and becomes immutable closed-trade history after the idempotent close transition.
- `paper_execution_journal` holds accepted and rejected decisions, reason codes, risk snapshots, allocations, scanner identity, run number, and timestamps.

No existing tables or columns are removed.

## Worker cycle and restart behavior

The worker lock is the single-writer guarantee across Railway replicas. A lock conflict skips the entire scan and PAPER cycle. Once locked, a normal cycle loads open positions from PostgreSQL, refreshes option quotes, persists exits, processes the scanned opportunities, captures contracts, evaluates risk, persists entries and journals decisions. Candidate failures are isolated; repository failures fail the cycle so the worker backoff and database reconnect behavior apply.

On restart, open positions, MFE/MAE, daily realized losses, consecutive losses, and cooldown time are derived from PostgreSQL. Unique trade/source-signal keys and conditional close updates prevent duplicate entries and exits.

If Tradier cannot supply a valid quote, the existing position object is retained unchanged and retried next cycle. No price or fill is invented. Entry fills are deterministic estimates between midpoint and ask only after a valid contract snapshot exists.

## Risk and execution modes

New entries require both:

- `OPTIONBEACON_EXECUTION_MODE=PAPER`
- `OPTIONBEACON_TRADING_ENABLED=true`

Trading is disabled by default. `CONFIRM`, `AUTO`, `LIVE`, and every other unsupported mode are rejected. There is no live brokerage adapter or order-placement path.

The existing score, Eastern entry window, allocation, concurrent-position, daily-trade, daily-loss, consecutive-loss, cooldown, duplicate, liquidity, contract-validity, expiration, stop, target, max-hold, and EOD rules remain in force. Daily state uses `America/New_York`, including DST-aware timestamps.

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
5. Confirm the Railway worker logs `paper_state_restored` and `paper_cycle_completed`.
6. Confirm GitHub Actions has no scheduled trigger.
7. Confirm Streamlit shows the SQL-backed positions, history, metrics, and journal.
8. Set `OPTIONBEACON_EXECUTION_MODE=PAPER` and `OPTIONBEACON_TRADING_ENABLED=true` only after verification.
9. Monitor entry rejections, quote failures, database health, and scanner-lock conflicts for the first session.

Recovery consists of disabling `OPTIONBEACON_TRADING_ENABLED`, leaving Railway running so existing positions remain managed, correcting the provider or database issue, and allowing the next locked cycle to resume from PostgreSQL.
