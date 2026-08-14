# FILTERED execution experiment

`FILTERED` is an isolated PAPER-only lane evaluated after BROAD and MIRROR in
the existing scanner cycle. It is enabled by default and can be disabled with
`OPTIONBEACON_FILTERED_ENABLED=false`.

- Population: persisted BROAD decisions explicitly labeled `BROAD`.
- Enforced gate: MIRROR's persisted entry spread, `(ask-bid)/midpoint*100`, must
  be at most 20%. Exactly 20% is eligible.
- Contract and fills: copied from MIRROR; no selection or fill rules change.
- Provider impact: zero incremental chain or quote calls. FILTERED consumes the
  persisted MIRROR contract and mark stream after the MIRROR cycle.
- Signal age: observed and bucketed (`LE_60`, `61_120`, `121_180`, `181_300`,
  `GT_300`) but never blocks entry.
- Loss caps: -30% and -45% are ordered-mark shadow counterfactuals. The single
  actual FILTERED position follows the unchanged authoritative/MIRROR lifecycle.
- Governance: fewer than 30 closed trades is `INSUFFICIENT DATA`; 30-49 is
  descriptive only; 50+ still requires chronological validation before any
  promotion.

Persistence is additive in `filtered_execution_trades` and
`filtered_execution_runtime_state`. Identity is a SHA-256 of the immutable
opportunity ID and `FILTERED`; the database also enforces one row per
opportunity. This lane never places a live order.
