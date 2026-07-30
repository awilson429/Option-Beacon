# OptionBeacon 2.0 Architecture

## Architectural intent

OptionBeacon 2.0 is a deterministic analysis pipeline with versioned contracts.
Production and research share schemas and pure calculations, but never share
activation state implicitly. Streamlit consumes view models; it does not own
trading decisions.

```text
Provider adapters
    -> normalized point-in-time market data
    -> feature extraction
    -> market context
    -> playbook evaluations
    -> evidence synthesis
    -> opportunity lifecycle
    -> trade plans / management events
    -> journals, replay, analogs, shadow records
    -> read-only UI view models
```

## Core principles

- **Point-in-time correctness:** Inputs include event time, received time,
  source, session, and freshness. Computation cannot read future bars.
- **Determinism:** Equal inputs plus equal component versions produce equal
  outputs.
- **Explicit schemas:** Boundary objects are serializable, validated, and
  versioned.
- **Immutable facts, append-only decisions:** Raw snapshots, plan revisions,
  lifecycle events, and experiment records are not rewritten as narratives
  change.
- **Separation:** Provider, domain, research, persistence, and UI concerns have
  one-way dependencies.
- **Failure isolation:** Optional evidence, shadow evaluators, analogs, and UI
  enrichments cannot interrupt production scanning.
- **No execution:** Brokerage order APIs are outside the architecture.

## Proposed modules and contracts

### Market data

`providers/` adapts Yahoo Finance, Finnhub, and Tradier into explicit provider
results. A result distinguishes `AVAILABLE`, `STALE`, `UNAVAILABLE`,
`RATE_LIMITED`, and `ERROR`.

`market_data/schemas.py` defines:

- `QuoteSnapshot`
- `Bar`
- `BarSeries`
- `OptionChainSnapshot`
- `NewsItem`
- `ScheduledEvent`
- `DataQuality`

`market_data/normalization.py` owns symbol normalization, time zones, sessions,
duplicates, missing bars, numeric validation, and provenance.

### Feature extraction

`features/engine.py` accepts only normalized data and a cutoff time. It returns
a `FeatureSnapshot` with values, observation windows, as-of times, quality, and
feature-definition versions. Candidate extractors include trend, VWAP,
structure, range, volatility, participation, relative strength, and location.

Extractors do not assign opportunity states or recommendations.

### Market Context Engine

`context/engine.py` produces `MarketContext`:

- session and data health;
- SPY/QQQ regime and directional agreement;
- trend, volatility, and opening behavior;
- sector/proxy context;
- key levels;
- scenario list and invalidation;
- supporting, conflicting, and missing context.

Context is an input to playbooks, not a global score multiplier.

### Playbook Engine

`playbooks/base.py` defines a versioned `PlaybookDefinition` and
`PlaybookEvaluation`. Each playbook declares prerequisites, anti-conditions,
formation, confirmation, entry-zone construction, late rules, invalidation,
stop/target policy, expected duration, and research gate.

`playbooks/registry.py` contains explicit enabled states by environment.
Definitions begin inactive.

### Evidence Engine

`evidence/engine.py` groups observations into independent families and returns:

- one verdict per family;
- hard-gate outcomes;
- conflicts and missing families;
- evidence grade;
- broad confidence band;
- stable reason codes and explanation.

It does not add every indicator into a 100-point total. See the
[evidence model](optionbeacon_2_evidence_model.md).

### Opportunity Lifecycle

`opportunities/state_machine.py` is a pure transition reducer:

```text
reduce(current_state, event, policy_version) -> transition result
```

It validates allowed transitions, applies precedence, and emits a reason.
`opportunities/events.py` defines immutable, idempotent events.
`opportunities/repository.py` persists events and snapshots separately.

The proposed state machine remains disconnected from the current production
lifecycle until controlled promotion.

### Trade Plan Engine

`plans/engine.py` consumes the selected playbook evaluation, evidence result,
market features, and risk policy. It returns a versioned `TradePlan` with entry
zone, maximum entry, stop, targets, invalidation, risk units, expiry, and
reason codes.

The existing stable Trade Plan Engine remains the production implementation.
New policies begin as research versions and must prove parity or intentional
differences.

### Trade Management Engine

