# Experiment 003 — Signal Funnel, Data Expansion, and Score Calibration

Research and shadow logging only. Production scoring and threshold 90 are unchanged.

## Data availability

- SPY: 4680 source bars, 2026-05-04T09:30:00-04:00 through 2026-07-29T15:55:00-04:00; normalized SHA-256 `39457a03e3de6954c0b5ed02e29120c8c1b53aeacfc1398197a923f331a78a62`
- QQQ: 4680 source bars, 2026-05-04T09:30:00-04:00 through 2026-07-29T15:55:00-04:00; normalized SHA-256 `8c038bc496d4175e0172e15d3f4c8e593a02fdf409d1fda73868f65a99d0d18e`

## Funnel

- RAW CANDIDATE: 7462 passed of 9256 evaluated
- STRUCTURE DETECTED: 7462 passed of 7462 evaluated
- DIRECTION ASSIGNED: 7366 passed of 7462 evaluated
- INDICATORS AVAILABLE: 7366 passed of 7366 evaluated
- BASE CONDITIONS PASSED: 7366 passed of 7366 evaluated
- SCORE CALCULATED: 7366 passed of 7366 evaluated
- SCORE THRESHOLD PASSED: 32 passed of 7366 evaluated
- LIFECYCLE ELIGIBLE: 25 passed of 32 evaluated
- TRADE PLAN VALID: 25 passed of 25 evaluated
- FINAL ALERT: 25 passed of 25 evaluated

## Research thresholds

| threshold | retained_candidates | alerts_per_day | win_rate | expectancy | profit_factor | maximum_drawdown | stop_first_rate | target_1_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 60 | 926 | 15.433 | 32.829 | -0.016 | 0.903 | -33.988 | 64.579 | 23.758 |
| 65 | 592 | 9.867 | 32.601 | -0.015 | 0.912 | -21.008 | 65.709 | 25.000 |
| 70 | 351 | 6.052 | 34.188 | -0.006 | 0.962 | -11.045 | 64.672 | 26.211 |
| 75 | 218 | 4.192 | 36.239 | 0.016 | 1.100 | -5.779 | 62.385 | 28.899 |
| 80 | 133 | 2.956 | 35.338 | 0.000 | 1.000 | -5.659 | 63.910 | 27.820 |
| 85 | 81 | 2.250 | 34.568 | -0.013 | 0.921 | -3.750 | 64.198 | 27.160 |
| 90 | 32 | 1.600 | 25.000 | -0.072 | 0.615 | -3.058 | 75.000 | 21.875 |
| 95 | 7 | 1.167 | 14.286 | -0.143 | 0.333 | -1.500 | 85.714 | 14.286 |

## Conclusion

- Score predictive: False
- Threshold 90 assessment: **inconclusive**
- Reason: Ranking, threshold, and component results are not sufficiently stable across chronological partitions to justify a production change.

Underlying-price movements are used throughout; these are not option returns.
