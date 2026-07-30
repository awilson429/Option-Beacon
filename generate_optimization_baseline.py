"""Generate versioned OptionBeacon baseline and diagnostic artifacts."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
from zoneinfo import ZoneInfo

import pandas as pd

from optimization_analysis import (
    baseline_report,
    regime_methodology,
    replay_current_strategy,
)


DEFAULT_CONFIGS = (
    ("60-trading-days", "60d", "5m"),
    ("6-months", "6mo", "60m"),
    ("12-months", "1y", "60m"),
)
DEFAULT_SYMBOLS = ("SPY", "QQQ")


def fetch_market_data(symbol, period, interval):
    import yfinance as yf

    yf.set_tz_cache_location(str(Path(".analysis-cache").resolve()))
    frame = yf.download(
        symbol,
        period=period,
        interval=interval,
        auto_adjust=False,
        progress=False,
    )
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    required = ["Open", "High", "Low", "Close", "Volume"]
    return frame[required].dropna()


def _json_default(value):
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _current_commit():
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


def _frame_fingerprint(frame):
    values = pd.util.hash_pandas_object(frame, index=True).values.tobytes()
    return hashlib.sha256(values).hexdigest()


def _write_json(path, payload):
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=_json_default)
        + "\n",
        encoding="utf-8",
    )


def _markdown_table(rows, fields):
    if not rows:
        return "_No qualifying records._"
    header = "| " + " | ".join(fields) + " |"
    separator = "| " + " | ".join("---" for _ in fields) + " |"
    values = []
    for row in rows:
        values.append(
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
    return "\n".join([header, separator, *values])


def _write_markdown(path, report, generated_at):
    overall = report["overall"]
    lines = [
        "# OptionBeacon Current-System Baseline",
        "",
        f"Generated: {generated_at}",
        "",
        "This report is analysis-only. Production decisions, thresholds, stops, "
        "targets, and UI behavior are unchanged.",
        "",
        "## Data availability",
        "",
    ]
    for item in report["data_manifest"]:
        lines.append(
            f"- {item['symbol']} / {item['period']} / {item['timeframe']}: "
            f"{item['status']}, {item.get('bars', 0)} bars, "
            f"{item.get('start') or '—'} through {item.get('end') or '—'}"
        )
    lines.extend(
        [
            "",
            "## Overall",
            "",
            _markdown_table(
                [overall],
                [
                    "total_alerts",
                    "alerts_per_day",
                    "win_rate",
                    "expectancy",
                    "profit_factor",
                    "maximum_drawdown",
                    "average_mfe",
                    "average_mae",
                    "target_1_rate",
                    "stop_first_rate",
                    "late_rate",
                ],
            ),
            "",
        ]
    )
    for title, key in (
        ("By symbol", "by_symbol"),
        ("By direction", "by_direction"),
        ("By setup", "by_setup"),
        ("By hour", "by_hour"),
        ("By confidence bucket", "by_confidence_bucket"),
        ("By regime", "by_regime"),
        ("By requested period", "by_period"),
        ("By timeframe", "by_timeframe"),
        ("By higher-timeframe alignment", "by_higher_timeframe_alignment"),
    ):
        lines.extend(
            [
                f"## {title}",
                "",
                _markdown_table(
                    report[key],
                    [
                        "group",
                        "total_alerts",
                        "win_rate",
                        "expectancy",
                        "profit_factor",
                        "maximum_drawdown",
                    ],
                ),
                "",
            ]
        )
    lines.extend(
        [
            "## Failure modes",
            "",
            _markdown_table(
                report["failure_modes"],
                ["failure_mode", "frequency", "average_return"],
            ),
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def generate_reports(output_root, *, fetcher=fetch_market_data, generated_at=None):
    stamp = generated_at or datetime.now(ZoneInfo("America/New_York"))
    version = stamp.strftime("%Y-%m-%d")
    output_dir = Path(output_root) / version
    output_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    manifest = []

    for symbol in DEFAULT_SYMBOLS:
        for period_label, period, interval in DEFAULT_CONFIGS:
            item = {
                "symbol": symbol,
                "period": period_label,
                "requested_period": period,
                "timeframe": interval,
            }
            try:
                raw = fetcher(symbol, period, interval)
                if raw.empty:
                    raise ValueError("provider returned no bars")
                item.update(
                    {
                        "status": "available",
                        "bars": len(raw),
                        "trading_days": len(
                            {pd.Timestamp(value).date() for value in raw.index}
                        ),
                        "data_sha256": _frame_fingerprint(raw),
                        "start": pd.Timestamp(raw.index.min()).isoformat(),
                        "end": pd.Timestamp(raw.index.max()).isoformat(),
                    }
                )
                replay = replay_current_strategy(
                    symbol,
                    raw,
                    timeframe=interval,
                    period_label=period_label,
                )
                if not replay.empty:
                    frames.append(replay)
            except Exception as exc:
                item.update(
                    {
                        "status": "unavailable",
                        "bars": 0,
                        "start": None,
                        "end": None,
                        "reason": str(exc)[:240],
                    }
                )
            manifest.append(item)

    trades = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    report = baseline_report(trades, manifest)
    generated_text = stamp.isoformat()
    report.update(
        {
            "generated_at": generated_text,
            "baseline_code_commit": _current_commit(),
            "regime_methodology": regime_methodology(),
            "limitations": [
                "Yahoo intraday 5-minute history is limited to approximately 60 days.",
                "Six- and twelve-month analysis uses hourly bars when available.",
                "Underlying-price returns do not represent option-contract returns.",
                "Intrabar stop/target ambiguity is resolved conservatively in favor of the stop.",
                "Failure labels are diagnostic associations, not causal claims.",
            ],
        }
    )
    baseline_path = output_dir / "current_system_baseline.json"
    failure_path = output_dir / "failure_mode_audit.json"
    regime_path = output_dir / "market_regime_analysis.json"
    markdown_path = output_dir / "baseline_summary.md"
    trades_path = output_dir / "replay_trades.csv"
    registry_path = Path(output_root) / "experiment_registry.jsonl"

    _write_json(baseline_path, report)
    _write_json(
        failure_path,
        {
            "generated_at": generated_text,
            "failure_modes": report["failure_modes"],
            "limitations": report["limitations"],
        },
    )
    _write_json(
        regime_path,
        {
            "generated_at": generated_text,
            "methodology": report["regime_methodology"],
            "performance_by_regime": report["by_regime"],
        },
    )
    _write_markdown(markdown_path, report, generated_text)
    trades.to_csv(trades_path, index=False)

    experiment_id = f"baseline-{version}"
    prior_ids = set()
    if registry_path.exists():
        for line in registry_path.read_text(encoding="utf-8").splitlines():
            try:
                prior_ids.add(json.loads(line)["experiment_id"])
            except (json.JSONDecodeError, KeyError):
                continue
    if experiment_id not in prior_ids:
        entry = {
            "experiment_id": experiment_id,
            "date": version,
            "hypothesis": "Measure the unchanged production strategy before optimization.",
            "code_commit": report["baseline_code_commit"],
            "parameters": {
                "call_score_threshold": 90,
                "put_score_threshold": 90,
                "stop_percent": 0.0025,
                "target_percent": 0.005,
                "max_hold_candles": 48,
            },
            "train_period": None,
            "validation_period": None,
            "test_period": "observed baseline windows",
            "symbols": list(DEFAULT_SYMBOLS),
            "metrics": report["overall"],
            "result": "baseline established",
            "accepted": None,
            "reason": "No parameter change was evaluated.",
        }
        with registry_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, sort_keys=True, default=_json_default) + "\n")

    return {
        "baseline": baseline_path,
        "failure_modes": failure_path,
        "regimes": regime_path,
        "summary": markdown_path,
        "trades": trades_path,
        "registry": registry_path,
    }, report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="analysis/optimization",
        help="Versioned report root",
    )
    args = parser.parse_args()
    paths, report = generate_reports(args.output)
    print(f"Generated {report['trade_count']} replay trades")
    for name, path in paths.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
