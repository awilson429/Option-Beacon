# OptionBeacon Experiment 003 — Shareable GPT Summary

## Project state

- Repository: `awilson429/Option-Beacon`
- Branch: `develop`
- Starting SHA: `900f02ca85b9d0275395fab0281511b4c2bfebbd`
- Completed SHA: `c9d4557fe215d5fd817fc75c36fb9ed76adef5e6`
- Safety branch: `backup/pre-signal-funnel-experiment`
- Main remained unchanged at: `3f0aa5fd53fe5b5d83d91c1aebd0be63e9fe9330`
- No merge to `main` occurred.

## Objective

Experiment 003 expanded OptionBeacon research beyond final score-90 alerts. It:

1. Audited available market-data providers.
2. Created a reproducible normalized dataset pipeline.
3. Replayed the complete signal-generation funnel.
4. Evaluated all directional candidates before the production score gate.
5. Audited score calibration and scoring components.
6. Compared research-only score thresholds.
7. Separated entry quality from exit-policy performance.
8. Estimated additional sample requirements.
9. Added isolated, bounded shadow funnel logging.

Production scoring, threshold 90, entries, stops, targets, alerts, journals,
positions, UI, and navigation were not changed.

## Executive conclusion

- Is the score meaningfully predictive? **No**
- Do higher scores consistently outperform lower scores? **No**
- Is production threshold 90 justified? **Inconclusive**
- Recommended production change: **None**

Threshold 75 had the best in-sample result, but its expectancy became negative
in both chronological walk-forward validation folds. Production threshold 90
therefore remains unchanged.

## Data-provider audit

### Yahoo Finance via yfinance

- Used by the repository for scanner candles and research history.
- Approximately 60 days of five-minute data are available.
- Longer periods require coarser bars.
- No credential is required.
- Volume is available.
- Research requests use unadjusted prices.
- Retrieval is not immutable, so snapshots are hashed.

### Finnhub

- Used for current quotes and the mover universe.
- Credentials were detected without exposing their value.
- The repository has no implemented historical-candle helper for Finnhub.

### Tradier

- Used for equity/option quotes, expirations, and option chains.
- Credentials were detected without exposing their value.
- The repository has no implemented historical equity-candle helper for
  six-to-twelve months of five-minute data.

The preferred twelve-month and minimum six-month five-minute targets could not
be obtained through existing authorized provider abstractions. Hourly data was
not silently substituted.

## Dataset obtained

Both datasets cover May 4 through July 29, 2026.

| Symbol | Five-minute bars | Missing bars | Duplicate bars |
|---|---:|---:|---:|
| SPY | 4,680 | 0 | 0 |
| QQQ | 4,680 | 0 | 0 |

Normalized SHA-256 hashes:

- SPY: `39457a03e3de6954c0b5ed02e29120c8c1b53aeacfc1398197a923f331a78a62`
- QQQ: `8c038bc496d4175e0172e15d3f4c8e593a02fdf409d1fda73868f65a99d0d18e`

Raw and normalized snapshots are stored under ignored `.analysis-cache`
directories. Their schemas, hashes, source metadata, and retrieval information
are versioned in the experiment reports.

## Complete signal funnel

| Stage | Evaluated | Passed | Conversion from prior stage |
|---|---:|---:|---:|
| Raw Candidate | 9,256 | 7,462 | 80.62% |
| Structure Detected | 7,462 | 7,462 | 100.00% |
| Direction Assigned | 7,462 | 7,366 | 98.71% |
| Indicators Available | 7,366 | 7,366 | 100.00% |
| Base Conditions Passed | 7,366 | 7,366 | 100.00% |
| Score Calculated | 7,366 | 7,366 | 100.00% |
| Score Threshold Passed | 7,366 | 32 | 0.43% |
| Lifecycle Eligible | 32 | 25 | 78.13% |
| Trade Plan Valid | 25 | 25 | 100.00% |
| Final Alert | 25 | 25 | 100.00% |

Primary rejections:

- Outside production trade-time window: 1,794
- Neutral directional score: 96
- Below score 90: 7,334
- Overlapping active lifecycle: 7

The 25 lifecycle-distinct final alerts exactly reproduce the established
baseline.

The repository does not expose a separate pre-score setup-detector API.
Therefore, a structure-only research candidate means a trade-time bar with a
prior structure window, finite indicators, and a non-neutral directional score.

