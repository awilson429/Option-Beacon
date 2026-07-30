# OptionBeacon 2.0 MVP

## Definition

The MVP is a deterministic, explainable, paper-only analyst for SPY, QQQ, and
a bounded liquid universe using mostly existing data. It produces market
context, evaluates several inactive research playbooks, explains independent
evidence, tracks a formal lifecycle in shadow mode, builds complete trade
plans, and records paper outcomes for calibration.

It does not replace the stable production scanner during development.

## Included

### Market context

- SPY and QQQ session trend, structure, VWAP, opening behavior, realized
  volatility, and directional agreement;
- sector ETF proxy alignment;
- key prior/session levels;
- data freshness and missing-data state;
- bullish, bearish, and balanced deterministic scenarios.

### Initial research playbooks

Start with four playbooks that use existing OHLCV:

1. Trend Continuation
2. Opening Range Breakout
3. VWAP Reclaim/Rejection as two definitions sharing infrastructure
4. Pullback Continuation

Compression Expansion and Support/Resistance Reversal follow after objective
feature definitions. Gap playbooks wait for validated extended-hours data.
Opening Range Failure and Relative Strength Divergence follow after the shared
framework proves stable.

No playbook is production-active in the MVP build phase.

### Explainable evidence

Use the gated family hybrid from the
[evidence model](optionbeacon_2_evidence_model.md):

- Market Environment
- Trend
- Structure
- Momentum
- Participation
- Relative Strength
- Location
- Timing
- Risk/Reward

Event Risk is `UNKNOWN` unless reliable data is added. Options Context is
descriptive/downstream. Sentiment is excluded from the grade.

### Opportunity lifecycle

Run the proposed lifecycle in replay and isolated shadow mode. READY requires
all hard gates; ACTIVE requires a distinct tracked paper-entry event. Every
transition is append-only, versioned, idempotent, and explainable.

### Trade plans and management

- entry zone and maximum entry;
- structural stop and up to three targets;
- risk/reward and invalidation;
- expected duration and setup expiry;
- current R, MFE, MAE, target progress, and thesis health after paper entry;
- advisory management events with reason codes.

Existing production calculations remain unchanged. New plan policies begin in
research.

### Historical evidence

- deterministic replay with dataset manifests/hashes;
- outcome cohorts by playbook, version, grade, regime, and direction;
- historical analog summaries with match level and sample size;
- explicit insufficient-data behavior;
- append-only experiment registry and isolated shadow logs.

### User surfaces

Behind a disabled-by-default feature flag:

- Morning Brief view model;
- Live Market Desk opportunity view model;
- Active Trade Management view model;
- Post-Trade Review view model.

The core engines have no Streamlit dependency.

## Excluded

- live-order placement or brokerage execution;
- production scanner replacement;
- unvalidated scoring or thresholds;
- true market breadth/internals;
- unusual options activity and put/call indicators;
- sentiment-driven recommendations;
- premium news/calendar dependencies;
- ML-generated signals or opaque predictions;
- historical IV percentile without a validated dataset;
- gap playbooks before extended-hours data validation;
- user-facing shadow recommendations before approval.

## Build sequence

1. Freeze schemas and point-in-time rules.
2. Build Market Context Engine and replay fixtures.
3. Implement inactive playbook contract and initial definitions.
4. Implement evidence families, gates, conflicts, and grades.
5. Implement lifecycle reducer and event log.
6. Adapt existing plan outputs behind research interfaces.
7. Add analog/replay cohorts.
8. Run isolated shadow evaluation.
9. Add feature-flagged read-only view models.
10. Complete forward paper-validation protocol.

## Acceptance criteria

- Equal versioned inputs produce byte-equivalent decisions.
- No future bar, revised outcome, or later analog enters an earlier decision.
- Required missing/stale data prevents READY.
- Every output exposes support, conflict, missing data, and reason codes.
- Playbooks remain disabled in production.
- Shadow failures cannot affect scans, scores, alerts, plans, lifecycle,
  journals, positions, or UI.
- No production module changes behavior until a controlled promotion.
- Full regression remains green.
- Paper evaluation reaches the predeclared sample and regime-coverage gates.

## Data requirements

Required:

- normalized OHLCV for SPY, QQQ, symbols, and sector ETFs;
- reliable timestamps/session calendar;
- volume and derived VWAP;
- current quotes for open paper tracking;
- append-only decision and outcome records.

Optional:

- Tradier contract liquidity context;
- Finnhub general news display.

Deferred:

- economic calendar, structured sentiment, true VIX/breadth/internals,
  unusual-options activity, and historical IV.

## Safety and promotion

MVP components progress through offline replay, held-out evaluation, shadow
mode, forward paper validation, and explicit human approval. Promotion is
component-level and reversible. The MVP itself does not authorize production
activation.
