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

T0 persists the production chain payload already requested by
`capture_qualified_signal`. It does not make its own expiration, chain, quote, or
underlying requests.

`requested_at` is the production provider-request start retained by the observing
wrapper. Provider/quote timestamps are the provider timestamps when present.
`persisted_at` may be later because research writes after authoritative work.
Delaying persistence does not relabel a later chain fetch as TRADE_ENTERED data;
there is no later research fetch.

If production never requested a chain, T0 records `NOT_REQUESTED_BY_PRODUCTION`
(or `CAPTURE_UNAVAILABLE` when a production trade exists but the payload was not
observable). It does not fabricate `CHAIN_EMPTY`.

### Fill — `capture_reason=PRODUCTION_FILL`

PRODUCTION_FILL is **not** a second independent point-in-time chain snapshot.
It is the same production chain/quote payload used by production selection/fill
(`observation_relation=SAME_CAPTURE`, shared `payload_identity`). Distinct
fill-time chain observations (`DISTINCT_CAPTURE`) are not created by this
recorder.

The fill record adds production contract, realistic entry, fill, elapsed seconds
from the TRADE_ENTERED event, and eligibility / rejection information. The
production fill is not altered.

### Reject / no-contract

Results are distinct where evidence permits:

- `PROVIDER_FAILURE` — production request failed; no fabricated empty chain
- `CHAIN_EMPTY` — production requested and received no usable expiration/chain
- `NO_ELIGIBLE_CONTRACT` — chain present but selector/rules accepted none
- `NOT_REQUESTED_BY_PRODUCTION` — production never requested chain data
- `CAPTURE_UNAVAILABLE` — production ran but the chain payload was not observable
- `CAPTURE_FAILURE` — production capture returned nothing usable
- `CAPTURED` — candidate evidence persisted

### Marks

One observation per OPEN paper option position on the existing pre-scan refresh
cadence. Marks consume only quotes already obtained by `refresh_option_positions`.
No research-only polling, extra option quotes, extra underlying quotes, or extra
Greeks requests. Bid/ask/mid/last, timestamps, quote age, volume/OI/greeks when
the production quote payload supplies them, underlying, lifecycle state,
production entry, and current production return. Marks never cause an exit.

Production `option_quote` currently requests `greeks=false`. Mark greeks stay
null unless that production quote later includes them. This recorder does not
change quote provider flags.

## Provider-call impact

Enabling or disabling the flight recorder must not change the number or type of
market-data provider requests made by the authoritative production path.

A. Existing production chain request at `capture_qualified_signal` is observed and
   persisted for T0/FILL. Quote requests already made by `refresh_option_positions`
   are observed and persisted as marks.

B. Genuinely new research-only provider requests: none. If production did not
   request a chain, research records unavailability and does not fetch one.

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

- H1: T0 and PRODUCTION_FILL currently share `SAME_CAPTURE` production chain
  payload. Do not treat them as two independent delayed chain snapshots. Elapsed
  seconds measure TRADE_ENTERED event time to persist/fill, not a second fetch.
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
