# React Journal audit

## Scope and conclusion

This audit was completed before changing Journal runtime behavior. The React Journal can be built as a read-only projection of canonical persistence, but the repository contains three historically separate concepts that must remain distinct:

1. `authoritative_trades` records the underlying trade lifecycle for one canonical `opportunity_id`.
2. `capital_positions` records lane-specific OB/BROAD simulated capital and option execution outcomes.
3. Streamlit's legacy `positions` and `recommendations` tables form a manually maintained journal whose integer IDs do not map to canonical trade, opportunity, or lane identities.

The safe Journal source for deployable OB/BROAD performance is therefore `capital_positions`, enriched only through exact IDs. Legacy Streamlit records cannot be merged into this projection without an explicit future migration/backfill.

## Persistence inventory

### Legacy Streamlit Journal

`trade_storage.py` owns `positions` and `recommendations`, and `app.py` renders the existing Streamlit Trade Journal. A legacy position stores manually entered contract fields, entry/exit premiums, timestamps, contracts, current stop, targets, notes, grades, and outcome tags. Its recommendation history stores Exit Score/label and coaching text against the local integer `position_id`.

These rows are internally related by `recommendations.position_id = positions.id`, but neither table stores a canonical `trade_id`, `opportunity_id`, or lane. They must not be joined to canonical history by symbol, contract, or timestamp. The React migration does not change this persistence or the existing Streamlit UI.

### Opportunities

`opportunities.id` is the canonical signal identity. It authoritatively supplies symbol, direction, playbook, signal time, initial underlying references, initial stop/targets, source version, and persisted metadata. An opportunity can be evaluated independently by OB and BROAD, so `opportunity_id` alone does not identify a lane-specific position.

### Authoritative trades

`authoritative_trades.id` is the canonical underlying-trade identity and has a unique `opportunity_id`. It stores opened/closed timestamps, status, entry/last/exit underlying prices, stop/targets, exit reason, realized result, and metadata. It does not consistently carry complete option contract or lane-specific execution economics. Lane attribution may be inferred from its own persisted metadata for existing read models, but it is not a substitute for a lane-specific capital position.

### Paper execution

`paper_execution_trades.trade_id` is an exact paper-execution identity and `source_signal_id`/`opportunity_id` links it to the signal. Closed rows can authoritatively supply option contract, quantity, option entry/exit, total debit/exit value, realized option P&L and return, duration, exit reason, and canonical MFE/MAE.

`paper_execution_positions.trade_id` uses the same execution identity and stores the position's contract, quantity, entry underlying/option prices, marks, excursions, and lifecycle state. It is not lane-specific.

### Capital positions

`capital_positions.position_id` is the lane-specific Journal trade identity. It is generated as `<lane>:<source_trade_id>` and constrained by `UNIQUE(lane, source_trade_id)`. Each row explicitly stores `lane`, `source_trade_id`, and `opportunity_id`, plus contract, quantity, realistic/theoretical entry and exit, committed capital, initial risk, P&L, fees/slippage, timestamps, status, and metadata.

For Journal, exact enrichment is permitted as follows:

- `capital_positions.source_trade_id = paper_execution_trades.trade_id`
- `capital_positions.source_trade_id = paper_execution_positions.trade_id`
- `capital_positions.opportunity_id = opportunities.id`
- `capital_positions.opportunity_id = authoritative_trades.opportunity_id`

The lane remains part of the identity when reading management state and when separating OB from BROAD. No symbol-only join is valid.

### Canonical management snapshots

`trade_management_snapshots` stores immutable material management observations keyed by exact `trade_id` and `lane`, with `opportunity_id` as provenance. Capital snapshots use `capital_positions.position_id` as `trade_id`, so Journal management lookup is exactly:

`trade_management_snapshots.trade_id = capital_positions.position_id AND trade_management_snapshots.lane = capital_positions.lane`

Snapshots are chronological by `captured_at`, with material-state deduplication already enforced by the repository. They can authoritatively provide final/latest Exit Score and management label only when rows exist. Older trades without snapshots remain explicitly unavailable; there is no safe inferred backfill.

## Authoritative historical fields

The following are safe when present on the exact source rows:

- Identity: capital `position_id`, `opportunity_id`, lane, symbol, direction, and status.
- Contract: option symbol, strike, option type from the exact paper execution row, expiration, DTE, and quantity.
- Entry: opened timestamp, paper underlying entry, realistic option premium, exact entry notional derived from realistic premium and quantity (closed capital rows reset current committed capital to zero), and initial dollar risk.
- Exit: closed timestamp, authoritative underlying exit when the exact opportunity trade exists, realistic/paper option exit, exit reason, and paper duration.
- Performance: `capital_positions.realistic_pnl` as deployable lane P&L; lane return derived from that P&L and its exact realistic entry notional; paper MFE and MAE from the exact execution trade; R multiple only when both realized P&L and a positive initial risk are present.
- Plan: capital initial stop and targets, falling back only to the exact authoritative trade/opportunity plan.
- Management: exact `(position_id, lane)` snapshot count and final snapshot values.
- Provenance: source/version and an explicit list of unavailable fields.

`NULL` remains unavailable. It must not be rendered or aggregated as zero.

## OB, BROAD, and MIRROR/control treatment

OB and BROAD are separate lane projections even when they share the same opportunity or paper execution. Their capital sizing, realistic fills, fees, slippage, risk, and P&L remain separate. The API and aggregate metrics must group by the explicit `capital_positions.lane` value.

MIRROR/control is research-only and must not be mixed into deployable capital metrics. Current `capital_positions` creation is restricted to configured OB/BROAD lanes. If a future persisted control row is exposed, it must be returned under a separate research/control section and never included in overall or lane capital performance.

## Existing APIs and safe additions

Existing read-only FastAPI routes expose recent authoritative trades, active lane positions, and canonical management history at `GET /api/trades/{trade_id}/management`. Recent trade history is not currently a complete lane-specific Journal contract, and current aggregate endpoints are session/capital-readiness views rather than filterable Journal performance.

The minimum safe addition is a read-only `GET /api/trades/history` projection with server-side filters, pagination, and backend-calculated overall/lane metrics. It may reuse the existing management-history endpoint for a selected trade. The route must execute no scan, provider call, strategy evaluation, write, or execution operation.

## Data gaps and non-reconstructable legacy values

- Legacy Streamlit position/recommendation IDs cannot be mapped to canonical identities.
- Historical trades that predate `trade_management_snapshots` have no canonical management timeline.
- Contract type, underlying exit, DTE, plan levels, and excursions are unavailable when the exact persisted source does not contain them.
- Capital realistic P&L and paper realized return are different measures and must retain their provenance.
- An authoritative trade without a lane-specific capital position cannot be presented as canonical OB/BROAD capital performance.
- Historical management must never be joined by symbol; same-symbol and same-opportunity records can legitimately exist in multiple lanes.

Repository searches found symbol filters used for scanner/market reads, but the canonical Active Trades and management paths already use exact IDs. The legacy Streamlit journal relates recommendations by its own integer position ID. The Journal implementation must preserve those boundaries and introduce no symbol-only historical or management join.
