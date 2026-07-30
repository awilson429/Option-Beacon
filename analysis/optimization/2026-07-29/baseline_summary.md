# OptionBeacon Current-System Baseline

Generated: 2026-07-29T20:37:33.443655-04:00

This report is analysis-only. Production decisions, thresholds, stops, targets, and UI behavior are unchanged.

## Data availability

- SPY / 60-trading-days / 5m: available, 4680 bars, 2026-05-04T09:30:00-04:00 through 2026-07-29T15:55:00-04:00
- SPY / 6-months / 60m: available, 868 bars, 2026-01-30T09:30:00-05:00 through 2026-07-29T15:30:00-04:00
- SPY / 12-months / 60m: available, 1749 bars, 2025-07-30T09:30:00-04:00 through 2026-07-29T15:30:00-04:00
- QQQ / 60-trading-days / 5m: available, 4680 bars, 2026-05-04T09:30:00-04:00 through 2026-07-29T15:55:00-04:00
- QQQ / 6-months / 60m: available, 868 bars, 2026-01-30T09:30:00-05:00 through 2026-07-29T15:30:00-04:00
- QQQ / 12-months / 60m: available, 1749 bars, 2025-07-30T09:30:00-04:00 through 2026-07-29T15:30:00-04:00

## Overall

| total_alerts | alerts_per_day | win_rate | expectancy | profit_factor | maximum_drawdown | average_mfe | average_mae | target_1_rate | stop_first_rate | late_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 25 | 0.417 | 28.000 | -0.052 | 0.709 | -2.058 | 0.249 | -0.371 | 24.000 | 72.000 | 36.000 |

## By symbol

| group | total_alerts | win_rate | expectancy | profit_factor | maximum_drawdown |
| --- | --- | --- | --- | --- | --- |
| QQQ | 17 | 29.412 | -0.029 | 0.833 | -1.250 |
| SPY | 8 | 25.000 | -0.101 | 0.461 | -1.308 |

## By direction

| group | total_alerts | win_rate | expectancy | profit_factor | maximum_drawdown |
| --- | --- | --- | --- | --- | --- |
| Bearish | 14 | 21.429 | -0.089 | 0.545 | -1.500 |
| Bullish | 11 | 36.364 | -0.005 | 0.967 | -1.000 |

## By setup

| group | total_alerts | win_rate | expectancy | profit_factor | maximum_drawdown |
| --- | --- | --- | --- | --- | --- |
| BEARISH SETUP | 14 | 21.429 | -0.089 | 0.545 | -1.500 |
| BULLISH SETUP | 11 | 36.364 | -0.005 | 0.967 | -1.000 |

## By hour

| group | total_alerts | win_rate | expectancy | profit_factor | maximum_drawdown |
| --- | --- | --- | --- | --- | --- |
| 09:00 | 3 | 33.333 | 0.000 | 1.000 | -0.500 |
| 10:00 | 8 | 37.500 | -0.007 | 0.954 | -1.250 |
| 12:00 | 1 | 0.000 | -0.250 | 0.000 | -0.250 |
| 13:00 | 7 | 28.571 | -0.036 | 0.800 | -0.750 |
| 14:00 | 6 | 16.667 | -0.125 | 0.400 | -0.750 |

## By confidence bucket

| group | total_alerts | win_rate | expectancy | profit_factor | maximum_drawdown |
| --- | --- | --- | --- | --- | --- |
| 90-94 | 18 | 33.333 | -0.017 | 0.897 | -1.000 |
| 95-100 | 7 | 14.286 | -0.143 | 0.333 | -1.500 |

## By regime

| group | total_alerts | win_rate | expectancy | profit_factor | maximum_drawdown |
| --- | --- | --- | --- | --- | --- |
| bullish trend | 1 | 0.000 | -0.250 | 0.000 | -0.250 |
| high-volatility expansion | 3 | 66.667 | 0.147 | 2.769 | -0.250 |
| opening gap continuation | 8 | 25.000 | -0.062 | 0.667 | -0.750 |
| opening gap reversal | 13 | 23.077 | -0.077 | 0.600 | -2.000 |

## By requested period

| group | total_alerts | win_rate | expectancy | profit_factor | maximum_drawdown |
| --- | --- | --- | --- | --- | --- |
| 12-months | 4 | 50.000 | 0.125 | 2.000 | -0.500 |
| 6-months | 2 | 50.000 | 0.125 | 2.000 | -0.250 |
| 60-trading-days | 25 | 28.000 | -0.052 | 0.709 | -2.058 |

## By timeframe

| group | total_alerts | win_rate | expectancy | profit_factor | maximum_drawdown |
| --- | --- | --- | --- | --- | --- |
| 5m | 25 | 28.000 | -0.052 | 0.709 | -2.058 |
| 60m | 6 | 50.000 | 0.125 | 2.000 | -0.500 |

## By higher-timeframe alignment

| group | total_alerts | win_rate | expectancy | profit_factor | maximum_drawdown |
| --- | --- | --- | --- | --- | --- |
| aligned | 24 | 29.167 | -0.044 | 0.751 | -1.808 |
| partially aligned | 1 | 0.000 | -0.250 | 0.000 | -0.250 |

## Failure modes

| failure_mode | frequency | average_return |
| --- | --- | --- |
| false breakout | 18 | -0.250 |
| gap distortion | 16 | -0.250 |
| signal reversed immediately | 8 | -0.250 |
| momentum exhaustion | 7 | -0.187 |
| entered after extension | 6 | -0.176 |
| time-of-day weakness | 5 | -0.250 |
| low-volume breakout | 2 | -0.250 |
| VWAP conflict | 1 | -0.250 |
| timeout/no follow-through | 1 | 0.192 |
| alert arrived late | 0 | — |
| low liquidity | 0 | — |
| market regime mismatch | 0 | — |
| opposing higher-timeframe trend | 0 | — |
| poor risk/reward | 0 | — |
| signal never confirmed | 0 | — |
| stop too tight | 0 | — |
| target unrealistic | 0 | — |
| too close to support/resistance | 0 | — |
| weak candle body | 0 | — |
