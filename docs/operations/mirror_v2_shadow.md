# MIRROR V2 forward shadow

MIRROR V2 is a research-only, paper-only lane. It is disabled by default and is enabled with
`OPTIONBEACON_MIRROR_V2_SHADOW_ENABLED=true`. It contains no broker or order-submission adapter and
does not replace or mutate MIRROR CONTROL.

The optional `MIRROR_V2_EXPERIMENT_START_DATE=YYYY-MM-DD` pins the first eligible forward session.
If omitted on first enablement, the worker persists the current Eastern session date and reuses it
after restarts. Entries before that boundary are ignored rather than rewritten as V2 history.

For each new authoritative `TRADE_ENTERED` opportunity, V2 independently evaluates the existing
Tradier chain snapshot. The worker shares a one-cycle read-through chain cache with CONTROL, so
running both lanes does not duplicate expiration or chain requests. CONTROL keeps its existing
contract-selection and authoritative-exit behavior.

V2 normalizes all contracts for the authoritative CALL/PUT direction and persists the reasonably
available alternatives. It deterministically selects the candidate with, in order: moneyness nearest
spot, narrowest percentage spread, greatest open interest, greatest volume, and option symbol.
The selected candidate must have a non-inverted bid/ask, be within 0.5% of spot, and have a spread
no greater than 12.5%. Missing quotes fail closed. Confidence is not a V2 gate. Contracts outside
the near-ATM band—including clearly expensive ITM selections—are not eligible.

Accepted positions use the existing conservative quarter-spread fill model. Every observed quote
is persisted without interpolation. The first observed return at or above +10% exits as `TARGET_10`;
the first at or below -10% exits as `STOP_10`. If neither occurs before the authoritative trade
closes, the next usable quote closes the V2 position as `AUTHORITATIVE_EXIT`. Quote failures preserve
the open position for retry.

Four additive, idempotently created tables provide independent persistence:

- `mirror_v2_shadow_trades`: one exact-ID TAKE/REJECT decision and complete lifecycle per opportunity.
- `mirror_v2_shadow_marks`: observed quotes, returns, P&L, MFE, and MAE.
- `mirror_v2_shadow_runtime_state`: worker enablement and cycle health.
- `mirror_v2_shadow_comparisons`: authoritative, CONTROL, and V2 forward attribution.

The Paper Trading workspace labels the baseline `MIRROR CONTROL` and shows V2 in a neighboring
`MIRROR V2 SHADOW` subsection marked `RESEARCH ONLY`. It never promotes V2 automatically.
