# OB/BROAD simulated-capital readiness

This framework is PAPER/SIMULATION only. It has no brokerage credentials,
order submission, order-management endpoints, or controls that enable live
execution. OB signal generation and all existing OB/BROAD exit rules are
unchanged.

## Independent default accounts

| Setting | OB | BROAD |
| --- | ---: | ---: |
| Starting capital | $25,000 | $25,000 |
| Risk per trade | 0.50% | 0.25% |
| Maximum total open risk | 1.50% | 1.50% |
| Maximum positions | 3 | 6 |
| Maximum daily loss | 2.00% | 2.00% |

All values are environment-configurable with `OB_` or `BROAD_` prefixes. For
example: `OB_STARTING_CAPITAL`, `BROAD_RISK_PER_TRADE_PCT`,
`OB_MAX_TOTAL_OPEN_RISK_PCT`, and `BROAD_MAX_CONCURRENT_POSITIONS`.

Drawdown defaults are 5% warning, 8% reduced risk (50% of normal new-trade
risk), and 12% halt of new entries. Existing positions are not liquidated by a
daily-loss or drawdown entry lock.

## Position sizing and execution

The engine calculates permitted risk as current equity multiplied by the lane
risk percentage, then caps it by remaining total-open-risk capacity. Planned
loss per contract includes the realistic entry, conservative stop fill,
100-share contract multiplier, and round-trip fees. Quantity is always rounded
down and is also capped by available lane cash. One contract is never forced if
it exceeds the risk budget.

The default simulated execution model uses:

- theoretical entry/exit at midpoint;
- realistic entry at midpoint plus 25% of the full bid/ask spread;
- realistic exit at midpoint minus 25% of the full spread;
- configurable `$0.65` commission/fee per contract per side.

Theoretical P&L, realistic P&L, fees, and slippage are persisted separately.
Realistic simulated P&L is primary for account equity and readiness.

## Canonical records

- `lane_capital_state`: latest independent account/equity/risk/readiness state.
- `capital_decisions`: every accepted or rejected lane allocation decision.
- `capital_positions`: lane-owned option quantity, risk, capital, marks, and P&L.
- `capital_risk_events`: drawdown-state transitions.
- `capital_equity_history`: auditable equity/deployment series.
- `capital_daily_state`: ET-session starting equity, P&L, and entry lock.

Rejected decisions may later receive hypothetical outcomes, but those fields
never feed account equity or actual simulated-account P&L.

## Readiness thresholds

Readiness is informational and never enables execution.

- `NOT_READY`: missing risk-control coverage, less than 80% data completeness,
  or non-positive realistic expectancy once at least 20 trades exist.
- `EARLY_RESEARCH`: fewer than 30 trades or 10 sessions, with basic coverage.
- `DEVELOPING`: at least 30 trades/10 sessions, positive realistic expectancy,
  profit factor above 1, maximum drawdown at most 12%, at least 90% data
  completeness, and at least 80% execution evidence.
- `PAPER_VALIDATED`: at least 100 trades/30 sessions, profit factor at least
  1.20, drawdown at most 10%, at least 95% data/execution evidence, and evidence
  across at least three regimes.
- `LIVE_CANDIDATE`: at least 250 trades/60 sessions, profit factor at least
  1.30, drawdown at most 8%, at least 98% data/execution evidence, four regimes,
  and measured stability across regimes.

The current implementation deliberately reports no regime count until canonical
regime attribution is persisted, preventing premature promotion.

## Known coupling

The existing option quote lifecycle belongs to BROAD paper execution. The
framework can independently size OB and BROAD from one immutable contract
snapshot and can maintain different lane-owned quantities once BROAD opens the
shared quote lifecycle. If a legacy BROAD filter prevents that lifecycle from
opening, OB records `INDEPENDENT_OPTION_LIFECYCLE_UNAVAILABLE` instead of
inventing marks. A future worker change should create a shared, lane-neutral
quote lifecycle before considering real capital.
