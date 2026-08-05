# MIRROR PAPER experiment

## Purpose

MIRROR is a Railway-owned, simulated execution experiment that runs alongside the
existing BROAD PAPER portfolio. It answers: what option-contract cash flow, P&L,
and capital would have resulted if one contract were attempted for essentially
every authoritative OptionBeacon `TRADE_ENTERED` lifecycle?

MIRROR is not a signal strategy, portfolio recommendation, brokerage account, or
replacement for BROAD. Streamlit is read-only and cannot enable or execute it.

## Exact rules

Each authoritative entry after the configured experiment start receives exactly
one durable disposition: `MIRROR_OPENED`, `MIRROR_NO_VALID_CONTRACT`,
`MIRROR_QUOTE_UNAVAILABLE`, `MIRROR_PROVIDER_FAILURE`, or `MIRROR_STALE_ENTRY`.
Duplicate opportunity IDs are idempotent across restarts.
Malformed authoritative source payloads are isolated per entry as
`MIRROR_AUTHORITATIVE_DATA_FAILURE`; they cannot abort disposition of other entries.

MIRROR retains only execution-integrity gates: an exact authoritative ID, valid
CALL/PUT direction, listed expiration, deterministic valid contract, positive
non-inverted bid/ask, conservative fill, entry-age protection, provider-failure
handling, durable persistence, and Railway lock ownership. Missing or malformed
quotes are never fabricated.

MIRROR deliberately does not use Beacon score, BROAD score, liquidity thresholds,
trade/day limits, open-position limits, daily-loss or consecutive-loss halts,
cooldowns, buying power, allocation sizing, or deployed-capital ceilings. Low
open interest, zero volume, and spreads above 20% are recorded rather than rejected
when the quote remains executable.

## Contract and fill methodology

MIRROR reuses OptionBeacon's deterministic listed-expiration and contract ranking:
approximately 0.50 absolute delta when available, then spread, open interest,
volume, strike, and symbol; otherwise nearest strike with the same deterministic
tie-breakers. The selected symbol is immutable.

Quantity is exactly one and the multiplier is 100. Entry fill is midpoint plus
25% of the midpoint-to-ask distance. Exit fill is midpoint minus 25% of the
midpoint-to-bid distance. The recorded algorithm is
`MIRROR_CONSERVATIVE_QUARTER_SPREAD_V1`. Entry debit, quote, spread dollars and
percent, open interest, volume, timestamps, and contract identity are durable.

## Authoritative exits

Only authoritative `TRADE_CLOSED` controls a MIRROR exit. BROAD's -30% stop, +50%
target, max hold, EOD option rule, and risk exits do not control MIRROR. The
authoritative reason and time are preserved. If no executable exit quote exists,
the position becomes `MIRROR_EXIT_PENDING`; later worker cycles retry the same
immutable contract. The eventual executable quote time is stored separately.

## Persistence and ownership

The additive tables are `mirror_execution_trades`, `mirror_execution_journal`, and
`mirror_execution_runtime_state`. They do not share BROAD rows, so BROAD and MIRROR
can independently reject/open the same authoritative opportunity. Initialization
uses idempotent `CREATE TABLE IF NOT EXISTS`; no historical data is deleted or
rewritten. The locked Railway scanner is the only writer.

Structured events include `mirror_cycle_started`, `mirror_authoritative_handoff`,
`mirror_entry_opened`, `mirror_entry_unexecutable`, `mirror_position_updated`,
`mirror_authoritative_exit_received`, `mirror_trade_closed`,
`mirror_exit_pending`, and `mirror_cycle_completed`.

## Capital and drawdown

There is no artificial account cap. Current capital is the sum of entry debits for
open/pending positions. Peak capital is reconstructed from actual open and close
times as the maximum simultaneous sum of entry debits. Cumulative gross debit is
also reported. Realized P&L is actual simulated exit value minus entry debit;
unrealized P&L uses the conservative liquidation mark.

Realized maximum drawdown is the largest decline from the cumulative realized-P&L
high-water mark. It is shown in dollars and can be interpreted relative to peak
capital required; it is never divided by a fabricated starting balance. Mark-to-
market observations are stored where quotes exist, but this implementation does
not claim a continuous intracycle equity curve.

Capital-budget scenario replay is intentionally omitted in the first version.
Accurate reconstruction requires an explicit policy for overlapping entries and
released capital; silently choosing one could turn analysis into a new strategy.
The durable sequence contains everything required for a separately reviewed model.

## Dashboard and experiment interpretation

Paper Trading presents a compact authoritative `MIRROR ACTIVE`, `WAITING`,
`DEGRADED`, or `DISABLED` pill plus BROAD, MIRROR, and COMPARE sections. Status is
read from shared worker state, never Streamlit environment defaults. The comparison
labels authoritative returns as underlying percentages and BROAD/MIRROR results as
option dollars. Pre-experiment history is shown as `MIRROR NOT RUNNING`; no historic
fills are fabricated.

Set `MIRROR_EXPERIMENT_START_DATE=YYYY-MM-DD` to bound the clean experiment without
deleting older rows. Daily/session analysis should use Eastern trading dates. A
two-week sample can describe participation, execution failures, spreads, debit,
capital overlap, and observed option P&L. It cannot establish durable edge,
statistical significance, future returns, scalability, or live fill quality, and
should not be annualized by default.

## Railway configuration

MIRROR defaults off. Enable it only on the Railway writer:

```text
OPTIONBEACON_MIRROR_ENABLED=true
MIRROR_EXPERIMENT_START_DATE=YYYY-MM-DD
```

The date is recommended but optional. No Streamlit lifecycle variable or toggle is
required. No real brokerage-order path exists.
