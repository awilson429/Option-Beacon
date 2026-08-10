# Option Translation Autopsy

Option Translation Autopsy is a read-only forensic analysis of why an authoritative underlying call did or did not become a profitable MIRROR option trade. It is not a strategy optimizer and does not change entries, exits, contracts, fills, sizing, or risk.

## Identity and data

Rows join only by immutable identity: authoritative `opportunity_id` to MIRROR `opportunity_id`, then MIRROR `mirror_trade_id` to `mirror_execution_marks`. Unmatched MIRROR attempts are excluded and counted. The analysis uses persisted intelligence snapshots/outcomes, projected MIRROR trade fields, and marks. It makes no provider calls and never reconstructs old quotes from current data.

The UI is collapsed and query-on-demand. A run has a 7/30/90-day UTC lower bound, a bounded trade count, exact-ID MIRROR reads, explicit column projections, and a bounded raw-mark read. Raw marks load only after **Run Option Translation Autopsy** is pressed.

## Formulas and buckets

- MIRROR return and P&L use persisted realized fields.
- MFE/MAE are the maximum/minimum persisted mark returns. Giveback is `max(0, peak return - final return)`.
- Entry fill drag is `(entry fill - entry midpoint) × quantity × multiplier`; exit drag is `(exit midpoint - exit fill) × quantity × multiplier`. Unknown midpoint fields stay unavailable.
- Timing points use the nearest persisted mark within ±45 seconds of +1/+2/+3/+5/+10/+15/+30 minutes. Missing points remain null; there is no interpolation. "Materially negative" means a persisted mark return at or below -5%.
- Underlying magnitude: 0–0.10%, 0.10–0.25%, 0.25–0.50%, 0.50–1.00%, and >1.00%.
- Entry spread: ≤2%, 2–5%, 5–10%, 10–20%, and >20%.
- DTE: 0, 1, 2–4, 5–9, and 10+.
- Moneyness uses persisted entry underlying and strike. Within ±0.5% is ATM/near-ATM; signed intrinsic distance determines ITM or OTM.
- Peak capital is the maximum chronological sum of deployed debits using persisted open/close timestamps.

## Attribution and simulations

Each eligible attempt occupies exactly one outcome-matrix row. Causal labels distinguish `SUPPORTED`, `LIKELY`, `INCONCLUSIVE`, and `DATA UNAVAILABLE`. A supported label requires direct persisted evidence; IV and delta display `NOT PERSISTED` and are not inferred.

Selective simulations use only fixed, explainable candidates: exclude >20% spreads, exclude ≤0.10% authoritative winners, exclude 0DTE, or require confidence ≥70. Exit simulations use deterministic first-hit processing of persisted marks for fixed take-profit, trailing, breakeven, and maximum-hold variants. No missing price is interpolated.

Every candidate is ordered chronologically: oldest 70% development and newest 30% validation. A label cannot be `PROMISING` without at least 20 eligible trades, 10 development trades, six validation trades, and validation improvement over control on multiple metrics. Otherwise results are `UNSTABLE`, `NO IMPROVEMENT`, or `INSUFFICIENT DATA`.

## Limitations

Sparse marks can miss intraminute extrema or first hits. Persisted conservative marks reflect the MIRROR fill model, not executable historical quotes. Intelligence snapshot coverage may exclude older authoritative trades. Corporate events, historical IV, delta, Greeks, and theta cannot be attributed unless they were persisted. Symbol concentration above 30% and samples below 20 are flagged.

These diagnostics identify associations and supported path facts; they do not establish market causality or constitute a production strategy recommendation. Any production change requires a separate task, larger samples, prospective validation, and explicit risk review.
