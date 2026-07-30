"""Generate versioned artifacts for Experiment 002."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import subprocess
from zoneinfo import ZoneInfo

import pandas as pd

from generate_optimization_baseline import fetch_market_data
from regime_selection_experiment import (
    EXPERIMENT_ID,
    INTERACTIONS,
    MODELS,
    evaluate_experiment,
)


def _commit():
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _write_json(path, payload):
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _comparison(models):
    fields = (
        "original_alerts",
        "retained_alerts",
        "reduction_percent",
        "win_rate",
        "expectancy",
        "profit_factor",
        "stop_first_rate",
        "target_1_rate",
        "maximum_drawdown",
        "winners_removed",
        "losers_removed",
        "alerts_per_day",
        "longest_no_alert_hours",
        "flags",
    )
    return [
        {"model": name, **{field: report["metrics"].get(field) for field in fields}}
        for name, report in models.items()
    ]


def _conclusion(comparison, walk_forward):
    baseline = comparison[0]
    positive_validation = {
        fold["selected_on_train"]
        for fold in walk_forward["folds"]
        if fold.get("selected_on_train")
        and (fold["validation_metrics"].get("expectancy") or -999) > 0
        and not fold["validation_metrics"].get("flags")
    }
    candidates = [
        row
        for row in comparison[1:]
        if not row["flags"]
        and row["retained_alerts"] >= 5
        and row.get("expectancy") is not None
        and row["expectancy"] > (baseline.get("expectancy") or -999)
        and (row.get("profit_factor") or 0) > (baseline.get("profit_factor") or 0)
        and (row.get("stop_first_rate") or 100)
        < (baseline.get("stop_first_rate") or 100)
        and row["model"] in positive_validation
    ]
    if not candidates:
        return {
            "status": "inconclusive",
            "selected_candidate": None,
            "confidence": "low",
            "reason": (
                "No interpretable context model improved the required metrics "
                "while retaining meaningful volume and positive walk-forward evidence."
            ),
        }
    candidate = max(candidates, key=lambda row: row["expectancy"])
    return {
        "status": "promising",
        "selected_candidate": candidate["model"],
        "confidence": "low",
        "reason": "The candidate passed first-run gates but remains shadow-only.",
    }


def _table(rows, fields):
    lines = [
        "| " + " | ".join(fields) + " |",
        "| " + " | ".join("---" for _ in fields) + " |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                "—"
                if row.get(field) is None
                else f"{row[field]:.3f}"
                if isinstance(row.get(field), float)
                else str(row.get(field))
                for field in fields
            )
            + " |"
        )
    return "\n".join(lines)


def _summary(report):
    fields = (
        "model",
        "retained_alerts",
        "reduction_percent",
        "win_rate",
        "expectancy",
        "profit_factor",
        "stop_first_rate",
        "maximum_drawdown",
    )
    conclusion = report["conclusion"]
    return "\n".join(
        [
            "# Experiment 002 — Regime-Aware Signal Selection",
            "",
            "Analysis and shadow mode only. Production decisions remain unchanged.",
            "",
            "## Candidate results",
            "",
            _table(report["comparison"], fields),
            "",
            "## Conclusion",
            "",
            f"- Status: **{conclusion['status']}**",
            f"- Selected candidate: {conclusion['selected_candidate'] or 'none'}",
            f"- Confidence: {conclusion['confidence']}",
            f"- Reason: {conclusion['reason']}",
            "",
            "Sparse subgroup labels are descriptive and are not treated as conclusive.",
            "",
        ]
    )


def generate(
    output_root="analysis/experiments",
    registry_path="analysis/optimization/experiment_registry.jsonl",
    *,
    fetcher=fetch_market_data,
):
    generated = datetime.now(ZoneInfo("America/New_York"))
    frames = {symbol: fetcher(symbol, "60d", "5m") for symbol in ("SPY", "QQQ")}
    evaluation = evaluate_experiment(frames)
    comparison = _comparison(evaluation["models"])
    conclusion = _conclusion(comparison, evaluation["walk_forward"])
    report = {
        "experiment_id": EXPERIMENT_ID,
        "generated_at": generated.isoformat(),
        "implementation_base_commit": _commit(),
        "dataset": {
            symbol: {
                "bars": len(frame),
                "start": pd.Timestamp(frame.index.min()).isoformat(),
                "end": pd.Timestamp(frame.index.max()).isoformat(),
                "timeframe": "5m",
            }
            for symbol, frame in frames.items()
        },
        "model_definitions": {
            name: model.description for name, model in MODELS.items()
        },
        "context_dimensions": [
            "symbol",
            "direction",
            "volatility_regime",
            "trend_regime",
            "gap_regime",
            "higher_timeframe_alignment",
            "time_window",
        ],
        "interaction_definitions": [list(fields) for fields in INTERACTIONS],
        "comparison": comparison,
        "models": evaluation["models"],
        "interactions": evaluation["interactions"],
        "walk_forward": evaluation["walk_forward"],
        "conclusion": conclusion,
        "limitations": [
            "Approximately 60 trading days of five-minute bars are available.",
            "The unchanged production threshold yields a small setup sample.",
            "Underlying-price returns are not option-contract returns.",
            "Sparse combinations are labeled insufficient and not interpreted as evidence.",
            "The shallow tree is an analysis aid, not a deployed predictive model.",
            "Point-in-time regime labels may change as later bars arrive; stored decisions do not.",
        ],
    }
    root = Path(output_root) / EXPERIMENT_ID
    root.mkdir(parents=True, exist_ok=True)
    paths = {
        "report": root / "experiment_report.json",
        "summary": root / "summary.md",
        "decisions": root / "candidate_decisions.csv",
        "interactions": root / "interaction_analysis.json",
        "registry": Path(registry_path),
    }
    _write_json(paths["report"], report)
    paths["summary"].write_text(_summary(report), encoding="utf-8")
    evaluation["rows"].to_csv(paths["decisions"], index=False)
    _write_json(paths["interactions"], evaluation["interactions"])

    registry = paths["registry"]
    prior = []
    if registry.exists():
        for line in registry.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get("experiment_id") == EXPERIMENT_ID:
                prior.append(item)
    rules = {name: model.description for name, model in MODELS.items()}
    latest = prior[-1] if prior else None
    if (
        latest is None
        or latest.get("metrics") != comparison
        or latest.get("conclusion") != conclusion
        or latest.get("model_definitions") != rules
    ):
        entry = {
            "experiment_id": EXPERIMENT_ID,
            "date": generated.date().isoformat(),
            "hypothesis": (
                "Signal quality may improve when participation and confirmation "
                "requirements vary by point-in-time market context."
            ),
            "model_definitions": rules,
            "context_dimensions": report["context_dimensions"],
            "dataset": report["dataset"],
            "splits": {
                "walk_forward": "expanding chronological thirds",
                "leave_one_period_out": "three chronological periods",
                "holdouts": ["symbol", "direction"],
            },
            "metrics": comparison,
            "selected_candidate": conclusion["selected_candidate"],
            "confidence": conclusion["confidence"],
            "limitations": report["limitations"],
            "status": conclusion["status"],
            "accepted": conclusion["status"] == "promising",
            "conclusion": conclusion,
            "code_commit": report["implementation_base_commit"],
            "revision": len(prior) + 1,
        }
        with registry.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, sort_keys=True, default=str) + "\n")
    return report, paths


if __name__ == "__main__":
    report, paths = generate()
    for name, path in paths.items():
        print(f"{name}: {path}")
    print(json.dumps(report["conclusion"], indent=2))
