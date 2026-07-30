"""Generate versioned artifacts for Experiment 001."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import subprocess
from zoneinfo import ZoneInfo

import pandas as pd

from false_breakout_experiment import EXPERIMENT_ID, MODELS, evaluate_experiment
from generate_optimization_baseline import fetch_market_data


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
    keys = (
        "active_entries",
        "alert_reduction_percent",
        "win_rate",
        "expectancy",
        "profit_factor",
        "maximum_drawdown",
        "target_1_rate",
        "target_2_rate",
        "stop_first_rate",
        "quick_invalidation_rate",
        "average_entry_delay_minutes",
        "average_risk_reward_at_entry",
    )
    return [
        {
            "model": name,
            **{key: details["metrics"].get(key) for key in keys},
        }
        for name, details in models.items()
    ]


def _conclusion(comparison, walk_forward):
    baseline = comparison[0]
    candidates = [
        item
        for item in comparison[1:]
        if item["active_entries"] >= 10
        and item["expectancy"] is not None
        and item["expectancy"] > (baseline["expectancy"] or -999)
        and item["profit_factor"] is not None
        and item["profit_factor"] > (baseline["profit_factor"] or 0)
    ]
    selected_in_walk_forward = {
        fold.get("selected_on_train")
        for fold in walk_forward.get("folds", [])
        if (
            fold.get("validation_metrics", {}).get("expectancy") is not None
            and fold["validation_metrics"]["expectancy"] > 0
        )
    }
    robust_candidates = [
        item
        for item in candidates
        if item["model"] in selected_in_walk_forward
    ]
    if not robust_candidates:
        return {
            "status": "inconclusive",
            "recommended_candidate": None,
            "confidence": "low",
            "reason": (
                "No candidate combined sufficient retained alerts with "
                "positive out-of-sample walk-forward evidence."
            ),
        }
    best = max(robust_candidates, key=lambda item: item["expectancy"])
    return {
        "status": "promising but unproven",
        "recommended_candidate": best["model"],
        "confidence": "low",
        "reason": "Headline metrics improved, but the five-minute sample remains statistically inadequate.",
    }


def _summary_markdown(report):
    comparison = report["comparison"]
    fields = (
        "model",
        "active_entries",
        "alert_reduction_percent",
        "win_rate",
        "expectancy",
        "profit_factor",
        "stop_first_rate",
        "quick_invalidation_rate",
        "target_1_rate",
        "average_entry_delay_minutes",
    )
    lines = [
        "# Experiment 001 — False-Breakout Protection",
        "",
        "Production signals, scoring, stops, targets, journals, and positions are unchanged.",
        "",
        "## Model comparison",
        "",
        "| " + " | ".join(fields) + " |",
        "| " + " | ".join("---" for _ in fields) + " |",
    ]
    for row in comparison:
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
    conclusion = report["conclusion"]
    lines.extend(
        [
            "",
            "## Conclusion",
            "",
            f"- Status: **{conclusion['status']}**",
            f"- Recommended candidate: {conclusion['recommended_candidate'] or 'none'}",
            f"- Confidence: {conclusion['confidence']}",
            f"- Reason: {conclusion['reason']}",
            "",
            "Hourly history was not merged into these five-minute headline metrics.",
        ]
    )
    return "\n".join(lines) + "\n"


def generate(output_root="analysis/experiments", registry_path="analysis/optimization/experiment_registry.jsonl"):
    generated = datetime.now(ZoneInfo("America/New_York"))
    symbol_frames = {
        symbol: fetch_market_data(symbol, "60d", "5m")
        for symbol in ("SPY", "QQQ")
    }
    evaluation = evaluate_experiment(symbol_frames)
    comparison = _comparison(evaluation["models"])
    conclusion = _conclusion(comparison, evaluation["walk_forward"])
    report = {
        "experiment_id": EXPERIMENT_ID,
        "generated_at": generated.isoformat(),
        "baseline_commit": "26438743343b88e17c283f2bdc393ca95d9bcff1",
        "implementation_base_commit": _commit(),
        "dataset": {
            symbol: {
                "bars": len(frame),
                "start": pd.Timestamp(frame.index.min()).isoformat(),
                "end": pd.Timestamp(frame.index.max()).isoformat(),
                "timeframe": "5m",
            }
            for symbol, frame in symbol_frames.items()
        },
        "candidate_definitions": {
            name: model.__dict__ for name, model in MODELS.items()
        },
        "comparison": comparison,
        "models": evaluation["models"],
        "parameter_sweeps": evaluation["parameter_sweeps"],
        "walk_forward": evaluation["walk_forward"],
        "conclusion": conclusion,
        "limitations": [
            "Only approximately 60 trading days of five-minute bars are available.",
            "The unchanged production threshold produced only 25 base setups.",
            "Underlying returns are not option-contract returns.",
            "Intrabar ambiguity is resolved conservatively in favor of the stop.",
            "Parameter sweeps are exploratory and were not used as full-sample production tuning.",
            "Hourly history is excluded from headline metrics.",
        ],
    }
    root = Path(output_root) / "EXP-001-FALSE-BREAKOUT"
    root.mkdir(parents=True, exist_ok=True)
    report_path = root / "experiment_report.json"
    summary_path = root / "summary.md"
    rows_path = root / "candidate_decisions.csv"
    sweeps_path = root / "parameter_sweeps.json"
    _write_json(report_path, report)
    summary_path.write_text(_summary_markdown(report), encoding="utf-8")
    evaluation["rows"].to_csv(rows_path, index=False)
    _write_json(sweeps_path, evaluation["parameter_sweeps"])

    registry = Path(registry_path)
    existing = []
    if registry.exists():
        existing = registry.read_text(encoding="utf-8").splitlines()
    prior_experiments = [
        json.loads(line)
        for line in existing
        if line.strip() and json.loads(line).get("experiment_id") == EXPERIMENT_ID
    ]
    latest_prior = prior_experiments[-1] if prior_experiments else None
    current_rules = {
        name: model.__dict__ for name, model in MODELS.items()
    }
    if (
        latest_prior is None
        or latest_prior.get("conclusion") != conclusion
        or latest_prior.get("metrics") != comparison
        or latest_prior.get("candidate_rules") != current_rules
    ):
        registry_entry = {
            "experiment_id": EXPERIMENT_ID,
            "date": generated.date().isoformat(),
            "hypothesis": "Point-in-time breakout confirmation can reduce false breakouts without eliminating practical alert volume.",
            "candidate_rules": current_rules,
            "dataset": report["dataset"],
            "train_period": "chronological expanding-window folds",
            "validation_period": "next chronological fold",
            "code_commit": report["implementation_base_commit"],
            "metrics": comparison,
            "conclusion": conclusion,
            "status": conclusion["status"],
            "known_limitations": report["limitations"],
            "revision": len(prior_experiments) + 1,
            "supersedes_revision": (
                latest_prior.get("revision", len(prior_experiments))
                if latest_prior
                else None
            ),
        }
        with registry.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(registry_entry, sort_keys=True, default=str) + "\n")
    return report, {
        "report": report_path,
        "summary": summary_path,
        "decisions": rows_path,
        "sweeps": sweeps_path,
        "registry": registry,
    }


if __name__ == "__main__":
    report, paths = generate()
    for name, path in paths.items():
        print(f"{name}: {path}")
    print(json.dumps(report["conclusion"], indent=2))
