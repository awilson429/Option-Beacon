# Scanner Performance Instrumentation

OptionBeacon currently scans its authoritative universe sequentially. Each symbol
finishes `generate_signal(symbol)` and authoritative lifecycle persistence before
the next symbol begins. Production evidence previously showed roughly 30 symbols
in 7.5 minutes (about 15 seconds per symbol), which projects to approximately 17
minutes for 68 symbols and can be material for intraday detection.

This branch measures that architecture. It does not change scanner order,
concurrency, caching, providers, retries, sleeps, qualification, scoring,
lifecycle behavior, or PAPER execution.

## Structured events

`scanner_symbol_timing` is emitted once per attempted symbol. It contains the
symbol's immutable scan index, wall-clock start/completion timestamps, total
monotonic duration, success or exception type, real stage durations, provider
operation durations and counts, HTTP-status counts when available, retry/backoff
time, 429 count, and timeout count. It never includes URLs, headers, tokens, or
raw provider payloads.

`scanner_performance_summary` is emitted after lock release. It includes full-cycle
and lifecycle-phase durations, per-symbol average/median/p90/maximum, the five
slowest symbols, provider totals, retry wait, persistence and estimated local
compute time, symbol order, and rotation skew. Percentiles use nearest rank.

`scanner_performance_warning` is observability-only. Centralized thresholds flag:

- full scans over five minutes;
- median symbol time over five seconds;
- p90 symbol time over ten seconds;
- retry/backoff over 30 seconds;
- failures above ten percent.

Warnings do not stop, delay, or otherwise alter a scan.

## Measured lifecycle phases

- configuration resolution;
- lock acquisition and release;
- market-data cycle initialization and summary;
- PAPER configuration persistence and state restore;
- universe and authoritative open-trade loading;
- symbol scan loop and scanner-health progress writes;
- snapshot write;
- authoritative-to-PAPER handoff query;
- PAPER cycle;
- scanner-health completion.

Within `generate_signal()`, measurements cover market data, indicator calculation,
scoring, trade-plan enrichment, option liquidity, contract filtering, timestamps,
trade-plan/outcome/result persistence, shadow experiments, and authoritative
lifecycle persistence.

Provider coverage includes Finnhub universe quote calls, actual Yahoo Finance
historical-bar calls, and Tradier expiration, chain, and quote requests. Yahoo 429
retry waits and Finnhub's existing cold-cache quote throttle are accounted using
their existing delay values. PAPER-stage Tradier calls are captured in run totals
when they occur outside a symbol context.

## Option-chain architecture

The current scanner does **not** request an option chain for every symbol.
`option_liquidity_for_setup()` returns "Not checked" unless the underlying signal
is already one of the active bullish/bearish setup states. Qualifying setups then
perform expiration and chain lookup before contract filtering. A two-stage
underlying/contract architecture therefore already exists inside each symbol,
although underlying qualification remains sequential across the universe.

## Provider request-volume interpretation

When the daily mover cache is cold, universe construction can make one Finnhub
quote request per liquid-options candidate with an existing 50 ms delay between
requests. In the normal successful symbol path, each symbol makes one Yahoo historical-bars call,
so 68 symbols imply about 68 Yahoo calls per rotation. Empty data can try the
existing three periods, and a rate-limited request can use up to three existing
attempts. Active option setups can add one Tradier expiration and one chain call;
their existing process-local LRU caches may avoid repeat network calls. PAPER
position refresh and contract capture can add Tradier quote/chain calls.

At a five-minute cadence, the normal underlying path would be about 816 Yahoo
calls/hour; a 17-minute actual rotation would achieve only about 240 calls/hour.
Production summaries—not these bounds—must be used to determine real volume,
429 exposure, and feasible cadence.

## Optimization candidates to evaluate after measurement

1. **Eliminate duplicate provider work within one rotation.** Moderate payoff,
   low-to-medium behavioral risk, and low rate-limit risk if results remain scoped
   to the same scan timestamp.
2. **Separate fast universe qualification from contract resolution.** Potentially
   high payoff if Tradier stages dominate qualifying symbols; medium architecture
   and freshness risk. Existing option gating is a useful foundation.
3. **Provider batching where officially supported.** Potentially high payoff and
   medium implementation risk; provider limits and response semantics must be
   verified first.
4. **Provider-specific bounded concurrency.** High theoretical payoff but high 429,
   ordering, lifecycle, and determinism risk. It should not be attempted until
   measured call counts and backoff behavior establish safe bounds.
5. **Shared market-data caching.** Medium payoff and medium staleness risk; cache
   lifetime must not cross the strategy's freshness boundary.
6. **Tiered or priority rotation.** Improves freshness for selected symbols but has
   high trading-behavior and fairness impact because it changes evaluation order.

A 1–3 minute rotation requires an average end-to-end budget of roughly 0.9–2.6
seconds per symbol for 68 sequential symbols, before fixed pre/post work. The
earlier 15-second observation does not support that target. Feasibility should be
decided only after production summaries identify how much time is parallelizable
network wait versus required sequential computation and persistence.