## Score-bucket performance

| Score bucket | Candidates | Final alerts | Win rate | Expectancy | Profit factor | Stop-first rate |
|---|---:|---:|---:|---:|---:|---:|
| Below 50 | 5,128 | 0 | 42.36% | +0.059% | 1.423 | 54.80% |
| 50–59 | 1,312 | 0 | 40.47% | +0.036% | 1.250 | 57.16% |
| 60–69 | 575 | 0 | 32.00% | -0.022% | 0.867 | 64.52% |
| 70–79 | 218 | 0 | 33.49% | -0.010% | 0.940 | 65.14% |
| 80–84 | 52 | 0 | 36.54% | +0.020% | 1.125 | 63.46% |
| 85–89 | 49 | 0 | 40.82% | +0.026% | 1.178 | 57.14% |
| 90–94 | 25 | 18 | 28.00% | -0.052% | 0.709 | 72.00% |
| 95–100 | 7 | 7 | 14.29% | -0.143% | 0.333 | 85.71% |

Score ranking was not monotonic:

- Score versus realized return: `-0.056`
- Score versus MFE: `-0.044`
- Score versus MAE: `-0.045`
- Score versus Target 1: `-0.040`
- Score versus stop-first: `+0.046`

These broad candidates heavily overlap. They must not be treated as 7,366
independent trades.

## Research threshold comparison

| Threshold | Retained candidates | Win rate | Expectancy | Profit factor | Stop-first rate |
|---:|---:|---:|---:|---:|---:|
| 60 | 926 | 32.83% | -0.016% | 0.903 | 64.58% |
| 65 | 592 | 32.60% | -0.015% | 0.912 | 65.71% |
| 70 | 351 | 34.19% | -0.006% | 0.962 | 64.67% |
| 75 | 218 | 36.24% | +0.016% | 1.100 | 62.39% |
| 80 | 133 | 35.34% | approximately 0.000% | 1.000 | 63.91% |
| 85 | 81 | 34.57% | -0.013% | 0.921 | 64.20% |
| 90 | 32 | 25.00% | -0.072% | 0.615 | 75.00% |
| 95 | 7 | 14.29% | -0.143% | 0.333 | 85.71% |

Walk-forward results:

- Fold 1 selected threshold 60:
  - Training expectancy: +0.014%
  - Validation expectancy: -0.034%
- Fold 2 selected threshold 75:
  - Training expectancy: +0.027%
  - Validation expectancy: -0.011%

No apparent threshold improvement survived chronological validation.

## Scoring-component audit

| Component | Frequency present | Average points | Expectancy when present | Expectancy when absent | Return correlation |
|---|---:|---:|---:|---:|---:|
| Trend | 7,366 | 23.14 | +0.046% | unavailable | +0.033 |
| Momentum | 7,366 | 14.49 | +0.046% | unavailable | -0.001 |
| Volume | 2,919 | 9.96 | +0.027% | +0.058% | -0.036 |
| Volatility | 6,829 | 7.99 | +0.044% | +0.063% | -0.010 |
| Price action | 7,366 | 5.50 | +0.046% | unavailable | -0.055 |

Interpretation:

- Trend, momentum, and price action were present in every directional research
  candidate, preventing simple present-versus-absent isolation.
- Volume-present candidates underperformed volume-absent candidates.
- Price-action points had the most negative component-return correlation.
- Removing any one component moved every score-90 crossing below 90, exposing
  a strong score-threshold cliff.
- Components are correlated and the total score is capped, so this analysis
  does not justify production reweighting.

## Entry-versus-exit findings

Average underlying-price excursions:

| Horizon | Average MFE | Average MAE |
|---|---:|---:|
| 15 minutes | +0.115% | -0.118% |
| 30 minutes | +0.163% | -0.163% |
| 60 minutes | +0.230% | -0.222% |
| Through session | +0.592% | -0.599% |

Standardized barriers:

| Barrier | Favorable first | Adverse first |
|---|---:|---:|
| +0.15% before -0.15% | 3,763 | 3,603 |
| +0.25% before -0.25% | 3,834 | 3,532 |
| +0.35% before -0.25% | 3,337 | 4,029 |
| +0.50% before -0.25% | 2,658 | 4,708 |
| 1R before stop | 3,834 | 3,532 |
| 1.5R before stop | 3,222 | 4,144 |
| 2R before stop | 2,658 | 4,708 |

