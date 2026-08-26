# Provenance Validation and Evidence Report

## Purpose

`analysis.provenance_validation` answers whether a selected session's canonical SPY/QQQ provenance is sufficiently complete and internally consistent for later research. It changes no scanner, qualification, capital, execution, or management behavior.

## Usage and exports

```powershell
python -m analysis.provenance_validation --date 2026-08-25
python -m analysis.provenance_validation --date 2026-08-25 --days 5 --symbol SPY --lane OB
python -m analysis.provenance_validation --date 2026-08-25 --json-output evidence.json --csv-output evidence-csv
python -m analysis.provenance_validation --readiness --lookback-days 365
```

JSON contains the full structured report. CSV writes session summary, qualification/rejection summary, and integrity issues. Provider payloads and secrets are excluded. `GET /api/provenance/validation?date=YYYY-MM-DD&days=1` exposes the same bounded read-only evidence. `GET /api/provenance/readiness` summarizes live collection and 20/40/60-session progress. Neither triggers provider calls or writes.

## Health score

The 0–100 score is the unweighted mean of cycle coverage, observation coverage, chain completeness, identity integrity, temporal integrity, data quality, and outcome linkage. Issues reduce the relevant integrity dimensions. Any CRITICAL issue caps the score at 49 and forces `UNRELIABLE`.

- `HEALTHY`: 85–100 with no critical issue.
- `DEGRADED`: 60–84.9 with no critical issue.
- `UNRELIABLE`: below 60 or any critical issue.

This is an observability score, never a trading score.

## Interpretation

Issues are CRITICAL (identity/lane contamination or wrong chain), HIGH (missing required linkage or impossible chronology), MEDIUM (degraded/data-quality/reason gaps), or LOW (optional explanation gaps). Reports separate observed closed-trade outcomes from `UNAVAILABLE_COUNTERFACTUAL_OUTCOME`; rejected observations are not assigned hypothetical performance.

Empty and partial first-run datasets return explicit low-data states. Low volume alone is not an integrity failure. Growth projections compare observed rows/session with the design estimate of 78 cycles and 156 observations per session and flag only more than 2× that rate.

## Research-eligible session

A session is research eligible only when it has real cycles and observations, health is `HEALTHY`, no critical identity failure exists, SPY/QQQ observation coverage is at least 95%, and no cycle is degraded/error. Strategy research should also require complete opportunity/trade linkage for the question being studied and canonical outcomes for any performance claim.

Block a session from strategy research when identity or lane integrity fails, required SPY/QQQ coverage is absent, cycles are materially degraded, opportunity/trade ownership is ambiguous, or outcomes required by the analysis are unavailable. These rules do not automatically tune strategy.

## Limitations and next observation period

The current schema has no canonical forward outcome for rejected/no-setup observations, so counterfactual performance is unavailable. Database byte size is not estimated portably by the report. Accumulate at least 20 complete market sessions—and preferably 40–60 across varied regimes—before proposing strategy changes, while evaluating evidence sufficiency rather than claiming significance from count alone.
