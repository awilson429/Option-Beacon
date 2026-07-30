"""Generate versioned Experiment 003 research artifacts."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
from zoneinfo import ZoneInfo

import pandas as pd

from finnhub_universe import finnhub_api_key
from generate_optimization_baseline import fetch_market_data
from signal_funnel_experiment import (
    EXPERIMENT_ID,
    dataset_hash,
    experiment_report,
    normalize_market_data,
    provider_audit,
)
from tradier_options import tradier_configured


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


def _json(path, payload):
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _raw_hash(frame):
    return hashlib.sha256(
        pd.util.hash_pandas_object(frame, index=True).values.tobytes()
    ).hexdigest()


def _summary(report):
    threshold_fields = (
        "threshold",
        "retained_candidates",
        "alerts_per_day",
        "win_rate",
        "expectancy",
        "profit_factor",
        "maximum_drawdown",
        "stop_first_rate",
        "target_1_rate",
    )
    lines = [
        "# Experiment 003 — Signal Funnel, Data Expansion, and Score Calibration",
        "",
        "Research and shadow logging only. Production scoring and threshold 90 are unchanged.",
        "",
        "## Data availability",
        "",
    ]
    for item in report["data_manifest"]:
        lines.append(
            f"- {item['symbol']}: {item['bars']} source bars, "
            f"{item['start']} through {item['end']}; normalized SHA-256 "
            f"`{item['normalized_sha256']}`"
        )
    lines.extend(["", "## Funnel", ""])
    for stage, values in report["funnel"]["counts"].items():
        lines.append(f"- {stage}: {values['passed']} passed of {values['evaluated']} evaluated")
    lines.extend(
        [
            "",
            "## Research thresholds",
            "",
            "| " + " | ".join(threshold_fields) + " |",
            "| " + " | ".join("---" for _ in threshold_fields) + " |",
        ]
    )
    for row in report["threshold_analysis"]:
        lines.append(
            "| "
            + " | ".join(
                "—"
                if row.get(field) is None
                else f"{row[field]:.3f}"
                if isinstance(row.get(field), float)
                else str(row.get(field))
                for field in threshold_fields
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Conclusion",
            "",
            f"- Score predictive: {report['conclusion']['score_predictive']}",
            f"- Threshold 90 assessment: **{report['conclusion']['threshold_90_assessment']}**",
            f"- Reason: {report['conclusion']['reason']}",
            "",
            "Underlying-price movements are used throughout; these are not option returns.",
            "",
        ]
    )
    return "\n".join(lines)


def generate(
    output_root="analysis/experiments",
    registry_path="analysis/optimization/experiment_registry.jsonl",
    *,
    fetcher=fetch_market_data,
    generated_at=None,
):
    generated = generated_at or datetime.now(ZoneInfo("America/New_York"))
    snapshot_id = generated.strftime("%Y%m%dT%H%M%S%z")
    cache_root = Path(".analysis-cache") / EXPERIMENT_ID / snapshot_id
    cache_root.mkdir(parents=True, exist_ok=False)
    frames = {}
    manifest = []
    for symbol in ("SPY", "QQQ"):
        raw = fetcher(symbol, "60d", "5m")
        if raw.empty:
            raise RuntimeError(f"{symbol} five-minute provider history is unavailable")
        frames[symbol] = raw
        normalized = normalize_market_data(raw, symbol)
        raw_path = cache_root / f"{symbol.lower()}-raw.csv"
        normalized_path = cache_root / f"{symbol.lower()}-normalized.csv"
        raw.to_csv(raw_path)
        normalized.to_csv(normalized_path, index=False)
        manifest.append(
            {
                "symbol": symbol,
                "provider": "Yahoo Finance via yfinance",
                "requested_period": "60d",
                "interval": "5m",
                "bars": len(raw),
                "normalized_rows": len(normalized),
                "missing_bars": int(normalized["missing_bar"].sum()),
                "duplicate_bars": int(normalized["duplicate_bar"].sum()),
                "start": pd.Timestamp(raw.index.min()).isoformat(),
                "end": pd.Timestamp(raw.index.max()).isoformat(),
                "retrieved_at": generated.isoformat(),
                "raw_sha256": _raw_hash(raw),
                "normalized_sha256": dataset_hash(normalized),
                "raw_snapshot": str(raw_path),
                "normalized_snapshot": str(normalized_path),
                "snapshot_committed": False,
            }
        )
    evaluation = experiment_report(frames)
    report = {
        "experiment_id": EXPERIMENT_ID,
        "generated_at": generated.isoformat(),
        "implementation_base_commit": _commit(),
        "provider_audit": provider_audit(
            yfinance_configured=True,
            finnhub_configured=bool(finnhub_api_key()),
            tradier_configured=tradier_configured(),
        ),
        "history_target": {
            "preferred": "12 months of five-minute SPY and QQQ",
            "minimum_useful": "6 months of five-minute SPY and QQQ",
            "obtained": "approximately 60 days of five-minute SPY and QQQ",
            "limitation": (
                "No currently implemented and authorized repository provider "
                "exposes six or twelve months of five-minute history. Hourly "
                "bars were not substituted."
            ),
        },
        "dataset_schema": [
            "symbol", "timestamp", "open", "high", "low", "close", "volume",
            "session_date", "regular_market_hours", "source", "interval",
            "timezone", "adjustment_status", "missing_bar", "duplicate_bar",
        ],
        "data_manifest": manifest,
        **{
            key: value
            for key, value in evaluation.items()
            if key not in {"funnel_rows", "candidates"}
        },
        "models": {
            "MODEL_A": "unchanged production threshold 90+",
            "MODEL_B": "research threshold 85+",
            "MODEL_C": "research threshold 80+",
            "MODEL_D": "research threshold 75+",
            "MODEL_E": "score-bucket ranking analysis",
            "MODEL_F": "all directional structure candidates before score gating",
            "MODEL_G": "one-component-at-a-time research ablation",
        },
        "limitations": [
            "Yahoo five-minute history is limited to approximately 60 days.",
            "Historical retrieval is not immutable at the provider; hashes pin this snapshot.",
            "Candidates from adjacent bars overlap and are not independent trades.",
            "SPY and QQQ outcomes are correlated.",
            "Intrabar stop/target ties are resolved conservatively in favor of adverse movement.",
            "The broad universe intentionally contains overlapping research candidates.",
            "Score values are rankings, not calibrated probabilities.",
        ],
    }
    root = Path(output_root) / EXPERIMENT_ID
    root.mkdir(parents=True, exist_ok=True)
    paths = {
        "report": root / "experiment_report.json",
        "summary": root / "summary.md",
        "provider_audit": root / "data_provider_audit.json",
        "dataset_manifest": root / "dataset_manifest.json",
        "funnel": root / "signal_funnel_counts.json",
        "score_calibration": root / "score_calibration.json",
        "component_audit": root / "component_audit.json",
        "entry_exit": root / "entry_exit_analysis.json",
        "sample_size": root / "sample_size_report.json",
        "candidates": root / "candidate_universe.csv",
        "registry": Path(registry_path),
    }
    _json(paths["report"], report)
    paths["summary"].write_text(_summary(report), encoding="utf-8")
    _json(paths["provider_audit"], report["provider_audit"])
    _json(paths["dataset_manifest"], manifest)
    _json(paths["funnel"], report["funnel"])
    _json(paths["score_calibration"], {
        "score_calibration": report["score_calibration"],
        "threshold_analysis": report["threshold_analysis"],
        "validation": report["validation"],
        "bootstrap_90": report["bootstrap_90"],
        "permutation_check": report["permutation_check"],
    })
    _json(paths["component_audit"], report["component_audit"])
    _json(paths["entry_exit"], report["entry_exit_analysis"])
    _json(paths["sample_size"], report["sample_size"])
    evaluation["candidates"].to_csv(paths["candidates"], index=False)

    registry = paths["registry"]
    prior = []
    if registry.exists():
        for line in registry.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("experiment_id") == EXPERIMENT_ID:
                prior.append(record)
    entry = {
        "experiment_id": EXPERIMENT_ID,
        "date": generated.date().isoformat(),
        "hypothesis": "The complete pre-threshold funnel can reveal whether score ranking and threshold 90 are justified.",
        "dataset_sources": ["Yahoo Finance via yfinance"],
        "dataset_hashes": {
            item["symbol"]: item["normalized_sha256"] for item in manifest
        },
        "candidate_count": report["candidate_count"],
        "production_alert_count": report["production_alert_count"],
        "funnel_counts": report["funnel"]["counts"],
        "score_buckets": report["score_calibration"]["buckets"],
        "threshold_results": report["threshold_analysis"],
        "component_audit": report["component_audit"],
        "entry_exit_findings": report["entry_exit_analysis"],
        "validation_results": report["validation"],
        "walk_forward_results": report["walk_forward"],
        "sample_size_limitations": report["sample_size"],
        "conclusion": report["conclusion"],
        "status": "inconclusive",
        "code_commit": report["implementation_base_commit"],
        "revision": len(prior) + 1,
    }
    comparable = {
        key: entry[key]
        for key in (
            "dataset_hashes", "candidate_count", "production_alert_count", "funnel_counts",
            "score_buckets", "threshold_results", "component_audit",
            "entry_exit_findings", "validation_results", "walk_forward_results",
            "sample_size_limitations", "conclusion",
        )
    }
    latest_comparable = (
        {key: prior[-1].get(key) for key in comparable} if prior else None
    )
    if latest_comparable != comparable:
        with registry.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, sort_keys=True, default=str) + "\n")
    return report, paths


if __name__ == "__main__":
    report, paths = generate()
    for name, path in paths.items():
        print(f"{name}: {path}")
    print(json.dumps(report["conclusion"], indent=2))
