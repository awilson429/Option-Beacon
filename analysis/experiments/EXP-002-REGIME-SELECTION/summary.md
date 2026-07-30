# Experiment 002 — Regime-Aware Signal Selection

Analysis and shadow mode only. Production decisions remain unchanged.

## Candidate results

| model | retained_alerts | reduction_percent | win_rate | expectancy | profit_factor | stop_first_rate | maximum_drawdown |
| --- | --- | --- | --- | --- | --- | --- | --- |
| MODEL_A_BASELINE | 25 | 0.000 | 28.000 | -0.052 | 0.709 | 72.000 | -2.308 |
| MODEL_B_SYMBOL_SELECTIVE | 13 | 48.000 | 23.077 | -0.101 | 0.477 | 76.923 | -1.808 |
| MODEL_C_DIRECTION_SELECTIVE | 21 | 16.000 | 23.810 | -0.086 | 0.548 | 76.190 | -2.558 |
| MODEL_D_REGIME_SELECTIVE | 3 | 88.000 | 66.667 | 0.147 | 2.769 | 33.333 | -0.250 |
| MODEL_E_TIME_SELECTIVE | 15 | 40.000 | 33.333 | -0.021 | 0.877 | 66.667 | -1.808 |
| MODEL_F_CONTEXT_CONFIRMATION | 24 | 4.000 | 29.167 | -0.040 | 0.770 | 70.833 | -1.954 |
| MODEL_G_SIMPLE_GATES | 10 | 60.000 | 30.000 | -0.056 | 0.681 | 70.000 | -1.250 |
| MODEL_H_SHALLOW_TREE | 20 | 20.000 | 30.000 | -0.040 | 0.769 | 70.000 | -1.558 |

## Conclusion

- Status: **inconclusive**
- Selected candidate: none
- Confidence: low
- Reason: No interpretable context model improved the required metrics while retaining meaningful volume and positive walk-forward evidence.

Sparse subgroup labels are descriptive and are not treated as conclusive.
