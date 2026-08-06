# Full authoritative-entry regression audit

Audit date: 2026-08-06

## Baseline and scope

The last mainline revision immediately before MIRROR was `0fda67e` (PR #46,
scanner-latency instrumentation). This is the defensible last-known-good
pre-MIRROR baseline supplied by repository history. Current main at the audit was
`e5c5912` (PR #50).

The chronological range is:

1. `9abaf2a` / `76391c7`: MIRROR repository, projection, execution, and post-PAPER worker handoff.
2. `a115bed` / `d602e4e`: read-only Trade Desk MIRROR comparison.
3. `72ed387` / `79086e5`: additive authoritative funnel persistence and UI.
4. `5c8144f` / `e5c5912`: unconditional, failure-isolated funnel finalization.

`git diff 0fda67e..e5c5912` proves no change to `trade_state_service.py`,
`signal_history.py`, `trade_repository.py`, `option_trade_engine.py`,
`optionbeacon_live.py`, `optionbeacon/worker/run.py`, session helpers, strategy
scoring, or trade planning. Changed files classify as UI-only (app, Trade Desk,
theme, PAPER page), persistence/diagnostics-only (funnel), execution-only after
authoritative lifecycle (MIRROR), documentation, and tests. `scan_once.py` is the
only shared orchestrator changed: it collects result references for the funnel and
runs MIRROR after authoritative processing and the BROAD handoff.

## Baseline and current state machine

The baseline and current authoritative state machines are identical:

1. `optionbeacon.worker.run.main()` constructs the durable repository and enters
   `run()`; `run()` calls the imported `run_scan_once()`.
2. `run_scan_once()` acquires `ScannerLockLease`, loads the universe, starts the
   market-data cycle, and calls `optionbeacon_live.generate_signal()` serially.
3. `generate_signal()` downloads 5-minute bars, calculates indicators, calls
   `optionbeacon_strategy.score_candle()`, then `enrich_with_trade_plan()`.
4. For every non-null result with a positive price, `run_scan_once()` calls
   `trade_state_service.process_scanner_result()` before any funnel, BROAD, or
   MIRROR code.
5. `process_scanner_result()` loads all durable outcomes, selects open records for
   the symbol, applies EOD/expiration, checks the session, and calls
   `signal_history.update_trade_outcome()` with the current result price.
6. `update_trade_outcome()` compares bullish `price >= persisted entry` and bearish
   `price <= persisted entry`; `entry_confidence_eligible()` requires finite
   persisted confidence at least 65. On success it sets `entry_time`.
7. `sync_trade_outcome()` independently commits the opportunity/trade projection;
   `persist_outcome_transition()` independently inserts the deduplicated
   `TRADE_ENTERED` event.
8. Only after existing outcomes are evaluated does `scanner_result_to_trade_outcome()`
   create a missing candidate for the current result.
9. Current main then finalizes the failure-isolated funnel, projects durable entry
   events to BROAD, executes BROAD, projects them separately to MIRROR, and executes
   MIRROR.

## Candidate identity and lifecycle findings

Candidate identity hashes symbol, direction, setup, persisted trigger, and a
five-minute result-timestamp bucket. Identical results inside a bucket reuse one
candidate. A later bucket or changed trigger can create a new candidate, but does
not overwrite or hide old candidates: `list_trade_outcomes()` still returns them,
and every open matching record is evaluated before current candidate creation.
The regression tests prove an older candidate enters using its persisted trigger
even when the current result carries a different trigger.

The deliberate one-cycle delay is therefore real but finite. Candidates expire
after 60 minutes; entered trades have a 120-minute maximum hold. Candidate
confidence is copied from `result["confidence"]`, persisted in both the outcome
payload and opportunity, and restored without substituting PAPER score fields.

## Entry gates and time behavior

Scanner scoring is allowed from 09:45 through 14:59 based on Eastern 5-minute
candle time. A score of 90 selects the visible `BULLISH SETUP` or `BEARISH SETUP`
label, but directional WATCHLIST results may still form authoritative candidates.
The authoritative entry gate is the persisted trigger, finite confidence >=65,
and an NYSE regular session before the configured 15:55 ET cutoff. Calendar logic
uses `America/New_York` and `pandas_market_calendars`, including DST, holidays, and
early closes. Naive stored timestamps are treated as UTC consistently. These
modules are unchanged from the pre-MIRROR baseline.

Configured strategy constants remain: CALL/PUT display threshold 90, volume
multiplier 1.40, bullish breakout multiplier 1.0003, bearish breakdown multiplier
0.9997, and authoritative candidate age 60 minutes. No audit change alters them.

## MIRROR, BROAD, transactions, and provider failures

MIRROR reads durable entry/exit events and writes only `mirror_execution_*` tables.
It copies candidate dictionaries, materializes candidate iterables, uses separate
disposition IDs, and neither updates authoritative opportunities nor marks their
events consumed. BROAD likewise checks dispositions only in `paper_execution_*`
tables. The two disposition sets cannot suppress authoritative lifecycle rows.

Every repository operation opens its own connection and commits on context exit.
Authoritative opportunity, trade, and event writes complete before funnel/BROAD/
MIRROR connections are opened. A later consumer exception cannot roll back an
already committed authoritative transition. No shared cursor, widened transaction,
or cross-ledger rollback was found.

Yahoo 429 handling retries the affected symbol three times with backoff. A recovered
429 remains listed in the warning summary but still returns a complete result. An
exhausted 429 makes only that symbol's `generate_signal()` fail: it produces no
current price, candidate, or lifecycle evaluation for that symbol in that cycle.
Other symbols continue. Open authoritative positions are included in the universe,
but candidates that have not entered are not added separately; therefore a symbol
absent from the configured/dynamic universe or repeatedly failing all provider
attempts cannot advance in that cycle. This behavior also predates MIRROR.

## Conclusion

No authoritative behavior regression exists between the pre-MIRROR baseline and
current main. Deterministic tests cover bullish, bearish, below-confidence,
waiting-trigger, expired, changed-current-trigger, same-bucket reuse, new-bucket
identity, and a worker cycle with both BROAD and MIRROR enabled. Exactly the
expected two entries occur in the multi-symbol replay, and exactly one entry occurs
before both consumers in the two-cycle worker replay.

The workspace has no production `DATABASE_URL` or provider credentials, and the
public production dashboard URL is not stored in the repository. Consequently this
audit cannot truthfully assign today's symbols to a specific runtime blocker from
local evidence. Given the unchanged state machine and passing replay, today's zero
is not attributable to the MIRROR/PAPER/Trade Desk/funnel code range. Its exact
measurable explanation must be read from the first repaired production funnel
snapshot: directional count, trigger count, confidence blockers, entry-window
blockers, and per-symbol provider failures. Earlier missing per-cycle snapshots
cannot be reconstructed without inventing state.

Git bisect was not used because every authoritative module is identical at both
endpoints and the end-to-end current-main behavior passes; there is no differing
authoritative implementation in the range for bisect to isolate.
