# Authoritative entry funnel

## Production state machine

The authoritative path is not the same as the dashboard's opportunity labels.
The worker calls `generate_signal(symbol)`, which downloads 5-minute data, computes
indicators, calls `optionbeacon_strategy.score_candle`, enriches the result with a
setup stage and trade plan, and returns it to the locked worker. The worker then
calls `trade_state_service.process_scanner_result`.

`process_scanner_result` first advances every existing, unclosed authoritative
candidate for that symbol. A candidate enters only when the current underlying
price is at/through its persisted trigger, its immutable entry confidence is at
least 65, and `intraday_entry_allowed` is true. It then projects the transition to
SQL, where `persist_outcome_transition` emits the durable `TRADE_ENTERED` event.
After existing candidates are evaluated, the current scanner result may create a
new deterministic candidate. Consequently, a newly created triggered candidate is
normally eligible for lifecycle evaluation on the next scan, not earlier in the
same symbol pass.

## Gates before `TRADE_ENTERED`

1. Market data must be non-empty and indicator output must contain at least 30 rows.
2. Scanner scoring runs only from 09:45 through 14:59 according to the candle index.
3. A direction requires bullish and bearish scores not to tie.
4. A production `BULLISH SETUP` or `BEARISH SETUP` label requires the corresponding
   score to be at least 90 and strictly dominate the other side. This is not itself
   the authoritative entry threshold: directional WATCHLIST results can create
   candidates too.
5. Trade-plan enrichment requires a Bullish/Bearish direction and a positive trigger.
6. Invalidated, failed, extended, and do-not-chase results are not projected into a
   new authoritative candidate.
7. Existing candidates expire untriggered after 60 minutes.
8. Actual entry requires the persisted price comparison (`price >= trigger` for
   Bullish, `price <= trigger` for Bearish), immutable candidate confidence >= 65,
   and an open authoritative entry session before the 15:55 ET cutoff.
9. The deterministic candidate identity includes symbol, direction, setup, trigger,
   and a 5-minute timestamp bucket. Repeated IDs are idempotent.

RSI, VWAP, EMA alignment, MACD, volume, ATR, and breakout evidence are additive
score contributions, not independent Boolean entry gates. Diagnostics therefore
do not falsely label them as direct rejection reasons. Their absence can explain a
score below 90; only immutable candidate confidence below 65 is a hard score blocker
for authoritative entry.

There is no separate production market-regime, gap, consolidation, EMA-slope,
sector, or option-liquidity gate in the authoritative `TRADE_ENTERED` transition.
Those concepts may exist in UI intelligence or shadow analysis, but static tracing
shows they do not block this lifecycle path. The 90 threshold controls only the
scanner setup label.

## Current production constants

- CALL score threshold: 90
- PUT score threshold: 90
- Authoritative trigger confidence: 65
- Scanner scoring window: 09:45-14:59 (candle time)
- Authoritative lifecycle cutoff: 15:55 ET
- Breakout buffers: 1.0003 above / 0.9997 below prior range
- Volume expansion multiplier: 1.40x
- ARMED score: 70, within 0.4 ATR of trigger
- EXTENDED: more than 0.5 ATR beyond trigger
- Candidate maximum age: 60 minutes

The 90 score threshold is structurally restrictive for the visible setup label but
cannot, by itself, explain zero authoritative entries because lower-scoring
directional candidates are still projected. The authoritative score gate is 65 on
the candidate's immutable confidence. A score below 65 can block a reached trigger;
otherwise trigger distance, invalidation/chase state, session time, or the one-cycle
lifecycle ordering are the meaningful gates. Volume is measured on the latest
five-minute candle, so an incomplete candle can contribute less than a completed
candle, but that only affects additive score. The persisted funnel is required to
identify today's actual blocker.

## Transition audit

The bullish/bearish trigger comparison directions are correct. Lifecycle time uses
the worker clock and entry-window conversion uses Eastern market-calendar bounds.
Persisted trigger values are intentionally immutable. Opportunities are not
overwritten: changed 5-minute identity buckets can create separate candidates.

The notable transition characteristic is ordering: existing candidates are
evaluated before the current result creates a candidate. Thus a current
`Triggered` result can legitimately show `AWAITING_AUTHORITATIVE_LIFECYCLE` for one
cycle. If persisted diagnostics show the same symbol repeatedly triggered without
an entry on subsequent cycles, that is evidence for a transition defect; static
analysis alone does not show such a defect.

## Diagnostic persistence and UI

Railway writes additive, non-authoritative diagnostic snapshots to:

- `authoritative_entry_funnel_cycles`
- `authoritative_entry_funnel_symbols`

Each completed cycle records scanned, valid, directional, qualified setup, ARMED,
trigger-reached, and `TRADE_ENTERED` counts plus primary blockers and non-secret
thresholds. Symbol rows preserve score, real setup state, trigger/current prices,
distance, and update time. Diagnostic failures are caught and cannot fail or alter
scanner/lifecycle processing.

Developer Tools reads these tables with initialization disabled and renders the
latest cycle, blockers, candidate table, near-entry ordering, thresholds, and the
latest previous-session cycle. Same-clock historical comparisons cannot be shown
for sessions before this instrumentation because those intraday snapshots do not
exist; the UI states that limitation instead of inventing history.

## Interpreting zero entries

Before deployment, the repository can identify plausible suppressors but cannot
truthfully determine today's production counts from scanner health alone. After a
deployed cycle:

- many directional results but few score-qualified setup labels describes weak
  alignment, but does not prove authoritative candidates were blocked;
- qualified/triggered results awaiting one cycle are normal ordering;
- repeated triggered results with no later entry suggests lifecycle investigation;
- many ARMED results indicate a quiet near-trigger session;
- many insufficient-data results contradict an apparently healthy result count;
- zero directional results indicates genuinely unclear scoring rather than a
  PAPER, MIRROR, or Railway problem.

This instrumentation changes no threshold, signal, trigger, lifecycle, execution,
or risk behavior.
