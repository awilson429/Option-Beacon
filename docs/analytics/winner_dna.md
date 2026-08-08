# Winner DNA / Entry Attribution

## Goal and scope

Winner DNA is a read-only research view in Developer Tools. It uses immutable,
point-in-time authoritative entry snapshots and completed authoritative outcomes,
then exact-joins BROAD dispositions and MIRROR outcomes by opportunity ID. It
describes associations; it cannot change scanning, scores, thresholds, entries,
contracts, fills, exits, or risk controls.

## Feature definitions and coverage

The entry snapshot currently supports confidence/quality score, symbol, direction,
setup, entry price, relative volume, RSI, VWAP relationship and distance, EMA 9/21
and EMA slope, ATR, candle body, breakout distance, trend alignment, session,
market regime, and sector context where the scanner persisted them. Time of day,
EMA relationship, and SPY/QQQ agreement are derived solely from persisted entry
fields. Missing fields remain missing. Trigger distance, ATR-normalized trigger
distance, MACD, support/resistance proximity, candidate age, and prior scan count
are not reconstructed. Delta and IV are not part of the authoritative snapshot.

The UI displays per-feature coverage plus MIRROR outcome and mark coverage. A zero
means unavailable, not a measured zero.

## Outcome buckets

- **Flat / noise:** authoritative return within ±0.10%.
- **Loser:** authoritative return below -0.10%.
- **Large winner:** positive return above the sample's 75th percentile of returns greater than 0.10%.
- **Small winner:** remaining positive return above 0.10%.

The computed large-winner boundary is displayed with every report. The percentile
is deterministic and adapts to the persisted distribution; the flat/noise band is
a centralized descriptive constant.

MIRROR translation is classified separately as Auth Win/MIRROR Win, Auth
Win/MIRROR Loss, Auth Loss/MIRROR Win, or Auth Loss/MIRROR Loss. Trades without a
realized MIRROR outcome remain unavailable.

## Expectancy and capital

Expectancy is the arithmetic mean authoritative return, not win rate. Profit
factor is gross positive return divided by absolute gross negative return. The
report also shows average winner, average loser, and median return. MIRROR sections
use persisted realized P&L and debit. Peak capital is the maximum simultaneous
entry debit reconstructed from persisted MIRROR open and exit-quote times;
cumulative debit is not substituted for peak capital.

## Binning and validation

Continuous features use fixed, documented bins for confidence/score, relative
volume, and RSI. The report evaluates only four predeclared two-factor patterns;
it does not brute-force rule combinations. Patterns require at least 10 total,
five older training, and three newer validation trades. The oldest 70% train and
the newest 30% validate, with no random shuffle.

- **Promising:** adequately sampled with positive train and validation expectancy.
- **Unstable:** adequately sampled but not positive in both periods.
- **Insufficient data:** below any sample requirement.

The report also shows sessions, distinct symbols, CALL/PUT direction balance, and
regime coverage. A symbol representing more than 50% of eligible trades triggers a
concentration warning.

## Interpretation limits

Feature effects are descriptive correlations, not causal estimates. Small bins,
multiple comparisons, regime changes, and symbol concentration can create false
patterns. An authoritative directional win can still lose as an option because
the underlying move is too small relative to spread, fill drag, debit, DTE, or
timing. This analytics layer deliberately does not auto-tune production. Any
future strategy change requires separate human review, prospective validation,
and an explicitly authorized implementation.
