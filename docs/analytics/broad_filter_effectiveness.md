# BROAD Filter Effectiveness

## Purpose

This read-only report compares exact persisted authoritative opportunities with
their BROAD disposition, MIRROR trade, and MIRROR intratrade marks. It describes
what happened after BROAD accepted or rejected an opportunity. It does not tune,
recommend, or modify any trading rule.

The report is in **Paper Trading → COMPARE → BROAD FILTER EFFECTIVENESS** and is
collapsed by default. Windows include today, previous persisted session, the last
5 or 10 sessions, and the complete MIRROR experiment. Sessions before
`MIRROR_EXPERIMENT_START_DATE` are excluded.

## Exact joins and definitions

Rows join only through the authoritative `opportunity_id`:

`authoritative opportunity_id → paper source_signal_id → BROAD journal trade_id`

`authoritative opportunity_id → MIRROR opportunity_id → MIRROR mirror_trade_id marks`

There is no symbol/time fuzzy matching and no provider lookup.

- A MIRROR win has realized P&L greater than zero; a loss has realized P&L below zero.
- Net P&L is the sum of persisted realized MIRROR P&L. Open trades are not counted as realized wins or losses.
- Profit factor is gross winning P&L divided by absolute gross losing P&L. It is infinite when wins exist without losses and unavailable when neither exists.
- MFE is the maximum persisted telemetry return; MAE is the minimum. Missing historic marks remain unavailable.
- Peak return is the persisted intratrade high-water return. Giveback is `peak return - final return`, floored at zero, and is reported only when the trade was profitable at some point.
- A profitable-to-final-loser reversal has peak return above zero and final realized return below zero.
- Midpoint P&L uses persisted entry and exit midpoints. Modeled fill drag is midpoint P&L minus actual persisted MIRROR P&L.
- Peak capital is the largest simultaneous sum of persisted entry debits using open/exit times. Cumulative debit is total turnover and is intentionally separate.
- Return on peak capital and return on cumulative debit divide net realized P&L by those respective denominators.

An authoritative win is an underlying-price outcome. It does not guarantee a
profitable option expression because spread, entry/exit fills, strike, DTE,
convexity, and timing can produce a different MIRROR outcome.

## Effectiveness labels

Classification thresholds are centralized in `broad_filter_effectiveness.py`:

- Fewer than 10 realized MIRROR trades: **INSUFFICIENT DATA**.
- At least 10, negative net P&L, and profit factor no greater than 0.80: **PROTECTIVE**.
- At least 10, positive net P&L, and profit factor at least 1.25: **COSTLY FILTER**.
- Every other sufficiently sampled result: **NEUTRAL / INCONCLUSIVE**.

These transparent descriptive labels are not production recommendations. A
filter can correlate with an outcome because of market regime, selection effects,
or small samples. Production thresholds must never be automatically changed from
this report.

## Coverage and limitations

Every reason displays its sample size and flags low samples. Telemetry, delta,
and IV coverage are shown explicitly. Older sessions without marks display
`TELEMETRY UNAVAILABLE`; MFE and MAE are never inferred. Delta or IV absent from
persisted rows displays as not persisted and is never fetched retroactively.

All calculations occur in memory from existing repository reads. The dashboard
does not create analytics tables, write execution rows, update marks, or call a
market-data provider.
