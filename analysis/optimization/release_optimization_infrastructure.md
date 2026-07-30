# Optimization Infrastructure Release Candidate

## Scope

This document classifies the complete release-candidate difference from
`origin/main` before any merge.

- Production base: `origin/main` at `3f0aa5fd53fe5b5d83d91c1aebd0be63e9fe9330`
- Requested develop SHA: `900f02ca85b9d0275395fab0281511b4c2bfebbd`
- Actual current develop/release base: `c9d4557fe215d5fd817fc75c36fb9ed76adef5e6`
- Release branch: `release/optimization-infrastructure`
- Main safety branch: `backup/main-before-optimization-infrastructure`

The actual develop SHA is used because it contains the completed Experiment 003
infrastructure requested for this release. No merge has occurred.

## Changed-file classification

### 1. Production stability fixes and current stable application behavior

- `developer_tools.py`
- `optionbeacon_live.py`
- `trade_plan_config.py`
- `trade_plan_engine.py`
- `trade_plan_journal.py`
- `trade_plan_lifecycle.py`
- `trade_plan_models.py`
- `trade_plan_service.py`
- `tests/test_developer_tools.py`
- `tests/test_public_dashboard_startup.py`
- `tests/test_trade_plan_engine.py`
- `tests/test_trade_plan_journal_ui.py`
- `tests/test_trade_plan_lifecycle.py`
- `tests/test_trade_plan_service.py`
- `tests/test_release_production_equivalence.py`

These files retain the stable develop application, deterministic paper-only
Trade Plan Engine, diagnostics, lifecycle support, and compatibility APIs.
`optionbeacon_live.py` also contains isolated research hooks; those hooks run
after production processing and return the original scanner result.

### 2. Reusable research infrastructure

- `.gitignore`
- `generate_optimization_baseline.py`
- `optimization_analysis.py`
- `tests/test_optimization_analysis.py`

This group provides replay, baseline metrics, regime labels, normalized
analytics, reproducible generation, and ignored runtime/research storage.

### 3. Experiment-specific code

- `false_breakout_experiment.py`
- `generate_false_breakout_experiment.py`
- `regime_selection_experiment.py`
- `generate_regime_selection_experiment.py`
- `signal_funnel_experiment.py`
- `generate_signal_funnel_experiment.py`
- `tests/test_false_breakout_experiment.py`
- `tests/test_regime_selection_experiment.py`
- `tests/test_signal_funnel_experiment.py`

All three experiments are analysis/shadow only. They do not modify production
scores, thresholds, plans, journals, alerts, or positions.

### 4. Generated reports and versioned research documentation

- `analysis/optimization/2026-07-29/baseline_summary.md`
- `analysis/optimization/2026-07-29/current_system_baseline.json`
- `analysis/optimization/2026-07-29/failure_mode_audit.json`
- `analysis/optimization/2026-07-29/market_regime_analysis.json`
- `analysis/optimization/2026-07-29/replay_trades.csv`
- `analysis/optimization/experiment_registry.jsonl`
- `analysis/experiments/EXP-001-FALSE-BREAKOUT/candidate_decisions.csv`
- `analysis/experiments/EXP-001-FALSE-BREAKOUT/experiment_report.json`
- `analysis/experiments/EXP-001-FALSE-BREAKOUT/parameter_sweeps.json`
- `analysis/experiments/EXP-001-FALSE-BREAKOUT/summary.md`
- `analysis/experiments/EXP-002-REGIME-SELECTION/candidate_decisions.csv`
- `analysis/experiments/EXP-002-REGIME-SELECTION/experiment_report.json`
- `analysis/experiments/EXP-002-REGIME-SELECTION/interaction_analysis.json`
- `analysis/experiments/EXP-002-REGIME-SELECTION/summary.md`
- `analysis/experiments/EXP-003-SIGNAL-FUNNEL-CALIBRATION/candidate_universe.csv`
- `analysis/experiments/EXP-003-SIGNAL-FUNNEL-CALIBRATION/component_audit.json`
- `analysis/experiments/EXP-003-SIGNAL-FUNNEL-CALIBRATION/data_provider_audit.json`
- `analysis/experiments/EXP-003-SIGNAL-FUNNEL-CALIBRATION/dataset_manifest.json`
- `analysis/experiments/EXP-003-SIGNAL-FUNNEL-CALIBRATION/entry_exit_analysis.json`
- `analysis/experiments/EXP-003-SIGNAL-FUNNEL-CALIBRATION/experiment_report.json`
- `analysis/experiments/EXP-003-SIGNAL-FUNNEL-CALIBRATION/sample_size_report.json`
- `analysis/experiments/EXP-003-SIGNAL-FUNNEL-CALIBRATION/score_calibration.json`
- `analysis/experiments/EXP-003-SIGNAL-FUNNEL-CALIBRATION/signal_funnel_counts.json`
- `analysis/experiments/EXP-003-SIGNAL-FUNNEL-CALIBRATION/summary.md`
- `analysis/experiments/EXP-003-SIGNAL-FUNNEL-CALIBRATION/shareable_gpt_summary.md`
- `analysis/optimization/release_optimization_infrastructure.md`

