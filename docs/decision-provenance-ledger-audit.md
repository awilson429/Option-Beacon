# Decision-provenance ledger pre-implementation audit

## Scope and invariant

This audit traces the merged production SPY/QQQ path on `main` at `6861bf6` before provenance runtime changes. The provenance layer must be additive and observational. It must not change scores, thresholds, setup qualification, entry/exit behavior, capital decisions, sizing, management, providers, or worker cadence.

The required durable chain is:

`scan_cycle_id → observation_id → existing opportunity_id → existing capital decision_id + lane → exact lane trade/position ID → existing management snapshot IDs → existing outcome`

Existing canonical IDs remain authoritative. Symbol and timestamp proximity are never valid downstream joins.

## Production entry points and cycle

- `optionbeacon.worker.run` is the recurring Railway worker. It increments `run_number` and invokes `optionbeacon.worker.scan_once.run_scan_once` on the configured cadence (default 300 seconds).
- `run_scan_once` owns the durable scanner lock, starts/finalizes `scanner_health`, loads the universe, evaluates symbols serially, persists authoritative lifecycle changes, writes the legacy snapshot, runs the entry funnel, executes PAPER/capital handoff, then runs isolated MIRROR/control experiments.
- `optionbeacon_live.generate_signal` is the per-symbol decision pipeline used by the worker. It loads bars, computes existing indicators, calls `optionbeacon_strategy.score_candle`, enriches the existing trade plan and option liquidity, timestamps the result, and writes legacy/local research artifacts.
- `scheduled_scan` and the `optionbeacon_live` CLI loop are legacy/non-production entry points. They do not own the canonical Railway cycle identity.
- SPY and QQQ are the first core ETF symbols but traverse the same serial universe path as other symbols. The provenance scope in this task is deliberately bounded to those two symbols.

## Stage-by-stage authority map

| Stage | Inputs | Output / existing identity | Timestamp | Persistence before this task | Decision/rejection evidence | Authority |
| --- | --- | --- | --- | --- | --- | --- |
| Cycle acquisition | scanner ID, run number, lock owner, code version | scanner health current-run tuple; no immutable cycle ID | worker `started` | latest mutable `scanner_health`; funnel cycle separately persists diagnostics | lock contention and cycle failures logged | Authoritative operational state, but not an immutable decision cycle |
| Market data | symbol, provider configuration, 5-minute bars | DataFrame or no result/exception | provider/candle time | provider summary logged; aggregate health finalized | provider/rate-limit failures logged, not joined to a symbol observation | Authoritative input for that process; transient |
| Indicators | bars | EMA9/21/20/50/200, MACD/signal/histogram, RSI, VWAP, volume averages, ATR | candle index | only selected result values survive in legacy/display artifacts or eligible snapshots | empty/insufficient history returns `None` without canonical reason | Authoritative calculation; transient for non-eligible scans |
| Scoring | indicator frame and existing constants | bullish/bearish score, category scores, confidence, bias, signal, reasons | candle time | eligible context may be persisted later; WATCHLIST is not canonical | actual reasons exist in result; threshold is 90/90 by existing defaults | Authoritative strategy output |
| Trade-plan qualification | score result | setup stage, timing state, plan, trigger/stop/targets, next-action explanation | result time | persisted only when an opportunity is created; local artifacts otherwise | missing plan, non-directional, invalid/extended, or missing entry returns no `TradeOutcome` | Authoritative eligibility conversion |
| Candidate/opportunity | eligible result | deterministic `TradeOutcome.trade_id`, reused as `opportunities.id` | signal/candle timestamp | `opportunities`, intelligence snapshot, opportunity context | non-eligible scans disappear from canonical DB | Canonical opportunity |
| Authoritative lifecycle | current result + open `TradeOutcome` records | `authoritative_trades.id` and lifecycle events | worker lifecycle timestamp | durable opportunity/trade/event tables | entry/exit reason is durable | Canonical OB lifecycle |
| Option/PAPER handoff | authoritative `TRADE_ENTERED`, result, option quote, existing filters | paper trade/position IDs | checked time | paper execution tables and journal | every legacy execution rejection is journaled | Canonical simulated execution domain |
| Capital decisions | exact opportunity, candidate contract, lane state/config | SHA-256 `capital_decisions.decision_id`, separately for OB/BROAD | decision timestamp | every TAKE and rejection is durable | structured reason code and explanation | Canonical lane allocation decision |
| Lane position | accepted decision + paper position | `capital_positions.position_id = lane + ':' + paper trade ID` | paper entry/mark/close times | durable position with exact lane, source trade, opportunity | accepted decision was joinable by `(lane, opportunity)` but decision ID was not stored on position | Canonical simulated capital position |
| Management | lane position synchronization / intraday evaluation | `trade_management_snapshots.snapshot_id` | captured/source timestamps | append-only material state, exact `(trade_id, lane)` | nullable management fields remain explicit | Canonical when the evaluation exists |
| Outcome | authoritative close and/or closed capital position | closed trade/position plus lifecycle event | exit/close time | durable reason, fill/result where available | exact opportunity/trade/lane is available | Canonical outcome |