`management/engine.py` consumes an immutable entry plan plus current
point-in-time features. It emits advisory events such as thesis weakening,
target reached, stop threatened, or time review. It never mutates the original
plan and does not submit orders.

### Event-Risk Engine

`events/engine.py` normalizes scheduled events and calculates temporal
proximity. In the MVP, unavailable event data produces `UNKNOWN`, not safe.
Manual/static event input can be used in research, but cannot masquerade as a
live calendar.

### Historical Analog Engine

`analogs/engine.py` matches only historical snapshots available before the
current as-of time. It returns match dimensions, sample size, outcome metrics,
and limitations. Similarity rules and datasets are versioned.

### Research and Replay

`research/replay.py` advances a clock through normalized bars and invokes the
same pure engines. Dataset manifests store symbols, ranges, interval, source,
normalization version, hashes, and exclusions.

`research/experiments.py` appends experiment definitions and results to the
existing registry model. Training/calibration and evaluation periods remain
chronologically separate.

### Shadow Evaluation

`shadow/evaluator.py` runs after stable production decisions. It receives a
copy of source data and production output, writes only ignored shadow records,
and catches all exceptions. It cannot call production alert, journal,
position, or order APIs.

### Journaling

`journal/` stores:

- immutable opportunity and lifecycle events;
- plan versions;
- paper entries and exits;
- management events;
- model and execution review fields;
- component and dataset versions.

Production stores retain their current behavior until migration is explicitly
approved.

### UI view models

`view_models/` converts domain outputs to presentation-safe dictionaries:

- `MorningBriefView`
- `MarketDeskView`
- `OpportunityCardView`
- `ActiveTradeView`
- `PostTradeReviewView`

It owns display labels and unavailable formatting. Core packages do not import
Streamlit.

## Versioning model

Every evaluation records:

- schema version;
- feature-definition version;
- market-context version;
- playbook id and version;
- evidence-policy version;
- lifecycle-policy version;
- plan-policy version;
- analog-policy and dataset versions;
- application build;
- event and evaluation timestamps.

Breaking schema changes receive a new major version. Policy tuning receives a
new strategy version; it never rewrites old records.

## Point-in-time and replay rules

1. The evaluation clock is explicit.
2. Only observations with event time at or before the clock are eligible.
3. Provider receipt time is retained to model latency.
4. Daily bars are not treated as complete before their session close.
5. Higher-timeframe features use completed bars unless explicitly documented.
6. Corporate-action and adjustment policy is part of the dataset manifest.
7. Missing/duplicate/out-of-session bars are logged deterministically.
8. Analog pools exclude the current and future periods.

## Proposed directory structure

```text
optionbeacon/
  market_data/
    schemas.py
    normalization.py
  providers/
    yahoo.py
    finnhub.py
    tradier.py
  features/
    schemas.py
    engine.py
    trend.py
    structure.py
    participation.py
    volatility.py
  context/
    schemas.py
    engine.py
  playbooks/
    base.py
    registry.py
    trend_continuation.py
    opening_range.py
    vwap.py
    pullback.py
  evidence/
    schemas.py
    engine.py
    policies.py
  opportunities/
    events.py
    state_machine.py
    repository.py
  plans/
    schemas.py
    engine.py
  management/
    engine.py
  events/
    engine.py
  analogs/
    engine.py
  journal/
    schemas.py
    repository.py
  research/
    replay.py
    datasets.py
    experiments.py
  shadow/
    evaluator.py
  view_models/
    morning_brief.py
    market_desk.py
    active_trade.py
    review.py
```

This is a target structure, not a required immediate migration. Existing
modules should move only through small, tested changes.

## Integration and promotion boundaries

- New packages begin unused by production.
- Feature flags are explicit, environment-safe, and disabled by default.
- Shadow evaluation receives data after production output is fixed.
- A component may be promoted independently; no “big bang” rewrite is needed.
- Promotion requires replay, shadow, paper, regression, rollback, and human
  approval evidence.

## Security and operations

- Secrets remain in environment/Streamlit Secrets and never enter outputs.
- Provider errors are sanitized.
- Runtime stores remain ignored or externalized.
- Rate limits use caching, batching, and bounded retries.
- Data and recommendation freshness are visible.
- No module exposes brokerage order placement.
