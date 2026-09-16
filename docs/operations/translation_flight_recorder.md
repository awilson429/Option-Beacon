# Translation research flight recorder

THE FLIGHT RECORDER DOES NOT MAKE TRADING DECISIONS.

It is a fail-open, side-car research instrument. Authoritative OptionBeacon
behavior remains:

```text
providers → worker / scanner / strategy → TRADE_ENTERED
    → existing option selection / paper execution
    → existing BROAD / OB logic
    → existing management
```

In parallel, and never on the authoritative return path:

```text
TRADE_ENTERED
   ├── authoritative production path (unchanged)
   └── TRANSLATION_FLIGHT_RECORDER_V1 capture (research persistence only)

OPEN PAPER POSITION
   ├── authoritative management / refresh (unchanged)
   └── research mark capture (observation only)
```

Lane role is `RESEARCH`. Experiment/research version is
`TRANSLATION_FLIGHT_RECORDER_V1`. This is not an H1/H2/H3 winner, not a strategy
version, and not a TAKE/REJECT engine.

Disable with `OPTIONBEACON_TRANSLATION_RESEARCH_ENABLED=false`. Default is on,
matching other research sidecars. Production continues if the recorder is
missing, throws, or cannot reach the database.

## Purpose

Future OptionBeacon opportunities must leave enough point-in-time option evidence
to test translation hypotheses honestly:

- H1 — earlier signal-to-contract execution
- H2 — underlying-thesis-aligned option lifecycle
- H3 — alternative contract selection

This task only instruments. It does not simulate earlier fills, thesis exits,
alternative selectors, or experimental P&L.

## Non-authoritative guarantee

The recorder must not create trades, TAKE decisions, rejections, fills, BROAD or
OB changes, capital, stops, targets, max hold, scores, or confidence. It must not
become required for production. If capture fails, the worker logs a bounded
research failure and continues.

Insertion points:

- T0 / fill: after existing `capture_qualified_signal` + production
  decision/open in `run_paper_execution`, never instead of them.
- Marks: after existing `refresh_option_positions` in `refresh_paper_positions`.
  No new polling loop.

## Tables / repositories

Additive `CREATE TABLE IF NOT EXISTS` via `TranslationResearchRepository`.
No authoritative tables are rewritten. No historical chains are backfilled.

- `translation_research_captures` — one row per logical
  `(research_version, opportunity_id, capture_reason)`
- `translation_research_candidates` — selector-visible contracts for that capture
- `translation_research_marks` — one row per
  `(research_version, paper_trade_id, recorded_at)`

Query API (repository only; no Market Command page and no public FastAPI):

- `captures(opportunity_id=, capture_reason=, research_version=, option_symbol=, session_date=)`
- `candidates(capture_id)` / `candidates_for_opportunity(opportunity_id)`
- `marks(opportunity_id=, paper_trade_id=, option_symbol=, research_version=)`

Join future thesis events with `opportunity_id` on `authoritative_trade_events`
and dense marks on the same opportunity / paper trade id.

## Capture timing and fields

### T0 — `capture_reason=TRADE_ENTERED`

Fired for every new authoritative `TRADE_ENTERED` that reaches the paper option
path, including no-chain / provider / no-eligible outcomes.

Identity: opportunity_id, authoritative_trade_id, scan_cycle_id, symbol,
direction, research version, capture reason, requested_at, provider timestamp,
persisted_at.

Underlying: scanner/result price and timestamp when present.

Candidates: the CALL/PUT universe actually passed into production
`select_contract` for the preferred expiration (not the full listed surface of
unrelated expirations). Bid/ask/mid, sizes, volume, OI, delta, IV, gamma, theta,
DTE, quote timestamp, eligibility, rejection reason, selector rank/key, and the
contract the current selector would choose from that exact set. Research never
substitutes that choice for production.

### Fill — `capture_reason=PRODUCTION_FILL`

Same candidate class at the production capture/fill point, plus selected
production contract, realistic entry, fill, bid/ask/mid, quote timestamp,
underlying, elapsed seconds from the TRADE_ENTERED event, and eligibility /
rejection information. The production fill is not altered.

### Reject / no-contract

Results are distinct where evidence permits:

- `PROVIDER_FAILURE` — request failed; no fabricated empty chain
- `CHAIN_EMPTY` — provider returned no usable expiration/chain
- `NO_ELIGIBLE_CONTRACT` — chain present but selector/rules accepted none
- `CAPTURE_FAILURE` — production capture returned nothing usable
- `CAPTURED` — candidate evidence persisted

### Marks

One observation per OPEN paper option position on the existing pre-scan refresh
cadence. Bid/ask/mid/last, timestamps, quote age, volume/OI/greeks when the
production quote payload supplies them, underlying, lifecycle state, production
entry, and current production return. Marks never cause an exit.

Production `option_quote` currently requests `greeks=false`. Mark greeks stay
null unless that production quote later includes them. This recorder does not
change quote provider flags.

## Provider-call impact

A. Existing production chain request at `capture_qualified_signal` is wrapped in a
   one-cycle read-through cache and additionally persisted for T0/FILL. Quote
   requests already made by `refresh_option_positions` are observed and persisted
   as marks. No extra quote polling.

B. Genuinely new chain requests are bounded to at most one T0 load per logical
   `TRADE_ENTERED` when production did not already populate the cache (for
   example an exception before the production fetch). Duplicate T0/FILL rows are
   ignored before a second provider walk.

Expected additional requests/day: ~0 on the normal path where T0 and fill share
the production chain payload. Worst case is one extra expiration+chain pair per
undispositioned TRADE_ENTERED that failed before the production fetch.

## Storage estimate

Assumptions: ~2–8 new TRADE_ENTERED option-path evaluations per session, one T0
and one FILL capture each, ~20–80 selector-visible candidates per capture, and
marks only for OPEN paper positions (~0–5) once per existing scan cycle
(~70–120 cycles/session).

- Captures/day: ~4–16
- Candidates/day: ~80–1,300
- Marks/day: open_positions × cycles ≈ 0–600
- Rows/day: roughly 100–2,000
- Storage/day: on the order of 0.05–1 MB (typed columns plus compact JSON keys)
- Storage/month: on the order of 2–30 MB

These are instrumentation bounds, not a reason to persist every scanner symbol's
chain every cycle. That is explicitly out of scope.

## Failure behavior

Import, initialize, persist, and annotate failures are swallowed by worker
wrappers. `research_repository=None` keeps the historical paper path. Research
exceptions cannot change `evaluate_execution`, capital TAKE/PASS, paper fills,
or management exits.

## How later experiments consume this evidence

- H1: compare T0 candidate quotes to PRODUCTION_FILL quotes and elapsed time;
  do not invent fills in this phase.
- H2: join dense marks + authoritative thesis events by opportunity_id;
  do not create hypothetical exits in this phase.
- H3: replay persisted candidate sets under alternate rules;
  do not rank experimental selectors in this phase.

## Deployment

Additive schema created by the worker on startup (`CREATE TABLE IF NOT EXISTS`).
Roll the worker after (or with) the code that knows the new tables. Old workers
ignore the tables. New workers do not rewrite authoritative rows and do not
backfill historical point-in-time chains. Missing historical evidence stays
missing.

Not deployed by this change. Not a Streamlit or Railway production-strategy
change.