## Where decisions currently disappear

1. `generate_signal` returns `None` for empty market data or fewer than 30 post-indicator rows; the worker records neither a canonical SPY/QQQ observation nor a structured per-symbol disposition.
2. Provider exceptions increment cycle failures and are logged, but no exact observation row explains that SPY/QQQ could not be evaluated.
3. `score_candle` returns `MARKET CLOSED / WAIT` outside the strategy session. This result remains transient unless a legacy artifact happens to retain it.
4. WATCHLIST results retain component scores, indicators, and reasons in memory but `scanner_result_to_trade_outcome` returns no candidate, so no opportunity exists.
5. Directional results can disappear because the trade plan is absent, direction is not Bullish/Bearish, timing/stage is invalid or extended, or no usable entry reference exists. The return path is currently `None` without a structured canonical reason.
6. Opportunity creation is deterministic and exact, but it does not store the observation that caused it because no canonical observation exists.
7. Capital decisions already preserve TAKE and rejection, but accepted positions do not retain the exact `decision_id`; later code reconstructs acceptance with `(lane, opportunity_id)` and recency.
8. Management and outcomes are exact once a lane position exists. The missing work is composition, not a second management system.

## Proposed normalized design

### `provenance_scan_cycles`

One lightweight immutable/updatable record for each production cycle identity. The deterministic ID includes scanner ID, run number, and started timestamp so restarts and repeated numbers cannot collide. It records start/completion, session state, worker/source version, provider/data state, evaluated SPY/QQQ symbols, cycle status, freshness, and provenance degradation.

### `provenance_observations`

One bounded row per evaluated SPY/QQQ symbol per cycle, including failures/no-result states. The deterministic ID includes cycle ID, symbol, and observation/data timestamp. Normal columns hold identity, price, direction, score/confidence, setup/qualification/disposition, freshness, and exact opportunity link. Bounded JSON holds only the existing component scores, decision-consumed indicators, and authoritative reason set. It does not archive bars or provider responses.

### `provenance_decision_trade_links`

One row per existing capital `decision_id`, with exact opportunity, lane, decision state, and nullable exact lane position/trade ID. Rejections are recorded as `NO_TRADE`; accepted decisions begin as decided/pending and are updated only at the exact capital-position upsert boundary. OB and BROAD rows can never collide because their existing decision IDs and lanes remain distinct.

Existing `opportunities`, `capital_decisions`, `capital_positions`, `trade_management_snapshots`, and closed outcomes remain the system of record. Read models compose them; provenance tables do not duplicate them.

## Qualification terminology

The observability classifier must expose the existing conversion result without changing it:

- `QUALIFIED`: `scanner_result_to_trade_outcome` produced the existing deterministic candidate.
- `SESSION_BLOCKED`: existing signal is `MARKET CLOSED / WAIT`.
- `NO_SETUP`: existing WATCHLIST/non-directional result did not produce a plan/candidate.
- `REJECTED`: existing plan/timing/stage/entry checks rejected a directional candidate, with the actual structured reason.
- `DATA_UNSAFE`: provider failure, no result, invalid price, or insufficient decision result.
- `STALE_DATA`: only when the existing timestamp/freshness evidence demonstrates staleness.

No `INSUFFICIENT_SCORE` label should be inferred solely because a WATCHLIST score is below current thresholds; `WATCHLIST` is the authoritative strategy output and the component scores remain available for analysis.

## Failure boundary

Every provenance write must be caught after or around the existing authoritative operation. Failure must log a structured, secret-safe event and mark the cycle provenance state degraded when the cycle row remains writable. No provenance exception may change the return value of candidate conversion, `process_scanner_result`, a capital decision, position creation, management, or execution.

## Expected volume and retention

At the current 5-minute cadence, a 6.5-hour regular session has about 78 cycles. Bounded to SPY and QQQ:

| Period | Cycle rows | Observation rows (maximum normal session) |
| --- | ---: | ---: |
| Trading day | 78 | 156 |
| 21-session month | 1,638 | 3,276 |
| 252-session year | 19,656 | 39,312 |

Retries/restarts can add a small number of rows because cycle identity includes the exact start. This volume is modest for normalized PostgreSQL rows. Retain cycle/observation/decision links for at least the same horizon as opportunities and outcomes; otherwise the causal chain breaks. Do not add destructive automated retention in this task. If future cadence or symbol scope expands, preserve all qualified/rejected/failure transitions and consider compacting repetitive `NO_SETUP` observations only after a measured retention review.

## MIRROR and legacy treatment

- OB and BROAD are the only deployable capital lanes in this ledger.
- MIRROR/control remains in its existing research tables and is never inferred into OB/BROAD provenance. Any future research capture must use an explicit research role and separate metrics.
- Existing opportunities/trades have no trustworthy originating observation. No symbol/time backfill is permitted. Read endpoints must return explicit unavailable provenance for legacy records.
