# Experiment 001 — False-Breakout Protection

Production signals, scoring, stops, targets, journals, and positions are unchanged.

## Model comparison

| model | active_entries | alert_reduction_percent | win_rate | expectancy | profit_factor | stop_first_rate | quick_invalidation_rate | target_1_rate | average_entry_delay_minutes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| MODEL_A_BASELINE | 25 | 0.000 | 28.000 | -0.052 | 0.709 | 72.000 | 32.000 | 24.000 | 0.000 |
| MODEL_B_CLOSE_ONLY | 25 | 0.000 | 28.000 | -0.052 | 0.709 | 72.000 | 32.000 | 24.000 | 0.000 |
| MODEL_C_CLOSE_VOLUME | 24 | 4.000 | 29.167 | -0.044 | 0.751 | 70.833 | 33.333 | 25.000 | 0.000 |
| MODEL_D_CLOSE_EXTENSION | 3 | 88.000 | 0.000 | -0.250 | 0.000 | 100.000 | 33.333 | 0.000 | 0.000 |
| MODEL_E_CLOSE_VOLUME_EXTENSION | 2 | 92.000 | 0.000 | -0.250 | 0.000 | 100.000 | 50.000 | 0.000 | 0.000 |
| MODEL_F_GAP_AWARE | 15 | 40.000 | 40.000 | 0.007 | 1.050 | 60.000 | 20.000 | 33.333 | 5.000 |
| MODEL_G_RETEST_HOLD | 8 | 68.000 | 37.500 | -0.014 | 0.923 | 62.500 | 12.500 | 37.500 | 11.875 |
| MODEL_H_HYBRID | 0 | 100.000 | — | — | — | — | — | — | — |

## Conclusion

- Status: **inconclusive**
- Recommended candidate: none
- Confidence: low
- Reason: No candidate combined sufficient retained alerts with positive out-of-sample walk-forward evidence.

Hourly history was not merged into these five-minute headline metrics.
