# Intelligence analytics methodology

The intelligence analytics service joins immutable setup snapshots to evolving outcome labels by opportunity ID. It is deterministic, performs no network calls, and describes completed historical observations; it does not claim causal or validated predictive performance.

Eligible return observations require an exit timestamp and finite realized return. Never-triggered, unresolved, malformed, and unjoined records are excluded with explicit reason counts. Eastern trading date and session segment come from the original decision timestamp.

Formulas:

- win rate = wins / (wins + losses); breakeven is excluded from the denominator
- average return and expectancy = arithmetic mean of eligible realized returns
- average winner/loser = arithmetic mean within the positive/negative subsets
- profit factor = sum of positive returns / absolute sum of negative returns; infinity is reported only when winners exist and losses do not
- MFE, MAE, and hold time average only finite available values

The default descriptive minimum is 20 eligible outcomes per group. Smaller groups remain visible but are labeled `INSUFFICIENT_SAMPLE`. Supported breakdown inputs include setup, direction, symbol, regime, sector rank/alignment, session segment, day, rule/confidence score bucket, volume, RSI, risk/reward, exit reason, and source version where captured.

Limitations include changing symbol coverage, incomplete historical features, underlying-return rather than option-return labels, missing time-to-excursion measurements, provider gaps, and non-independent observations. Reports should show sample size and uncertainty and should not promote a model without time-separated validation.
