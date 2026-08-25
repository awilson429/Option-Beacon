# Canonical Trade Management Snapshot Audit

## Scope and non-negotiable boundary

This audit was completed before runtime implementation on branch
`feature/canonical-trade-management-snapshots`, based on merged `main` at
`ac9c31f`. The new persistence layer is additive and observational. It must not
change strategy selection, Trade Coach logic, Exit Score logic, execution,
allocation, stops, targets, exits, provider calls, or worker cadence.

The only safe canonical join is the exact tuple `(trade_id, lane)`, with
`opportunity_id` retained as provenance. Symbol, contract, timestamps, or
direction are not unique enough to attribute management state. Records without
an exact trade/lane identity are intentionally left unavailable; no legacy
symbol-based backfill is permitted.

## Existing identities and persistence

| State owner | Canonical identity available | Current durable state | Snapshot eligibility |
| --- | --- | --- | --- |
| `authoritative_trades` | `id`, unique `opportunity_id` | lifecycle, underlying entry/last, stop, targets, exit/result, metadata | Eligible when the exact authoritative trade ID and lane are known |
| `capital_positions` | `position_id`, `lane`, `source_trade_id`, `opportunity_id` | OB/BROAD contract, size, entry/mark, risk, P&L, stop/targets, lifecycle | Primary OB/BROAD write integration; identity is exact and lane-owned |
| `paper_execution_positions` | paper `position_id` joined through `capital_positions.source_trade_id` | contract marks and paper execution state | Source context only; the lane-qualified capital position owns the snapshot identity |
| `intraday_paper_trades` | `trade_id`, `opportunity_id`, `variant` | managed and mirror lifecycle state | Distinct intraday domain; must not be relabeled as OB/BROAD |
| `trade_storage.positions` / `recommendations` | legacy numeric position ID only | Streamlit Trade Coach projection and recommendation history | Not eligible: no authoritative trade ID, opportunity ID, or lane |
| `position_context_marks` | `trade_id`, `opportunity_id`, `lane` | historical setup-health research context | Remains separate; it is not a complete management snapshot |

## Management evaluation paths

- `trade_management.coach_recommendation` and related Exit Score calculation
  are the existing advisory logic. They are unchanged.
- `scheduled_trade_coach.run_active_trade_coaching` and the Streamlit active
  trade UI persist legacy recommendations against local numeric position IDs.
  They may also invoke a provider when no result is supplied. The new API must
  never call this path and cannot safely attribute its legacy records.
- `live_trade_coach` and `live_trade_coach_dashboard` produce advisory
  projections without a canonical active-trade/lane foreign identity. They are
  not candidates for inferred joins.
- `exit_coach_intelligence.assess_exit_conditions` is advisory and does not own
  lifecycle state. It remains unchanged.
- `intraday_execution.IntradayRepository.update_managed` and `update_mirror`
  persist exact variant-owned state. MIRROR is research/control and must never
  appear as OB/BROAD management state.
- `CapitalRepository.sync_paper_positions` updates exact lane-qualified
  `capital_positions` after paper execution refreshes. It has the required
  identity and persisted plan/lifecycle inputs, so it is the safe integration
  point for OB/BROAD canonical snapshots.
- `IntradayRepository.update_managed`, `update_mirror`, and the direct MIRROR
  close path are the exact-ID boundaries where the separate intraday management
  state is actually evaluated and persisted. They are safe snapshot write
  points only when their lanes remain `INTRADAY_MANAGED` and
  `CONTROL_RESEARCH`; this state must not be relabeled as OB/BROAD.

## Selected design

`trade_management_snapshots` is an append-only history table owned by
`TradeRepository`. Each row includes the exact identity, captured/source times,
trade and contract context, marks and P&L when available, risk/plan values,
Trade Coach and Exit Score fields when available, explicit missing-data state,
source/version metadata, the complete payload, and a material-state
fingerprint.

Repository operations will provide:

1. validation and persistence of an exact `(trade_id, opportunity_id, lane)`;
2. material-state deduplication against the latest snapshot for the same exact
   `(trade_id, lane)` so ordinary mark refreshes do not create history noise;
3. latest-snapshot lookup for one identity or a batch of exact identities; and
4. chronological history for the read-only management endpoint.

The fingerprint excludes observation timestamps, transient marks, elapsed time,
freshness, and P&L. It includes identity, lifecycle, plan/risk controls, and
management conclusions. Repeated refreshes therefore reuse the last row, while
entry, lifecycle, stop/target, risk, or management-state changes create a new
historical snapshot.

Snapshot write failures are logged with exact identity and isolated from the
existing capital/execution flow. Reads tolerate a not-yet-deployed additive
table by returning no snapshot. Neither condition may alter a trade decision or
lifecycle transition.

The write lifecycle therefore covers lane-owned OB/BROAD capital-position
updates and actual intraday managed/control evaluations. OB/BROAD snapshots do
not fabricate Trade Coach or Exit Score fields because those calculations are
not currently evaluated in a canonically attributable OB/BROAD path. Intraday
snapshots persist their native management state while leaving unrelated coach
fields null.

## Active Trades and API contract

`GET /api/trades/active` will batch-load the latest canonical snapshot using
each already-projected row's exact `(id, lane)`. It will not inspect arbitrary
metadata or fall back by symbol. A matching snapshot enriches stop/target and
management fields; otherwise those fields explicitly remain unavailable.

`GET /api/trades/{trade_id}/management` is a read-only chronological history.
An optional lane narrows an otherwise exact trade-ID query. It performs no
writes, provider calls, coaching evaluation, or inferred joins.

MIRROR/control snapshots, if present in the canonical table, use a distinct
research lane such as `CONTROL_RESEARCH`. Active Trades continues to admit only
OB and BROAD, so research state cannot contaminate operational lanes.

## Legacy and deployment behavior

- No existing table is dropped or reinterpreted.
- No legacy recommendation is backfilled without exact identity.
- The schema is created through the existing idempotent repository
  initialization path.
- Before deployment of the additive table, management reads resolve to an
  explicit unavailable/empty state rather than executing coaching logic.
- Existing Streamlit and Python execution behavior remains authoritative and
  unchanged.
