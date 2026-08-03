# Trade Selectivity Analysis

## Purpose and safety boundary

Selectivity Analysis is a read-only shadow layer. It describes which immutable entry-time characteristics have been associated with completed outcomes. It does not replace the production rule score, change qualification or ranking, reject trades, or alter PAPER management.

The analysis joins `intelligence_setup_snapshots` to `intelligence_outcome_labels` by `opportunity_id`. Snapshots are inserted once at decision time. Outcome values are never copied into entry features, and missing measurements remain missing. No new database schema is required.

## Entry features

Available features include rule/confidence score, setup, direction, session segment, weekday, EMA values and slopes, trend alignment, VWAP relationship and distance, RSI, relative volume, breakout and candle-body measurements, ATR/volatility, market regime/alignment, and sector identity/rank/alignment. Features absent from the immutable snapshot are not estimated.

Option-contract attributes are reported only when a durable point-in-time linkage is available. Current intelligence snapshots do not universally link authoritative opportunities to PAPER contract captures, so spread, DTE, Greeks, moneyness, and option liquidity remain missing rather than being reconstructed from future data.

## Outcomes and entry-versus-exit diagnosis

Completed entered trades provide realized return, MFE, MAE, hold time, exit reason, stop/target/EOD/max-hold flags, favorable-before-loss state, and peak-to-exit giveback. Dollar excursion and time-to-excursion fields remain missing when they were not captured historically.

The version-one descriptive diagnosis is:

- **GOOD TRADE:** realized return is positive and MFE is at least +0.50%.
- **GOOD ENTRY / BAD EXIT:** realized return is non-positive but MFE reached at least +0.50%.
- **BAD ENTRY:** MFE stayed below +0.25% and MAE reached -0.50% or worse.
- **CHOP / INCONCLUSIVE:** all other fully measured cases.
- **INSUFFICIENT DATA:** realized return, MFE, or MAE is missing.

These thresholds are strategy-relative exploratory definitions, not production exit rules.

## Shadow quality score and tiers

`selectivity-empirical-v1` fits factor return differences on the older chronological training portion. A factor contributes only when at least five training trades contain it. The score begins at a neutral 50 and adds scaled empirical return differences for entry-time factors present on the candidate. It is bounded from 0 to 100, lists positive and negative contributors, and is explicitly not a calibrated probability.

Exploratory factor predicates include score at least 90, relative volume at least 1.5, balanced RSI, market/sector/VWAP/trend alignment, and late-session entry. Their weights are learned from older outcomes; their thresholds are labels for descriptive study and do not gate production.

Trades are ranked deterministically by shadow score and assigned percentile tiers. BASELINE contains all trades; SELECTIVE retains the top 75%; HIGH CONVICTION the top 50%; ELITE the top 25%; and a separate top-10% comparison is provided. Each tier reports retention, reduction, win-rate lift, returns, expectancy, MFE, MAE, hold time, and exit rates.

## Temporal validation

Rows are ordered by exit timestamp. The older 70% trains empirical factor effects and the newer 30% provides the primary tier comparison. There is no random shuffle. Full-history comparisons remain descriptive only. As data grows, the next methodology version should use rolling walk-forward folds and preserve model versions in shadow events.

## Sample governance

- Fewer than 20 eligible trades: **EXPLORATORY ONLY**
- 20–49: **DESCRIPTIVE**
- 50–99: **PRELIMINARY**
- 100 or more: **STRONGER EVIDENCE**

Narrow factor bins require at least five observations merely to display as reliable; substantially larger samples are required for production decisions. The UI never claims statistical significance.

## Known limitations

MFE and MAE quality depends on the existing lifecycle sampling cadence. Historical time-to-MFE/MAE and option-dollar excursions are frequently unavailable. Selection effects, overlapping signals, changing market regimes, and strategy/version drift can confound descriptive differences. One successful session is not evidence for a production threshold.

## Criteria before production filtering

Do not consider a production selectivity policy until there are at least 100 eligible completed trades overall, at least 30 out-of-time trades in the proposed retained tier, stable improvement across multiple trading weeks and market regimes, positive expectancy and MFE/MAE improvement, no dependence on a single ticker/setup, and a separately reviewed walk-forward result. A future change must be a distinct project with explicit human approval, versioned configuration, rollback, and continued shadow comparison.
