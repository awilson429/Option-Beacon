# Shadow-model governance

No model may silently train and enter production. The required path is:

1. Capture immutable decision-time features and authoritative outcomes.
2. Train a versioned candidate using a time-ordered training window.
3. Validate only on later observations and report class balance, calibration, Brier score, and bucket performance.
4. Compare against the unchanged production baseline.
5. Run in shadow mode without changing ranking, alerts, entries, exits, or persistence semantics.
6. Accumulate live shadow decisions with their model version.
7. Produce a promotion and rollback report.
8. Obtain explicit human approval.
9. Enable a separately controlled feature flag.
10. Retain the previous version and model version on every decision for rollback/audit.

The initial calibrator is an empirical rule-score bucket win rate with a 20-observation prior centered on the training base rate. The default minimum training sample is 50. It is intentionally transparent and returns `INSUFFICIENT_HISTORY` when unavailable. Ranking V2 defaults off through `OPTIONBEACON_OPPORTUNITY_RANKING_V2=false`. Model outputs are always marked `shadow_only`; no code in the authoritative lifecycle consumes them.

Automatic promotion is prohibited. Changing a default flag, model version, feature list, prior strength, outcome definition, or minimum sample threshold requires review, time-separated validation, a production-equivalence test, and a documented rollback plan.