Additional findings:

- 839 candidates lost under the fixed exit policy despite achieving at least
  +0.25% MFE within 60 minutes.
- 1,902 candidates moved adversely by at least 0.15% within 15 minutes.
- Both entry quality and exit expectations contribute to weak outcomes.
- Many candidates create modest favorable movement, but +0.50% is reached
  before -0.25% adverse movement only about 36% of the time.

All returns and excursions are underlying-price movements, not option returns.

## Sample-size requirements

Approximate independent observations needed per comparison group:

- Expectancy improvement from -0.052% to 0.000%: 861
- Expectancy improvement from -0.052% to +0.025%: 393
- Stop-first reduction from 72% to 60%: 245
- Win-rate improvement from 28% to 40%: 245

Assumptions:

- Two-sided 5% significance
- 80% power
- Equal-sized independent groups

Actual requirements are higher because of:

- Same-day clustering
- SPY/QQQ correlation
- Overlapping holding periods
- Serial correlation
- Regime imbalance
- Multiple comparisons

## Shadow logging

The experiment adds `experiment_003_signal_funnel.jsonl`.

It is:

- Ignored by Git
- Deterministically deduplicated
- Bounded to 5 MB
- Failure-isolated
- Separate from production journals and ledgers
- Unable to create alerts, positions, or orders

## Validation

- Experiment 003 tests: 16 passed
- Experiments 001–003 and optimization tests: 53 passed
- Broad focused regression: 200 passed, 1 unrelated pre-existing failure
- Full suite: 528 passed, 9 unrelated pre-existing failures
- `python -c "import app"`: passed
- Python syntax validation: passed
- `git diff --check`: passed
- Secret scan: passed
- Live-order audit: passed
- Production journals, ledgers, and position stores: unchanged

The nine full-suite failures are pre-existing stale UI/source-shape assertions
and one Finnhub source-label expectation. Experiment 003 introduced no new
full-suite failure.

## Important limitations

1. Only approximately 60 days of five-minute history were available.
2. Adjacent research candidates overlap heavily and are not independent.
3. SPY and QQQ outcomes are correlated.
4. Underlying-price outcomes do not represent option-contract returns.
5. Intrabar barrier ambiguity is resolved conservatively.
6. Score values are rankings, not calibrated probabilities.
7. No threshold or component should be changed from these results alone.

## Files and reports

Main implementation:

- `signal_funnel_experiment.py`
- `generate_signal_funnel_experiment.py`
- `tests/test_signal_funnel_experiment.py`
- `optionbeacon_live.py`

Reports:

- `analysis/experiments/EXP-003-SIGNAL-FUNNEL-CALIBRATION/summary.md`
- `analysis/experiments/EXP-003-SIGNAL-FUNNEL-CALIBRATION/experiment_report.json`
- `analysis/experiments/EXP-003-SIGNAL-FUNNEL-CALIBRATION/candidate_universe.csv`
- `analysis/experiments/EXP-003-SIGNAL-FUNNEL-CALIBRATION/data_provider_audit.json`
- `analysis/experiments/EXP-003-SIGNAL-FUNNEL-CALIBRATION/dataset_manifest.json`
- `analysis/experiments/EXP-003-SIGNAL-FUNNEL-CALIBRATION/signal_funnel_counts.json`
- `analysis/experiments/EXP-003-SIGNAL-FUNNEL-CALIBRATION/score_calibration.json`
- `analysis/experiments/EXP-003-SIGNAL-FUNNEL-CALIBRATION/component_audit.json`
- `analysis/experiments/EXP-003-SIGNAL-FUNNEL-CALIBRATION/entry_exit_analysis.json`
- `analysis/experiments/EXP-003-SIGNAL-FUNNEL-CALIBRATION/sample_size_report.json`

## Suggested prompt for a follow-up GPT discussion

> Review this Experiment 003 summary as a quantitative trading-system research
> audit. Do not recommend a production threshold change from in-sample results.
> Focus on: whether the score has ranking value, why low-score overlapping
> candidates appear stronger than high-score candidates, how to construct a
> genuinely independent research sample, how to separate entry and exit
> quality, and what data-collection plan would most efficiently reach the
> required effective sample size.
