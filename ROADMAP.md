# OptionBeacon 2.0 Roadmap

OptionBeacon 2.0 is an explainable, AI-assisted intraday trade-analysis
platform. It combines independent evidence, applies setup-specific playbooks,
and presents a point-in-time trade thesis without placing live orders.

This roadmap is architectural. Nothing described here changes the current
production scanner until a later phase passes replay, shadow, paper, and
promotion gates.

## Delivery principles

- Production behavior remains the control until controlled promotion.
- Core decisions are deterministic, versioned, replayable, and independent of
  Streamlit.
- Missing data reduces certainty; it never silently becomes a positive signal.
- Research records are append-only and preserve the inputs and versions used.
- New logic progresses through offline replay, shadow evaluation, and paper
  validation before production consideration.
- No phase adds live-order execution.

## Phase 0 - Product specification

**Purpose:** Establish the product contract, MVP, evidence model, playbooks,
state machine, data boundaries, and architecture.

**Deliverables:** The documents linked under [Product documents](#product-documents).

**Dependencies:** Validated optimization infrastructure on `main`.

**Tests:** Documentation links, `git diff --check`, secret scan, and the full
production regression suite.

**Acceptance criteria:** Terms are consistent; production versus research
boundaries are explicit; every proposed capability identifies its data
requirements and missing-data behavior.

**Risks:** Designing around unavailable data or hiding ambiguity behind a
single score.

**Non-goals:** Python implementation, scanner changes, UI changes, or playbook
activation.

## Phase 1 - Market Context Engine

**Purpose:** Produce a versioned point-in-time context for SPY, QQQ, volatility,
and sector alignment.

**Deliverables:** Context schema, feature timestamps, session segmentation,
trend/regime states, key levels, and replay fixtures.

**Dependencies:** Phase 0; normalized OHLCV.

**Tests:** Time-zone/session boundaries, no-lookahead fixtures, missing bars,
stale data, deterministic serialization, and replay parity.

**Acceptance criteria:** The same inputs and version always produce the same
context; every feature includes an as-of time and source.

**Risks:** Incomplete premarket coverage and proxy-based volatility.

**Non-goals:** Trade selection or user-facing recommendations.

## Phase 2 - Playbook Framework

**Purpose:** Define a common contract for setup-specific formation,
confirmation, entry, invalidation, and research requirements.

**Deliverables:** Versioned playbook interface, registry, prerequisite and
anti-condition results, initial inactive playbook definitions, and fixtures.

**Dependencies:** Phase 1 context and feature schemas.

**Tests:** Contract conformance, direction symmetry, prerequisite failures,
late-entry boundaries, and invalidation precedence.

**Acceptance criteria:** Playbooks are independently testable and disabled by
default; no universal score is required.

**Risks:** Overlapping playbooks and implicit shared assumptions.

**Non-goals:** Production activation or threshold optimization.

## Phase 3 - Explainable Evidence Engine

**Purpose:** Combine independent evidence families without double-counting
correlated indicators.

**Deliverables:** Evidence observations, family verdicts, conflict matrix,
gates, confidence bands, evidence grade, and explanation model.

**Dependencies:** Phases 1-2.

**Tests:** Correlation-family deduplication, missing data, conflicts, gate
precedence, deterministic explanations, and calibration fixtures.

**Acceptance criteria:** Every grade is traceable to evidence; no family gains
weight merely because it exposes several correlated indicators.

**Risks:** False precision and post-hoc narrative generation.

**Non-goals:** Machine-learned recommendations or production score replacement.

## Phase 4 - Opportunity Lifecycle

**Purpose:** Track an opportunity from formation through closure using a formal
state machine.

**Deliverables:** Transition table, transition reasons, immutable event log,
idempotency rules, and replay reducer.

**Dependencies:** Phases 1-3.

**Tests:** Every allowed transition, every prohibited transition, stale event
handling, duplicate events, restart/replay, and closed-state immutability.

**Acceptance criteria:** Impossible transitions fail safely and every state is
reconstructable from events.

**Risks:** Ambiguous ACTIVE/LATE precedence and out-of-order market updates.

**Non-goals:** Connection to the production lifecycle.

## Phase 5 - Dynamic Trade Plan Engine

**Purpose:** Generate playbook-specific plans with explicit entry zones,
invalidation, stops, targets, and late-entry rules.

**Deliverables:** Versioned plan inputs/outputs, risk units, plan revisions,
and reason codes.

**Dependencies:** Phases 1-4 and the existing stable trade-plan foundation.

**Tests:** Bullish/bearish symmetry, price precision, risk/reward constraints,
late/invalid plans, immutable plan revisions, and parity safeguards.

**Acceptance criteria:** Plans are deterministic and cannot weaken risk merely
to preserve an opportunity.

**Risks:** Unintended deviation from stable calculations.

**Non-goals:** Automatic production replacement or brokerage execution.

## Phase 6 - Historical Replay and Analogs

**Purpose:** Evaluate point-in-time behavior and retrieve comparable historical
contexts without leakage.

**Deliverables:** Replay datasets, analog feature vectors, similarity rules,
outcome cohorts, provenance, and dataset hashes.

**Dependencies:** Versioned outputs from Phases 1-5.

**Tests:** Dataset hashes, chronological splits, no future fields, deterministic
neighbors, malformed rows, and minimum-sample behavior.

**Acceptance criteria:** Every result is reproducible and analogs disclose
sample size, match quality, and data limitations.

**Risks:** Survivorship bias, short history, and overfitting similarity.

**Non-goals:** Predictive ML or claims of statistical significance without
adequate samples.

## Phase 7 - Shadow Evaluation

**Purpose:** Run OptionBeacon 2.0 beside production without affecting it.

**Deliverables:** Failure-isolated shadow evaluator, ignored runtime log,
decision comparison, funnel metrics, and version identifiers.

**Dependencies:** Phases 1-6.

**Tests:** Shadow failures cannot alter scans, scores, alerts, journals,
positions, or latency budgets; deduplication and append-only behavior.

**Acceptance criteria:** Production equivalence remains exact and shadow output
is complete enough for research.

**Risks:** Provider cost, latency, and accidental coupling.

**Non-goals:** User-facing recommendations or production filtering.

## Phase 8 - Trade Desk Integration

**Purpose:** Present versioned context, evidence, lifecycle, plans, and analogs
through read-only view models.

**Deliverables:** Morning Brief, Live Market Desk, active-management, and
post-trade view models behind an explicit feature flag.

**Dependencies:** Stable shadow outputs and UI-independent core modules.

**Tests:** View-model formatting, unavailable states, accessibility,
feature-flag defaults, and production UI regression.

**Acceptance criteria:** No core module imports Streamlit; the default
production experience remains unchanged until approval.

**Risks:** Information overload and misleading certainty.

**Non-goals:** Order entry or unflagged default UI changes.

## Phase 9 - Paper Validation

**Purpose:** Validate opportunity quality, plans, and management in forward
paper tracking.

**Deliverables:** Frozen validation protocol, paper cohorts, outcome taxonomy,
calibration tables, drift checks, and review report.

**Dependencies:** Phase 7 shadow stability and Phase 8 review surfaces.

**Tests:** Cohort integrity, lifecycle completeness, returns, MFE/MAE,
calibration, missing quotes, and restart recovery.

**Acceptance criteria:** Predeclared sample and quality gates are met across
multiple regimes; failures are documented rather than optimized away.

**Risks:** Insufficient samples and regime concentration.

**Non-goals:** Capital deployment.

## Phase 10 - Controlled Production Promotion

**Purpose:** Promote only validated components through explicit approval.

**Deliverables:** Change proposal, equivalence report, rollback plan, flags,
monitoring, and signed promotion checklist.

**Dependencies:** Phase 9 acceptance and human approval.

**Tests:** Full regression, canary/shadow comparison, rollback, data outage,
performance, and hosted smoke testing.

**Acceptance criteria:** Promotion scope is narrow, reversible, observable, and
approved. Defaults change only in the approved release.

**Risks:** Behavior drift and operational outages.

**Non-goals:** Live-order execution.

## Product documents

- [Product specification](docs/optionbeacon_2_product_spec.md)
- [Architecture](docs/optionbeacon_2_architecture.md)
- [Evidence model](docs/optionbeacon_2_evidence_model.md)
- [Playbooks](docs/optionbeacon_2_playbooks.md)
- [Data capability map](docs/optionbeacon_2_data_capability_map.md)
- [Opportunity state machine](docs/optionbeacon_2_state_machine.md)
- [MVP](docs/optionbeacon_2_mvp.md)
