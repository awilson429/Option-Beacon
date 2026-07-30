"""Experiment 002: point-in-time, regime-aware signal selection research.

This module is analysis-only.  It consumes unchanged production setups and
never changes scores, plans, journals, positions, or scanner output.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import logging
import math
from pathlib import Path
from statistics import mean

import pandas as pd

from false_breakout_experiment import (
    ACTIVE,
    MODELS as EXP001_MODELS,
    _candidate_decision,
    _fixed_plan_outcome,
    _number,
    _opening_range,
    _session_minutes,
    classify_gap,
    collect_base_setups,
    entry_window,
)
from optimization_analysis import performance_metrics


LOGGER = logging.getLogger(__name__)
EXPERIMENT_ID = "EXP-002-REGIME-SELECTION"
DEFAULT_SHADOW_FILE = "experiment_002_shadow.jsonl"
DEFAULT_MINIMUM_SAMPLE = 5
TREE_MAX_DEPTH = 3
TREE_MIN_LEAF_SIZE = 5


@dataclass(frozen=True)
class SelectionModel:
    name: str
    description: str


MODELS = {
    "MODEL_A_BASELINE": SelectionModel(
        "MODEL_A_BASELINE", "All unchanged production signals."
    ),
    "MODEL_B_SYMBOL_SELECTIVE": SelectionModel(
        "MODEL_B_SYMBOL_SELECTIVE",
        "Select the symbol with stronger expanding-window training evidence.",
    ),
    "MODEL_C_DIRECTION_SELECTIVE": SelectionModel(
        "MODEL_C_DIRECTION_SELECTIVE",
        "Select symbol-direction groups supported by expanding training data.",
    ),
    "MODEL_D_REGIME_SELECTIVE": SelectionModel(
        "MODEL_D_REGIME_SELECTIVE",
        "High volatility, directional trend, non-gap-reversal, aligned HTF.",
    ),
    "MODEL_E_TIME_SELECTIVE": SelectionModel(
        "MODEL_E_TIME_SELECTIVE",
        "Exclude opening 30 minutes, midday, 14:00 hour, and final hour.",
    ),
    "MODEL_F_CONTEXT_CONFIRMATION": SelectionModel(
        "MODEL_F_CONTEXT_CONFIRMATION",
        "Use context-specific close, hold, retest, and opening-range confirmation.",
    ),
    "MODEL_G_SIMPLE_GATES": SelectionModel(
        "MODEL_G_SIMPLE_GATES",
        "Three interpretable gates: non-gap-reversal, no 14:00 hour, HTF not opposed.",
    ),
    "MODEL_H_SHALLOW_TREE": SelectionModel(
        "MODEL_H_SHALLOW_TREE",
        "Depth-limited interpretable decision-tree analysis aid.",
    ),
}

INTERACTIONS = (
    ("symbol", "direction"),
    ("symbol", "volatility_regime"),
    ("direction", "gap_regime"),
    ("direction", "higher_timeframe_alignment"),
    ("time_window", "volatility_regime"),
    ("gap_regime", "confirmation_type"),
)


def time_window(timestamp):
    """Return one of the specified half-open ET windows."""
    return entry_window(timestamp)


def gap_regime(gap_atr, regime):
    magnitude = abs(_number(gap_atr, 0.0) or 0.0)
    if regime == "opening gap continuation":
        return "gap continuation"
    if regime == "opening gap reversal":
        return "gap reversal"
    if magnitude < 0.25:
        return "no meaningful gap"
    if magnitude < 0.50:
        return "small gap"
    if magnitude <= 1.00:
        return "medium gap"
    return "large gap"


def volatility_regime(regime):
    if regime == "high-volatility expansion":
        return "high-volatility expansion"
    if regime == "low-volatility compression":
        return "low-volatility compression"
    return "normal"


def trend_regime(regime):
    mapping = {
        "bullish trend": "bullish trend",
        "bearish trend": "bearish trend",
        "range-bound": "range-bound",
    }
    return mapping.get(regime, "mixed/neutral")


def context_for_setup(setup):
    """Build labels exclusively from fields calculated at the setup bar."""
    regime = setup.get("regime") or "mixed/neutral"
    return {
        "symbol": setup.get("symbol"),
        "direction": str(setup.get("direction") or "").lower(),
        "volatility_regime": volatility_regime(regime),
        "trend_regime": trend_regime(regime),
        "gap_regime": gap_regime(setup.get("gap_atr"), regime),
        "higher_timeframe_alignment": setup.get(
            "higher_timeframe_alignment", "neutral"
        ),
        "time_window": time_window(setup.get("signal_time")),
    }


def _baseline_row(setup):
    outcome = dict(setup["base_outcome"])
    return {
        **context_for_setup(setup),
        "model": "MODEL_A_BASELINE",
        "signal_time": setup["signal_time"],
        "status": ACTIVE,
        "decision": "participate",
        "rejection_reason": None,
        "confirmation_type": "production baseline",
        "entry_time": setup["signal_time"],
        "base_return": outcome["realized_return"],
        **outcome,
    }


def _training_support(prior_rows, fields, values, minimum=3):
    matching = prior_rows
    for field, value in zip(fields, values):
        matching = [row for row in matching if row.get(field) == value]
    if len(matching) < minimum:
        return None
    returns = [row["realized_return"] for row in matching]
    return mean(returns) >= 0


def _tree_decision(prior_rows, context):
    """A deterministic depth-two tree trained only on earlier observations."""
    if len(prior_rows) < TREE_MIN_LEAF_SIZE * 2:
        return True, "insufficient prior samples; baseline fallback", {
            "depth": 0,
            "minimum_leaf_size": TREE_MIN_LEAF_SIZE,
        }
    candidates = (
        "symbol",
        "direction",
        "volatility_regime",
        "gap_regime",
        "higher_timeframe_alignment",
        "time_window",
    )
    best = None
    for field in candidates:
        groups = {}
        for row in prior_rows:
            groups.setdefault(row[field], []).append(row["realized_return"])
        valid = {key: values for key, values in groups.items() if len(values) >= TREE_MIN_LEAF_SIZE}
        if len(valid) < 2:
            continue
        spread = max(mean(values) for values in valid.values()) - min(
            mean(values) for values in valid.values()
        )
        candidate = (spread, field, valid)
        if best is None or candidate[0] > best[0]:
            best = candidate
    if best is None:
        return True, "no valid split; baseline fallback", {
            "depth": 0,
            "minimum_leaf_size": TREE_MIN_LEAF_SIZE,
        }
    _, field, groups = best
    value = context[field]
    leaf = groups.get(value)
    participate = leaf is None or mean(leaf) >= 0
    return participate, f"{field}={value} leaf", {
        "depth": 1,
        "split": field,
        "minimum_leaf_size": TREE_MIN_LEAF_SIZE,
    }


def _opening_range_complete(frame, setup):
    index = setup["base_index"]
    if _session_minutes(frame, index) < 30:
        return False
    high, low = _opening_range(frame, index)
    price = _number(frame.iloc[index]["Close"])
    if high is None or price is None:
        return False
    return price >= high if setup["direction"] == "Bullish" else price <= low


def model_decision(model_name, frame, setup, prior_rows):
    context = context_for_setup(setup)
    if model_name == "MODEL_A_BASELINE":
        return True, "production baseline", setup["base_index"], {}
    if model_name == "MODEL_B_SYMBOL_SELECTIVE":
        support = _training_support(prior_rows, ("symbol",), (context["symbol"],))
        return support is not False, (
            "symbol supported by prior data" if support is not False else "symbol weak in prior data"
        ), setup["base_index"], {}
    if model_name == "MODEL_C_DIRECTION_SELECTIVE":
        support = _training_support(
            prior_rows,
            ("symbol", "direction"),
            (context["symbol"], context["direction"]),
        )
        return support is not False, (
            "symbol-direction supported by prior data"
            if support is not False
            else "symbol-direction weak in prior data"
        ), setup["base_index"], {}
    if model_name == "MODEL_D_REGIME_SELECTIVE":
        directional = context["trend_regime"] in {
            f"{context['direction']} trend",
            "mixed/neutral",
        }
        accepted = (
            context["volatility_regime"] == "high-volatility expansion"
            and directional
            and context["gap_regime"] != "gap reversal"
            and context["higher_timeframe_alignment"] == "aligned"
        )
        return accepted, "all regime gates passed" if accepted else "regime gate failed", setup["base_index"], {}
    if model_name == "MODEL_E_TIME_SELECTIVE":
        excluded = {
            "09:30-10:00",
            "11:00-13:00",
            "14:00-15:00",
            "15:00-16:00",
        }
        accepted = context["time_window"] not in excluded
        return accepted, "allowed time window" if accepted else "excluded time window", setup["base_index"], {}
    if model_name == "MODEL_F_CONTEXT_CONFIRMATION":
        confirmation = "standard close"
        candidate_model = EXP001_MODELS["MODEL_B_CLOSE_ONLY"]
        if (
            context["symbol"] == "QQQ"
            and context["direction"] == "bullish"
            and context["volatility_regime"] == "high-volatility expansion"
        ):
            confirmation = "standard close"
        elif context["higher_timeframe_alignment"] == "opposed":
            confirmation = "retest required"
            candidate_model = EXP001_MODELS["MODEL_G_RETEST_HOLD"]
        elif context["gap_regime"] == "large gap":
            confirmation = "opening range required"
            if not _opening_range_complete(frame, setup):
                return False, "opening range incomplete", None, {"confirmation_type": confirmation}
        elif (
            context["symbol"] == "SPY"
            and context["direction"] == "bearish"
            and context["gap_regime"] == "gap reversal"
        ):
            confirmation = "one-candle hold"
            candidate_model = EXP001_MODELS["MODEL_F_GAP_AWARE"]
        decision = _candidate_decision(frame, setup["base_index"], setup, candidate_model)
        accepted = decision["status"] == ACTIVE
        return accepted, decision["reason"], decision.get("entry_index"), {
            "confirmation_type": confirmation
        }
    if model_name == "MODEL_G_SIMPLE_GATES":
        accepted = (
            context["gap_regime"] != "gap reversal"
            and context["time_window"] != "14:00-15:00"
            and context["higher_timeframe_alignment"] != "opposed"
        )
        return accepted, "simple gates passed" if accepted else "simple context gate failed", setup["base_index"], {}
    if model_name == "MODEL_H_SHALLOW_TREE":
        accepted, reason, tree = _tree_decision(prior_rows, context)
        return accepted, reason, setup["base_index"], {
            "confirmation_type": "shallow tree",
            "tree": tree,
        }
    raise KeyError(model_name)


def evaluate_models(symbol_frames):
    frames_and_setups = []
    for symbol, raw in symbol_frames.items():
        frame, setups = collect_base_setups(symbol, raw)
        frames_and_setups.append((frame, setups))
    indexed = []
    for frame, setups in frames_and_setups:
        indexed.extend((pd.Timestamp(setup["signal_time"]), frame, setup) for setup in setups)
    indexed.sort(key=lambda item: (item[0], item[2]["symbol"]))
    baseline = [_baseline_row(setup) for _, _, setup in indexed]
    results = {}
    for model_name in MODELS:
        prior = []
        rows = []
        for _, frame, setup in indexed:
            accepted, reason, entry_index, details = model_decision(
                model_name, frame, setup, prior
            )
            row = {
                **context_for_setup(setup),
                "model": model_name,
                "signal_time": setup["signal_time"],
                "decision": "participate" if accepted else "reject",
                "status": ACTIVE if accepted else "REJECTED",
                "rejection_reason": None if accepted else reason,
                "confirmation_type": details.get(
                    "confirmation_type", "production baseline"
                ),
                "base_return": setup["base_outcome"]["realized_return"],
                "entry_time": (
                    pd.Timestamp(frame.index[entry_index]).isoformat()
                    if accepted and entry_index is not None
                    else None
                ),
                "tree": details.get("tree"),
            }
            if accepted and entry_index is not None:
                row.update(_fixed_plan_outcome(frame, entry_index, setup))
            rows.append(row)
            prior.append(_baseline_row(setup))
        results[model_name] = pd.DataFrame(rows)
    return results


def _max_drawdown(returns):
    equity = peak = drawdown = 0.0
    for value in returns:
        equity += value
        peak = max(peak, equity)
        drawdown = min(drawdown, equity - peak)
    return drawdown


def selection_metrics(rows, baseline_count=None, trading_days=None):
    active = rows[rows["status"] == ACTIVE] if not rows.empty else rows
    active = active.copy()
    defaults = {
        "late": False,
        "formation_delay_minutes": 0.0,
        "target_1_hit": False,
        "target_2_hit": False,
        "stop_first": False,
        "invalidated_quickly": False,
        "hold_minutes": None,
        "mfe": None,
        "mae": None,
        "exit_reason": None,
    }
    for field, default in defaults.items():
        if field not in active:
            active[field] = default
    metrics = performance_metrics(active)
    original = baseline_count if baseline_count is not None else len(rows)
    base_winners = int((pd.to_numeric(rows.get("base_return"), errors="coerce") > 0).sum()) if not rows.empty else 0
    retained_winners = int((pd.to_numeric(active.get("base_return"), errors="coerce") > 0).sum()) if not active.empty else 0
    retained_losers = len(active) - retained_winners
    removed = rows[rows["status"] != ACTIVE] if not rows.empty else rows
    removed_returns = pd.to_numeric(removed.get("base_return"), errors="coerce") if not removed.empty else pd.Series(dtype=float)
    signal_times = sorted(pd.to_datetime(active["signal_time"], utc=True)) if not active.empty else []
    longest = max(
        ((right - left).total_seconds() / 3600 for left, right in zip(signal_times, signal_times[1:])),
        default=None,
    )
    returns = pd.to_numeric(active.get("realized_return"), errors="coerce").dropna().tolist() if not active.empty else []
    return {
        **metrics,
        "original_alerts": original,
        "retained_alerts": len(active),
        "reduction_percent": (original - len(active)) / original * 100 if original else None,
        "winners_removed": int((removed_returns > 0).sum()),
        "losers_removed": int((removed_returns <= 0).sum()),
        "retained_winners": retained_winners,
        "retained_losers": retained_losers,
        "alerts_per_day": len(active) / trading_days if trading_days else None,
        "longest_no_alert_hours": longest,
        "maximum_drawdown": _max_drawdown(returns),
        "flags": candidate_flags(active, original),
        "performance_driven_by_one_trade": (
            bool(returns)
            and sum(returns) != 0
            and max(returns) / abs(sum(returns)) > 0.5
        ),
        "baseline_winners": base_winners,
    }


def candidate_flags(active, baseline_count):
    flags = []
    if baseline_count and len(active) / baseline_count < 0.25:
        flags.append("fewer than 25% of baseline alerts retained")
    if len(active) < 5:
        flags.append("fewer than 5 active trades")
    if not active.empty and active["symbol"].nunique() == 1:
        flags.append("performance driven by one symbol")
    if not active.empty:
        weeks = pd.to_datetime(active["signal_time"], utc=True).dt.date.map(
            lambda value: value.isocalendar()[:2]
        )
        if len(set(weeks)) == 1:
            flags.append("performance driven by one week")
    return flags


def evidence_label(metrics, minimum_sample=DEFAULT_MINIMUM_SAMPLE):
    if metrics["retained_alerts"] < minimum_sample:
        return "insufficient sample"
    expectancy = metrics.get("expectancy")
    profit_factor = metrics.get("profit_factor")
    if expectancy is None or expectancy < 0:
        return "weak evidence"
    if profit_factor is not None and profit_factor >= 1.25 and metrics["retained_alerts"] >= minimum_sample * 2:
        return "supported"
    return "promising"


def grouped(rows, fields, minimum_sample=DEFAULT_MINIMUM_SAMPLE):
    output = []
    if rows.empty:
        return output
    for keys, group in rows.groupby(list(fields), dropna=False, sort=True):
        if not isinstance(keys, tuple):
            keys = (keys,)
        metrics = selection_metrics(group, baseline_count=len(group))
        output.append(
            {
                **dict(zip(fields, (str(value) for value in keys))),
                "sample_size": len(group[group["status"] == ACTIVE]),
                "win_rate": metrics.get("win_rate"),
                "expectancy": metrics.get("expectancy"),
                "profit_factor": metrics.get("profit_factor"),
                "stop_first_rate": metrics.get("stop_first_rate"),
                "target_1_rate": metrics.get("target_1_rate"),
                "average_mfe": metrics.get("average_mfe"),
                "average_mae": metrics.get("average_mae"),
                "maximum_drawdown": metrics.get("maximum_drawdown"),
                "evidence": evidence_label(metrics, minimum_sample),
            }
        )
    return output


def interaction_analysis(baseline, minimum_sample=DEFAULT_MINIMUM_SAMPLE):
    return {
        " × ".join(fields): grouped(baseline, fields, minimum_sample)
        for fields in INTERACTIONS
    }


def bootstrap_interval(rows, iterations=1000, seed=2002):
    values = pd.to_numeric(
        rows.loc[rows["status"] == ACTIVE, "realized_return"], errors="coerce"
    ).dropna()
    if values.empty:
        return {"sample_size": 0, "lower_95": None, "upper_95": None}
    import random

    rng = random.Random(seed)
    source = values.tolist()
    estimates = sorted(
        mean(rng.choice(source) for _ in source) for _ in range(iterations)
    )
    return {
        "sample_size": len(source),
        "lower_95": estimates[int(iterations * 0.025)],
        "upper_95": estimates[min(iterations - 1, int(iterations * 0.975))],
    }


def walk_forward(model_rows):
    all_times = sorted(
        {pd.Timestamp(value) for rows in model_rows.values() for value in rows["signal_time"]}
    )
    if len(all_times) < 3:
        return {"folds": [], "leave_one_period_out": []}
    cuts = [all_times[len(all_times) // 3], all_times[len(all_times) * 2 // 3]]
    folds = []
    for train_end, validation_end in (
        (cuts[0], cuts[1]),
        (cuts[1], all_times[-1] + pd.Timedelta(microseconds=1)),
    ):
        training = {}
        for name, rows in model_rows.items():
            times = pd.to_datetime(rows["signal_time"], utc=True)
            boundary = pd.Timestamp(train_end)
            boundary = boundary.tz_localize("UTC") if boundary.tzinfo is None else boundary.tz_convert("UTC")
            training[name] = selection_metrics(rows[times < boundary])
        viable = [
            (name, metrics) for name, metrics in training.items()
            if metrics["retained_alerts"] >= 5 and not metrics["flags"]
        ]
        selected = max(
            viable,
            key=lambda item: item[1].get("expectancy")
            if item[1].get("expectancy") is not None else -math.inf,
            default=(None, None),
        )[0]
        rows = model_rows[selected] if selected else pd.DataFrame()
        times = pd.to_datetime(rows["signal_time"], utc=True) if not rows.empty else pd.Series(dtype="datetime64[ns, UTC]")
        start = pd.Timestamp(train_end)
        end = pd.Timestamp(validation_end)
        start = start.tz_localize("UTC") if start.tzinfo is None else start.tz_convert("UTC")
        end = end.tz_localize("UTC") if end.tzinfo is None else end.tz_convert("UTC")
        validation = rows[(times >= start) & (times < end)] if selected else pd.DataFrame()
        folds.append({
            "train_end": pd.Timestamp(train_end).isoformat(),
            "validation_end": pd.Timestamp(validation_end).isoformat(),
            "selected_on_train": selected,
            "train_metrics": training.get(selected),
            "validation_metrics": selection_metrics(validation),
        })
    periods = ((None, cuts[0]), (cuts[0], cuts[1]), (cuts[1], all_times[-1] + pd.Timedelta(microseconds=1)))
    leave_out = []
    for number, (start, end) in enumerate(periods, 1):
        results = {}
        for name, rows in model_rows.items():
            times = pd.to_datetime(rows["signal_time"], utc=True)
            end_value = pd.Timestamp(end)
            end_value = end_value.tz_localize("UTC") if end_value.tzinfo is None else end_value.tz_convert("UTC")
            if start is None:
                held = rows[times < end_value]
            else:
                start_value = pd.Timestamp(start)
                start_value = start_value.tz_localize("UTC") if start_value.tzinfo is None else start_value.tz_convert("UTC")
                held = rows[(times >= start_value) & (times < end_value)]
            results[name] = selection_metrics(held)
        leave_out.append({"period": number, "models": results})
    return {"folds": folds, "leave_one_period_out": leave_out}


def holdouts(rows):
    return {
        "symbol": {
            symbol: selection_metrics(rows[rows["symbol"] == symbol])
            for symbol in sorted(rows["symbol"].unique())
        },
        "direction": {
            direction: selection_metrics(rows[rows["direction"] == direction])
            for direction in sorted(rows["direction"].unique())
        },
    }


def evaluate_experiment(symbol_frames):
    model_rows = evaluate_models(symbol_frames)
    baseline = model_rows["MODEL_A_BASELINE"]
    trading_days = len(
        {pd.Timestamp(value).date() for value in baseline["signal_time"]}
    )
    reports = {}
    for name, rows in model_rows.items():
        metrics = selection_metrics(rows, len(baseline), trading_days)
        reports[name] = {
            "definition": MODELS[name].description,
            "metrics": metrics,
            "bootstrap_expectancy_95": bootstrap_interval(rows),
            "by_symbol": grouped(rows, ("symbol",)),
            "by_direction": grouped(rows, ("direction",)),
            "by_volatility_regime": grouped(rows, ("volatility_regime",)),
            "by_trend_regime": grouped(rows, ("trend_regime",)),
            "by_gap_regime": grouped(rows, ("gap_regime",)),
            "by_higher_timeframe_alignment": grouped(
                rows, ("higher_timeframe_alignment",)
            ),
            "by_time_window": grouped(rows, ("time_window",)),
            "holdouts": holdouts(rows),
        }
    return {
        "models": reports,
        "interactions": interaction_analysis(baseline),
        "walk_forward": walk_forward(model_rows),
        "rows": pd.concat(model_rows.values(), ignore_index=True),
    }


def shadow_record(result, frame=None, index=None, now=None):
    snapshot = dict(result or {})
    signal = snapshot.get("signal")
    direction = (
        "Bullish" if signal == "BULLISH SETUP"
        else "Bearish" if signal == "BEARISH SETUP"
        else None
    )
    plan = dict(snapshot.get("trade_plan") or {})
    timestamp = snapshot.get("last_candle_at") or snapshot.get("timestamp") or (
        now or datetime.now()
    ).isoformat()
    context = {
        "symbol": snapshot.get("symbol"),
        "direction": direction.lower() if direction else None,
        "volatility_regime": None,
        "trend_regime": None,
        "gap_regime": None,
        "higher_timeframe_alignment": None,
        "time_window": time_window(timestamp),
    }
    if frame is not None and index is not None and 0 <= index < len(frame):
        from optimization_analysis import classify_market_regime, higher_timeframe_alignment

        regime = classify_market_regime(frame.iloc[: index + 1], index)
        alignment = (
            higher_timeframe_alignment(frame.iloc[: index + 1], index, direction)
            if direction else "unavailable"
        )
        context.update({
            "volatility_regime": volatility_regime(regime["regime"]),
            "trend_regime": trend_regime(regime["regime"]),
            "gap_regime": gap_regime(regime["opening_gap_atr"], regime["regime"]),
            "higher_timeframe_alignment": {
                "aligned": "aligned",
                "partially aligned": "neutral",
                "non-aligned": "opposed",
                "unavailable": "neutral",
            }.get(alignment, "neutral"),
        })
    eligible = direction is not None and bool(plan)
    rejection_reasons = []
    if not eligible:
        rejection_reasons.append("not an eligible directional production setup")
    if eligible and context["gap_regime"] == "gap reversal":
        rejection_reasons.append("simple gate rejects gap reversal")
    if eligible and context["time_window"] == "14:00-15:00":
        rejection_reasons.append("simple gate rejects 14:00-15:00")
    if eligible and context["higher_timeframe_alignment"] == "opposed":
        rejection_reasons.append("simple gate rejects opposed higher timeframe")
    exp002_eligible = eligible and not rejection_reasons
    rejection = "; ".join(rejection_reasons) or None
    identity = "|".join(str(value) for value in (
        EXPERIMENT_ID, context["symbol"], context["direction"],
        snapshot.get("setup") or signal, timestamp, plan.get("entry"),
    ))
    return {
        "experiment_id": EXPERIMENT_ID,
        "shadow_id": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
        "timestamp": timestamp,
        "context": context,
        "eligible": exp002_eligible,
        "selected_model": "MODEL_G_SIMPLE_GATES",
        "selected_model_decision": "PARTICIPATE" if exp002_eligible else "REJECT",
        "rejection_reason": rejection,
        "theoretical_entry": plan.get("entry"),
        "theoretical_stop": plan.get("stop"),
        "theoretical_targets": [
            plan.get("target_1"), plan.get("target_2"), plan.get("target_3")
        ],
        "risk_reward": plan.get("risk_reward"),
        "symbol": context["symbol"],
        "direction": context["direction"],
        "time_window": context["time_window"],
    }


def append_shadow_record(record, path=DEFAULT_SHADOW_FILE):
    try:
        target = Path(path)
        if target.exists():
            for line in target.read_text(encoding="utf-8").splitlines():
                try:
                    if json.loads(line).get("shadow_id") == record.get("shadow_id"):
                        return False
                except json.JSONDecodeError:
                    continue
        with target.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, sort_keys=True, default=str) + "\n")
        return True
    except Exception as exc:
        LOGGER.warning("Experiment 002 shadow write failed: %s", exc)
        return False


def record_live_shadow(result, frame, index, path=DEFAULT_SHADOW_FILE):
    record = shadow_record(result, frame, index)
    append_shadow_record(record, path)
    return result