The raw and normalized research snapshots remain ignored under
`.analysis-cache/`. The committed candidate universe is approximately 4.9 MB,
which is below GitHub's file-size limit and is retained because it is the
versioned, reproducible input to the committed calibration summaries.

The shareable GPT summary belongs in versioned documentation: it is directly
related to EXP-003, contains no secrets, and uses repository-relative report
paths.

### 5. Temporary and local artifacts

The following pre-existing, untracked screenshots are excluded from the
release:

- `trade-desk-live-final.png`
- `trade-desk-overlay.png`
- `trade-desk-reference.png`
- `trade-desk-side-by-side.png`
- `workspace-developer-tools.png`
- `workspace-journal.png`
- `workspace-positions.png`
- `workspace-trade-desk.png`
- `workspace-ui-system-overview.png`

Ignored runtime stores, local secrets, caches, raw research snapshots, and
shadow logs are also excluded.

### 6. UI feature-flag and approved navigation work

- `app.py`
- `featured_setup_card.py`
- `trade_plan_ui.py`
- `ui/design_tokens.py`
- `ui/shared_layout.py`
- `ui_modern_style.py`
- `ui_navigation.py`
- `workspace_ui.py`
- `tests/test_build_information.py`
- `tests/test_card_navigation.py`
- `tests/test_featured_setup_card.py`
- `tests/test_internal_card_navigation.py`
- `tests/test_opened_alerts_navigation.py`
- `tests/test_scorecard_modernization.py`
- `tests/test_shared_ui_system.py`
- `tests/test_ui_modern_style.py`
- `tests/test_workspace_ui.py`

The approved default remains the legacy header, six internal navigation cards,
Trade Desk landing page, and legacy scorecard. Modern scorecard styling
requires both the explicit `new_style=1` query parameter and a `develop`
branch build. Demo data additionally requires `demo_data=1`; it is never
enabled by default and cannot activate on `main` or this release branch.

The additional UI modules are inert reusable presentation helpers. They are
not routed from the default application shell and do not expose experimental
recommendations.

### 7. Unrelated changes

None retained. The audit found no tracked screenshot, local environment,
credential, runtime store, live-order implementation, or unrelated production
feature in the release diff.

## Test-debt disposition

The nine known failures were stale tests:

1. Build footer test expected an older parameterized call.
2. Featured Trade Desk test expected a removed workspace renderer.
3. Finnhub test expected the old source label without Attention Movers.
4-7. Shared UI tests expected an abandoned sidebar/four-workspace layout.
8-9. Workspace tests expected removed `Positions`/`Journal` routes and obsolete
filter keys.

The tests now assert the approved six-card application, internal routing,
legacy/default shell, current journal keys, current diagnostics controls,
current Finnhub universe, and current build footer. No production source was
changed to resolve this debt.

## Experimental defaults

- EXP-001 production filtering: disabled
- EXP-002 production selection: disabled
- EXP-003 threshold/scoring changes: disabled
- Shadow output in UI: disabled
- Demo data: disabled
- Modern scorecard: disabled by default and branch-gated
- Live-order execution: absent

Shadow logs:

- `experiment_001_shadow.jsonl`
- `experiment_002_shadow.jsonl`
- `experiment_003_signal_funnel.jsonl`

All are ignored, isolated, deterministically deduplicated, and failure-safe.

## Release-candidate validation

- Focused production-equivalence tests: 184 passed
- Known test-debt checks: 33 passed
- Full suite: 543 passed
- Application import: passed
- Python syntax compilation: passed
- `git diff --check`: passed
- Secret scan: no committed credentials or secret files found
- Runtime-store audit: no ignored production store is tracked
- Live-order audit: no live-order API implementation found
- Local Streamlit startup: HTTP 200 from the release-candidate branch

The release branch is not mapped to an independent Streamlit Community Cloud
deployment. The local startup result is therefore the release-candidate smoke
validation; it is not represented as a hosted deployment result. A hosted
preview requires configuring a separate Streamlit app for this branch or
temporarily repointing an existing non-production app after approval.

## Proposed pull request summary

### Title

`Prepare optimization and experiment infrastructure for main`

### Summary

- Add the unchanged current-system replay baseline.
- Add reproducible regime, funnel, normalization, hashing, calibration, and
  experiment-registry infrastructure.
- Include EXP-001 through EXP-003 analysis modules and generated reports.
- Add isolated, ignored, failure-safe shadow instrumentation.
- Retain the stable production scanner, score 90 thresholds, plans, lifecycle,
  journal, positions, navigation, and legacy/default UI.
- Keep modern styling and demo fixtures explicitly disabled by default.
- Resolve nine stale test expectations without changing production behavior.

### Merge policy

Do not merge until the release branch is pushed, CI is green, smoke validation
is reviewed, and explicit approval is given.

### Proposed merge command after approval

```bash
git switch main
git pull --ff-only origin main
git merge --no-ff release/optimization-infrastructure
git push origin main
```
