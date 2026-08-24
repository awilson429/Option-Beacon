# OB/BROAD real-money-readiness audit

This audit records the pre-framework behavior on `web/react-trade-desk`. It is a
description of existing implementation, not a recommendation to preserve every
historical choice.

## Lane meaning and assignment

- **OB** is the authoritative `TradeOutcome` lifecycle. Scanner results create
  opportunities, underlying-price triggers create `TRADE_ENTERED`, and the
  authoritative trade closes from the existing stop/target/time/EOD lifecycle.
  Results are underlying-price returns. OB has no option contract, quantity,
  buying-power, fee, or capital account model.
- **BROAD** is a downstream PAPER option projection of durable OB
  `TRADE_ENTERED` events. It is not an independent signal generator. A captured
  option is assigned to BROAD through `simulation_profile=BROAD` in the paper
  journal/runtime configuration.
- **MIRROR/control** consumes authoritative lifecycle events into its own
  durable option ledger for research and audit. It is intentionally separate
  from BROAD and is not a deployable-capital lane.

## Pre-framework capital and sizing

- The PAPER executor had one configuration-selected account, defaulting to
  `$5,000`, rather than independent OB and BROAD accounts.
- BROAD defaults were `$250` maximum premium cost per trade, `$1,250` maximum
  deployed premium, five simultaneous positions, and twenty entries per day.
- Quantity was `floor(available premium budget / entry debit)`. It was not sized
  from the planned stop loss, account-risk percentage, or total open risk.
- SAFE, BROAD, and legacy paper positions could coexist in the same persisted
  paper tables. Presentation added provenance labels, but cash was not separated
  into lane-owned accounts.

## Execution, exits, filters, and persistence

- BROAD entry fill was midpoint plus one quarter of the full spread (the
  configurable `entry_fill_toward_ask=0.5` applied to the midpoint-to-ask half).
  Position marks and exits used midpoint. There was no canonical commission,
  fee, exit-slippage, or theoretical-versus-realistic result ledger.
- Existing BROAD exits are fixed option-return rules: `-30%` stop, `+50%`
  target, 120-minute maximum hold, and 15:55 ET/EOD closure. This framework does
  not change those rules.
- Existing rejection gates include execution mode, enablement, market/session,
  stale authoritative entry, entry window, score, symbol allowlist, duplicate
  signal, position/day limits, dollar daily-loss limit, cooldown, quote
  completeness, spread, open interest, volume, premium cost, and buying power.
  Rejections are journaled, but did not contain a canonical capital-decision
  state, account-risk percentage, planned loss, or human explanation.
- OB trades persist in `authoritative_trades` and lifecycle events. BROAD uses
  `paper_execution_trades`, `paper_execution_positions`, and
  `paper_execution_journal`. MIRROR uses separate `mirror_execution_*` tables.

## Accounting and drawdown before this framework

- PAPER daily state was reconstructed from positions entered on the current ET
  date. Daily loss was a fixed `$100`; there was no persisted daily starting
  equity.
- PAPER account equity was reconstructed as configured starting size plus
  realized and midpoint unrealized P&L. Peak deployment and intraday drawdown
  were derived for display, not persisted risk-control state.
- Other analytics calculate post-hoc drawdown, profit factor, expectancy, and
  filter effectiveness. Those reports are not an auditable lane capital ledger.

## React and FastAPI before this framework

- React inferred OB/BROAD/control labels from trade metadata and showed counts
  and realized P&L. It had no independent account equity, open risk, return,
  readiness, or capital-decision presentation.
- `GET /api/trade-desk` aggregated authoritative trades. It did not read the
  paper ledger or expose canonical capital state.

## Historical rather than deliberate differences

1. OB is measured in underlying returns while BROAD is measured in option
   dollars. This comes from separate generations of implementation, not an
   explicit account-comparison policy.
2. Only BROAD had a paper account, and that account could include SAFE/legacy
   rows. OB and BROAD therefore did not own independent dollars.
3. BROAD uses a cost cap and five-position limit; OB has no sizing or account
   limit. These were not normalized lane-risk choices.
4. BROAD entry uses a conservative spread adjustment but exit uses midpoint;
   MIRROR uses conservative entry and exit fills. The asymmetry is historical.
5. BROAD can only evaluate an opportunity after OB enters, so it is a
   participation/filter benchmark rather than a competing signal lane.

The readiness framework is additive. It records independent simulated dollars,
risk decisions, realistic accounting, and evidence status without modifying OB
signal generation, existing exit rules, provider integrations, or brokerage
behavior.
