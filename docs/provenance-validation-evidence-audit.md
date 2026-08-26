# Decision-Provenance Data Model Audit

The canonical ledger is additive, read-only evidence around the existing scanner and capital pipeline. It does not decide trades.

## Persisted chain

`provenance_scan_cycles` records worker/run identity, session and provider state, evaluated symbols, completion, freshness, and whether provenance persistence degraded. `provenance_observations` records one bounded SPY or QQQ decision observation with immutable identity, timestamps, quality, qualification, reasons, scores, indicators, and optional opportunity linkage. `provenance_decision_trade_links` records exact OB/BROAD capital decision identity and its optional exact trade/position identity.

The remaining joins are: observation → `opportunities.id`; decision link → opportunity and observation; trade link → exact authoritative/paper position identity; `trade_management_snapshots` → exact trade, opportunity, and lane; closed trade → its persisted realized outcome. Legacy rows may have no provenance and must return unavailable rather than inferred evidence.

## Integrity invariants

- Scan-cycle, observation, and decision identities are unique, nonempty, and stable.
- Every observation belongs to exactly one real cycle and cannot precede it.
- Canonical observations are limited to SPY and QQQ.
- A qualified observation that produced an opportunity links to that exact opportunity.
- Observation, opportunity, decision, trade, and management symbol/time ordering remains consistent.
- Deployable capital evidence contains only OB or BROAD. MIRROR/control research is never counted as deployable evidence.
- A decision refers to its exact observation and opportunity. An observation/opportunity identity may not be replaced.
- A TAKE that created a position links to the exact trade. A trade cannot have conflicting OB and BROAD ownership.
- Management snapshots join on exact trade, opportunity, and lane and cannot precede entry.
- A closed record has an outcome when the canonical trade representation supports it.
- Degraded provider/provenance states remain visible and are never silently promoted to healthy.
- Missing legacy data, no opportunities, no trades, and no closed trades are explicit availability states, not fabricated failures.

The validator reports broken chains. It never repairs, reclassifies, or replays them.
