# Current scoring and decision-path audit

OptionBeacon's production decision path remains rule based. Market candles are fetched by the configured provider, indicators are calculated before `score_candle`, qualifying scanner results are converted into trade plans, and `process_scanner_result` projects candidate/open/closed state into the authoritative repository. Dashboard ranking is presentation logic over the existing score; it is not a calibrated probability.

## Score construction

`optionbeacon_strategy.score_candle` caps bullish and bearish totals at 100 and selects a directional setup only when its score is both greater than the opposite score and at least 90. Otherwise it emits WATCHLIST. Contributions are:

| Category | Condition | Points |
|---|---|---:|
| Trend | price vs EMA20 | 6 |
| Trend | price vs EMA50 | 6 |
| Trend | price vs EMA200 | 6 |
| Trend | ordered EMA20/50/200 alignment | 7 |
| Momentum | RSI 52–70 bullish or 30–48 bearish | 7 |
| Momentum | MACD vs signal | 7 |
| Momentum | expanding same-direction MACD histogram | 6 |
| Volume | relative volume ≥2.0 / ≥1.4 / ≥1.1 | 10 / 7 / 4 |
| Volume | volume >125% of prior candle | 5 |
| Volume | volume above 20-period average | 5 |
| Volatility | ATR above its 20-period average | 8 |
| Volatility | same-direction range expansion | 4 |
| Volatility | candle body >35% ATR | 3 |
| Price action | 20-bar buffered breakout/breakdown | 12 |
| Price action | price vs VWAP | 4 |
| Price action | 3-bar buffered breakout/breakdown | 4 |

The configured buffers are 1.0003/0.9997, relative-volume threshold is 1.40, initial stop is 0.25%, initial target is 0.50%, and breakeven trigger is 0.40%. These values are unchanged.

## Hard filters and lifecycle

- Trade time is 09:45 through before 15:00 in the timestamp supplied to the scorer.
- A directional production signal requires score ≥90 and dominance over the opposing score.
- Candidate recording has separate directional/actionability rules in `scanner_result_to_trade_outcome`.
- Entry requires a finite confidence ≥65, an unentered/unclosed candidate, an allowed intraday entry time, and a direction-aware entry-price crossing.
- Authoritative exits remain stop, highest target reached, maximum hold, and end-of-day. Closed records never reopen.

## Persisted and lost information

Before this foundation, `TradeOutcome` persisted identity, time, symbol, direction, setup, confidence, entry/stop/three targets, entry/exit times and reason, MFE, MAE, realized underlying return, and hold minutes. Many scanner-time indicator values, individual score contributions, provider quality, market/sector context, and user explanation were not retained. Time-to-MFE and time-to-MAE were not measured and cannot be reconstructed from final records; the new label explicitly marks them missing rather than inventing values.

The immutable intelligence snapshot now stores all available decision-time values and explicit missing-feature flags. It never overwrites its first value. Outcome labels evolve separately as authoritative state changes.

## Bias and semantic risks

- Features must come only from the scanner result at its timestamp; later candles must not populate the immutable snapshot.
- Training and validation must split by time, never randomly mix future outcomes into past training.
- Never-triggered and malformed outcomes require explicit exclusion from return analytics.
- Symbol coverage changes can create survivorship bias; analytics reports exclusions and sample sizes.
- The current `confidence` is a setup/rule score, not a probability. Trade-plan confidence may include deterministic penalties and therefore can differ from the raw bullish/bearish scanner score.
- Dashboard ordering can differ from entry eligibility because ranking, qualification, and lifecycle are separate concerns.

The shadow calibration and Ranking V2 code cannot affect production while their feature flag is disabled.
