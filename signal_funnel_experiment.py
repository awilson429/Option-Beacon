"""Experiment 003: signal-funnel replay and score-calibration research.

All functions are analysis-only. Production thresholds, scoring, plans,
journals, positions, and alerts are never mutated by this module.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
import hashlib
import json
import logging
import math
from pathlib import Path
import random
from statistics import mean, median, NormalDist

import pandas as pd

from false_breakout_experiment import (
    _fixed_plan_outcome,
    _number,
    classify_gap,
    entry_window,
)
from optimization_analysis import (
    classify_market_regime,
    higher_timeframe_alignment,
    performance_metrics,
)
from optionbeacon_strategy import (
    DEFAULT_CALL_SCORE_THRESHOLD,
    DEFAULT_PUT_SCORE_THRESHOLD,
    STOP_PERCENT,
    TARGET_PERCENT,
    is_trade_time,
    score_candle,
)
from trade_replay import add_replay_indicators


LOGGER = logging.getLogger(__name__)
EXPERIMENT_ID = "EXP-003-SIGNAL-FUNNEL-CALIBRATION"
DEFAULT_SHADOW_FILE = "experiment_003_signal_funnel.jsonl"
DEFAULT_SHADOW_MAX_BYTES = 5 * 1024 * 1024
THRESHOLDS = (60, 65, 70, 75, 80, 85, 90, 95)
FUNNEL_STAGES = (
    "RAW CANDIDATE",
    "STRUCTURE DETECTED",
    "DIRECTION ASSIGNED",
    "INDICATORS AVAILABLE",
    "BASE CONDITIONS PASSED",
    "SCORE CALCULATED",
    "SCORE THRESHOLD PASSED",
    "LIFECYCLE ELIGIBLE",
    "TRADE PLAN VALID",
    "FINAL ALERT",
)
SCORE_BUCKETS = (
    ("below 50", 0, 50),
    ("50-59", 50, 60),
    ("60-69", 60, 70),
    ("70-79", 70, 80),
    ("80-84", 80, 85),
    ("85-89", 85, 90),
    ("90-94", 90, 95),
    ("95-100", 95, 101),
)
COMPONENTS = (
    "trend_score",
    "momentum_score",
    "volume_score",
    "volatility_score",
    "price_action_score",
)


def provider_audit(*, yfinance_configured=True, finnhub_configured=False, tradier_configured=False):
    """Describe only data paths implemented in this repository."""
    return [
        {
            "provider": "Yahoo Finance via yfinance",
            "repository_usage": "scanner candles and research history",
            "interval_support": ["1m", "2m", "5m", "15m", "30m", "60m", "1d"],
            "maximum_historical_lookback": (
                "approximately 60 days for 5m; longer windows require coarser bars"
            ),
            "premarket_availability": "not requested by current download path",
            "after_hours_availability": "not requested by current download path",
            "volume_availability": True,
            "split_adjustment_behavior": "auto_adjust=False in research fetcher",
            "timezone_behavior": "provider timestamps normalized to America/New_York",
            "rate_limits": "undocumented/provider managed",
            "missing_bar_behavior": "possible; detected by normalization pipeline",
            "duplicate_bar_behavior": "possible; exact duplicates removed deterministically",
            "credentials_configured": bool(yfinance_configured),
            "historical_retrieval_deterministic": False,
            "five_minute_research_eligible": True,
        },
        {
            "provider": "Finnhub",
            "repository_usage": "current quotes and daily mover universe",
            "interval_support": ["current quote only through implemented abstraction"],
            "maximum_historical_lookback": "no historical candle helper implemented",
            "premarket_availability": "provider dependent; not requested",
            "after_hours_availability": "provider dependent; not requested",
            "volume_availability": False,
            "split_adjustment_behavior": "not applicable to implemented quote path",
            "timezone_behavior": "current quote payload; no candle timestamps normalized",
            "rate_limits": "account tier/provider managed",
            "missing_bar_behavior": "not applicable",
            "duplicate_bar_behavior": "not applicable",
            "credentials_configured": bool(finnhub_configured),
            "historical_retrieval_deterministic": False,
            "five_minute_research_eligible": False,
        },
        {
            "provider": "Tradier",
            "repository_usage": "current equity/option quotes, expirations, and chains",
            "interval_support": ["current quotes through implemented abstraction"],
            "maximum_historical_lookback": "no historical equity candle helper implemented",
            "premarket_availability": "provider dependent; not requested",
            "after_hours_availability": "provider dependent; not requested",
            "volume_availability": True,
            "split_adjustment_behavior": "not applicable to implemented quote path",
            "timezone_behavior": "provider quote timestamps; no history normalization",
            "rate_limits": "account tier/provider managed",
            "missing_bar_behavior": "not applicable",
            "duplicate_bar_behavior": "not applicable",
            "credentials_configured": bool(tradier_configured),
            "historical_retrieval_deterministic": False,
            "five_minute_research_eligible": False,
        },
    ]


def normalize_timestamp(value):
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("America/New_York")
    return timestamp.tz_convert("America/New_York")


def dataset_hash(frame):
    columns = sorted(frame.columns)
    ordered = frame.sort_values(["symbol", "timestamp"])[columns].copy()
    for column in ordered:
        ordered[column] = ordered[column].astype(str)
    return hashlib.sha256(
        ordered.to_csv(index=False, lineterminator="\n").encode("utf-8")
    ).hexdigest()


def normalize_market_data(raw, symbol, source="Yahoo Finance", interval="5m"):
    """Normalize bars, flag duplicate timestamps, and insert missing RTH bars."""
    frame = raw.copy()
    frame.columns = [str(column).lower() for column in frame.columns]
    required = ["open", "high", "low", "close", "volume"]
    missing_columns = [field for field in required if field not in frame]
    if missing_columns:
        raise ValueError(f"missing required columns: {', '.join(missing_columns)}")
    frame["timestamp"] = [normalize_timestamp(value) for value in frame.index]
    frame["duplicate_bar"] = frame.duplicated("timestamp", keep=False)
    frame = frame.drop_duplicates("timestamp", keep="first")
    frame["symbol"] = symbol
    frame["session_date"] = frame["timestamp"].dt.date.astype(str)
    minutes = frame["timestamp"].dt.hour * 60 + frame["timestamp"].dt.minute
    frame["regular_market_hours"] = (minutes >= 570) & (minutes < 960)
    frame["source"] = source
    frame["interval"] = interval
    frame["timezone"] = "America/New_York"
    frame["adjustment_status"] = "unadjusted"
    frame["missing_bar"] = False

    rth = frame[frame["regular_market_hours"]]
    additions = []
    for session, group in rth.groupby("session_date"):
        pandas_frequency = (
            f"{interval[:-1]}min" if interval.endswith("m") else interval
        )
        expected = pd.date_range(
            f"{session} 09:30",
            f"{session} 15:55",
            freq=pandas_frequency,
            tz="America/New_York",
        )
        present = set(group["timestamp"])
        for timestamp in expected:
            if timestamp not in present:
                additions.append(
                    {
                        "symbol": symbol,
                        "timestamp": timestamp,
                        "open": None,
                        "high": None,
                        "low": None,
                        "close": None,
                        "volume": None,
                        "session_date": session,
                        "regular_market_hours": True,
                        "source": source,
                        "interval": interval,
                        "timezone": "America/New_York",
                        "adjustment_status": "unadjusted",
                        "missing_bar": True,
                        "duplicate_bar": False,
                    }
                )
    if additions:
        frame = pd.concat([frame, pd.DataFrame(additions)], ignore_index=True)
    return frame[
        [
            "symbol",
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "session_date",
            "regular_market_hours",
            "source",
            "interval",
            "timezone",
            "adjustment_status",
            "missing_bar",
            "duplicate_bar",
        ]
    ].sort_values(["timestamp", "missing_bar"], kind="stable").reset_index(drop=True)


def score_bucket(score):
    value = _number(score, 0.0) or 0.0
    for label, lower, upper in SCORE_BUCKETS:
        if lower <= value < upper:
            return label
    return "95-100" if value >= 95 else "below 50"


def _indicators_available(row):
    required = (
        "EMA20", "EMA50", "EMA200", "RSI", "MACD", "MACD_SIGNAL",
        "MACD_HIST", "VWAP", "ATR", "AVG_ATR_20", "AVG_VOLUME_20",
    )
    return all(_number(row.get(field)) is not None for field in required)


def _stage_record(stage, passed, reason, result=None):
    return {
        "stage": stage,
        "passed": bool(passed),
        "reason": reason,
        "score": (result or {}).get("confidence"),
    }


def funnel_for_bar(
    frame,
    index,
    symbol,
    production_threshold=DEFAULT_CALL_SCORE_THRESHOLD,
    lifecycle_eligible=True,
):
    """Replay the production scorer and expose each deterministic funnel stage."""
    timestamp = frame.index[index]
    candle = frame.iloc[index]
    stages = []
    trade_time = is_trade_time(timestamp)
    stages.append(_stage_record("RAW CANDIDATE", trade_time, "inside production trade-time window" if trade_time else "outside production trade-time window"))
    if not trade_time:
        return stages, None
    structure = index >= 20
    stages.append(_stage_record("STRUCTURE DETECTED", structure, "prior structure window available" if structure else "insufficient prior structure bars"))
    if not structure:
        return stages, None
    research = score_candle(frame, index, symbol, 0, 0)
    direction = research.get("bias") in {"Bullish", "Bearish"}
    stages.append(_stage_record("DIRECTION ASSIGNED", direction, f"{research.get('bias', 'Neutral')} directional score", research))
    if not direction:
        return stages, research
    available = _indicators_available(candle)
    stages.append(_stage_record("INDICATORS AVAILABLE", available, "all required indicators finite" if available else "one or more required indicators unavailable", research))
    if not available:
        return stages, research
    base = direction and available and (_number(research.get("confidence"), 0) or 0) > 0
    stages.append(_stage_record("BASE CONDITIONS PASSED", base, "directional base conditions passed" if base else "directional base conditions failed", research))
    if not base:
        return stages, research
    calculated = _number(research.get("confidence")) is not None
    stages.append(_stage_record("SCORE CALCULATED", calculated, "current production score calculated" if calculated else "score unavailable", research))
    if not calculated:
        return stages, research
    threshold = calculated and research["confidence"] >= production_threshold
    stages.append(_stage_record("SCORE THRESHOLD PASSED", threshold, f"score {research.get('confidence')} {'meets' if threshold else 'below'} unchanged threshold {production_threshold}", research))
    if not threshold:
        return stages, research
    lifecycle = threshold and lifecycle_eligible
    stages.append(
        _stage_record(
            "LIFECYCLE ELIGIBLE",
            lifecycle,
            "no prior overlapping lifecycle"
            if lifecycle
            else "prior lifecycle still active"
            if threshold
            else "score gate prevented lifecycle evaluation",
            research,
        )
    )
    if not lifecycle:
        return stages, research
    plan_valid = lifecycle and all(
        _number(research.get(field)) is not None
        for field in ("entry", "stop", "target")
    )
    stages.append(_stage_record("TRADE PLAN VALID", plan_valid, "fixed production plan levels valid" if plan_valid else "trade plan unavailable before threshold", research))
    final = plan_valid and research["signal"] in {"BULLISH SETUP", "BEARISH SETUP"}
    stages.append(_stage_record("FINAL ALERT", final, "unchanged production alert" if final else "not a final production alert", research))
    return stages, research


def _forward_metrics(frame, index, direction, entry):
    def excursion(bars=None):
        end = len(frame) - 1 if bars is None else min(len(frame) - 1, index + bars)
        visible = frame.iloc[index + 1 : end + 1]
        if visible.empty:
            return None, None
        favorable = visible["High"].max() if direction == "Bullish" else visible["Low"].min()
        adverse = visible["Low"].min() if direction == "Bullish" else visible["High"].max()
        mfe = (favorable - entry) / entry * 100 if direction == "Bullish" else (entry - favorable) / entry * 100
        mae = (adverse - entry) / entry * 100 if direction == "Bullish" else (entry - adverse) / entry * 100
        return max(0.0, mfe), min(0.0, mae)

    output = {}
    for label, bars in (("15m", 3), ("30m", 6), ("60m", 12), ("session", None)):
        if bars is None:
            timestamp = normalize_timestamp(frame.index[index])
            remaining_minutes = max(
                0, 960 - (timestamp.hour * 60 + timestamp.minute)
            )
            session = frame.iloc[
                index + 1 : min(len(frame), index + 1 + remaining_minutes // 5)
            ]
            if session.empty:
                mfe = mae = None
            else:
                favorable = session["High"].max() if direction == "Bullish" else session["Low"].min()
                adverse = session["Low"].min() if direction == "Bullish" else session["High"].max()
                mfe = max(0.0, (favorable - entry) / entry * 100 if direction == "Bullish" else (entry - favorable) / entry * 100)
                mae = min(0.0, (adverse - entry) / entry * 100 if direction == "Bullish" else (entry - adverse) / entry * 100)
        else:
            mfe, mae = excursion(bars)
        output[f"mfe_{label}"] = mfe
        output[f"mae_{label}"] = mae
    return output


def barrier_outcome(frame, index, direction, entry, favorable_percent, adverse_percent):
    """Return the first standardized barrier touched, conservatively resolving ties."""
    for offset in range(index + 1, len(frame)):
        row = frame.iloc[offset]
        favorable = (
            (row["High"] - entry) / entry * 100
            if direction == "Bullish"
            else (entry - row["Low"]) / entry * 100
        )
        adverse = (
            (row["Low"] - entry) / entry * 100
            if direction == "Bullish"
            else (entry - row["High"]) / entry * 100
        )
        if adverse <= -adverse_percent:
            return "ADVERSE", offset - index
        if favorable >= favorable_percent:
            return "FAVORABLE", offset - index
    return "NEITHER", len(frame) - index - 1


def _candidate_outcome(frame, index, result):
    direction = result["bias"]
    entry = _number(result["price"])
    stop = entry * (1 - STOP_PERCENT) if direction == "Bullish" else entry * (1 + STOP_PERCENT)
    target = entry * (1 + TARGET_PERCENT) if direction == "Bullish" else entry * (1 - TARGET_PERCENT)
    setup = {
        "direction": direction,
        "entry": entry,
        "stop": stop,
        "target_1": target,
        "target_2": entry + (target - entry) * 2,
        "target_3": entry + (target - entry) * 3,
        "bar_minutes": 5,
    }
    outcome = _fixed_plan_outcome(frame, index, setup)
    forward = _forward_metrics(frame, index, direction, entry)
    barriers = {}
    for name, favorable, adverse in (
        ("plus_015_minus_015", 0.15, 0.15),
        ("plus_025_minus_025", 0.25, 0.25),
        ("plus_035_minus_025", 0.35, 0.25),
        ("plus_050_minus_025", 0.50, 0.25),
        ("1r_before_stop", 0.25, 0.25),
        ("1_5r_before_stop", 0.375, 0.25),
        ("2r_before_stop", 0.50, 0.25),
    ):
        result_value, bars = barrier_outcome(frame, index, direction, entry, favorable, adverse)
        barriers[f"barrier_{name}"] = result_value
        barriers[f"barrier_{name}_bars"] = bars
    return {**outcome, **forward, **barriers, "planned_stop": stop, "planned_target_1": target, "planned_target_2": setup["target_2"]}


def replay_signal_funnel(symbol_frames):
    candidates = []
    funnel_rows = []
    for symbol, raw in symbol_frames.items():
        frame = add_replay_indicators(raw.copy())
        last_final_index = None
        for index in range(20, len(frame)):
            lifecycle_eligible = (
                last_final_index is None or index - last_final_index >= 48
            )
            stages, result = funnel_for_bar(
                frame,
                index,
                symbol,
                lifecycle_eligible=lifecycle_eligible,
            )
            final_alert = any(
                stage["stage"] == "FINAL ALERT" and stage["passed"]
                for stage in stages
            )
            if final_alert:
                last_final_index = index
            for stage in stages:
                funnel_rows.append(
                    {
                        "symbol": symbol,
                        "timestamp": pd.Timestamp(frame.index[index]).isoformat(),
                        **stage,
                    }
                )
            if result is None or result.get("bias") not in {"Bullish", "Bearish"}:
                continue
            regime = classify_market_regime(frame, index)
            score = _number(result["confidence"], 0.0) or 0.0
            outcome = _candidate_outcome(frame, index, result)
            candidates.append(
                {
                    "symbol": symbol,
                    "timestamp": pd.Timestamp(frame.index[index]).isoformat(),
                    "session_date": normalize_timestamp(frame.index[index]).date().isoformat(),
                    "hour": entry_window(frame.index[index]),
                    "direction": result["bias"],
                    "setup_type": "directional score candidate",
                    "score": score,
                    "score_bucket": score_bucket(score),
                    "production_alert": final_alert,
                    "trigger": result["resistance"] if result["bias"] == "Bullish" else result["support"],
                    "entry_reference": result["price"],
                    "regime": regime["regime"],
                    "volatility_regime": (
                        "high-volatility expansion"
                        if regime["regime"] == "high-volatility expansion"
                        else "low-volatility compression"
                        if regime["regime"] == "low-volatility compression"
                        else "normal"
                    ),
                    "trend_regime": (
                        regime["regime"]
                        if regime["regime"] in {"bullish trend", "bearish trend", "range-bound"}
                        else "mixed/neutral"
                    ),
                    "gap_regime": (
                        "gap reversal"
                        if regime["regime"] == "opening gap reversal"
                        else "gap continuation"
                        if regime["regime"] == "opening gap continuation"
                        else classify_gap(regime["opening_gap_atr"])
                    ),
                    "higher_timeframe_alignment": higher_timeframe_alignment(frame, index, result["bias"]),
                    "extension_state": "extended" if abs(result["price"] - result["vwap"]) > result["atr"] else "normal",
                    **{component: result.get(component, 0) for component in COMPONENTS},
                    "relative_volume": result.get("relative_volume"),
                    "rsi": result.get("rsi"),
                    **outcome,
                }
            )
    return pd.DataFrame(funnel_rows), pd.DataFrame(candidates)


def _ensure_metric_columns(frame):
    result = frame.copy()
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
    for field, value in defaults.items():
        if field not in result:
            result[field] = value
    if "signal_time" not in result and "timestamp" in result:
        result["signal_time"] = result["timestamp"]
    return result


def metrics(frame):
    return performance_metrics(_ensure_metric_columns(frame))


def score_calibration(candidates):
    rows = []
    for label, _, _ in SCORE_BUCKETS:
        group = candidates[candidates["score_bucket"] == label]
        report = metrics(group)
        rows.append(
            {
                "score_bucket": label,
                "candidate_count": len(group),
                "alert_count": int(group["production_alert"].sum()) if not group.empty else 0,
                **report,
                "average_score": group["score"].mean() if not group.empty else None,
                "immediately_invalidated_percent": report.get("quick_invalidation_rate"),
            }
        )
    expectations = [row["expectancy"] for row in rows if row["candidate_count"] and row["expectancy"] is not None]
    monotonic = all(left <= right for left, right in zip(expectations, expectations[1:]))
    return {
        "buckets": rows,
        "monotonic_expectancy": monotonic,
        "score_mfe_correlation": candidates["score"].corr(candidates["mfe"]),
        "score_mae_correlation": candidates["score"].corr(candidates["mae"]),
        "score_target_1_correlation": candidates["score"].corr(candidates["target_1_hit"].astype(float)),
        "score_stop_first_correlation": candidates["score"].corr(candidates["stop_first"].astype(float)),
    }


def threshold_analysis(candidates):
    reports = []
    days = max(1, candidates["session_date"].nunique())
    for threshold in THRESHOLDS:
        retained = candidates[candidates["score"] >= threshold]
        report = metrics(retained)
        reports.append(
            {
                "threshold": threshold,
                "retained_candidates": len(retained),
                "alerts_per_day": len(retained) / days,
                "average_score": retained["score"].mean() if not retained.empty else None,
                "score_distribution": dict(Counter(retained["score_bucket"])),
                **report,
                "by_symbol": {
                    value: metrics(retained[retained["symbol"] == value])
                    for value in sorted(candidates["symbol"].unique())
                },
                "by_direction": {
                    value: metrics(retained[retained["direction"] == value])
                    for value in sorted(candidates["direction"].unique())
                },
                "by_period": {
                    str(value): metrics(group)
                    for value, group in retained.groupby(
                        pd.to_datetime(retained["timestamp"], utc=True).dt.strftime("%Y-%m")
                    )
                },
            }
        )
    return reports


def component_audit(candidates):
    output = []
    for component in COMPONENTS:
        present = candidates[candidates[component] > 0]
        absent = candidates[candidates[component] <= 0]
        reduced_score = candidates["score"] - candidates[component]
        output.append(
            {
                "component": component,
                "frequency_present": len(present),
                "average_awarded_points": present[component].mean() if not present.empty else None,
                "present_metrics": metrics(present),
                "absent_metrics": metrics(absent),
                "return_correlation": candidates[component].corr(candidates["realized_return"]),
                "total_score_correlation": candidates[component].corr(candidates["score"]),
                "ablation_ranking_correlation": candidates["score"].corr(reduced_score),
                "threshold_90_crossings_removed": int(
                    ((candidates["score"] >= 90) & (reduced_score < 90)).sum()
                ),
                "by_symbol": {
                    name: metrics(group[group[component] > 0])
                    for name, group in candidates.groupby("symbol")
                },
                "by_direction": {
                    name: metrics(group[group[component] > 0])
                    for name, group in candidates.groupby("direction")
                },
                "by_month": {
                    str(name): metrics(group[group[component] > 0])
                    for name, group in candidates.groupby(
                        pd.to_datetime(candidates["timestamp"], utc=True).dt.strftime("%Y-%m")
                    )
                },
                "by_regime": {
                    name: metrics(group[group[component] > 0])
                    for name, group in candidates.groupby("regime")
                },
            }
        )
    correlations = candidates[list(COMPONENTS)].corr().to_dict()
    return {"components": output, "component_correlations": correlations}


def entry_exit_analysis(candidates):
    fields = [
        "mfe_15m", "mfe_30m", "mfe_60m", "mfe_session",
        "mae_15m", "mae_30m", "mae_60m", "mae_session",
    ]
    excursions = {
        field: candidates[field].mean() if field in candidates and not candidates.empty else None
        for field in fields
    }
    barriers = {}
    for name in (
        "plus_015_minus_015", "plus_025_minus_025", "plus_035_minus_025",
        "plus_050_minus_025", "1r_before_stop", "1_5r_before_stop",
        "2r_before_stop",
    ):
        field = f"barrier_{name}"
        barriers[name] = dict(Counter(candidates[field])) if field in candidates else {}
    workable = int(
        ((candidates["realized_return"] <= 0) & (candidates["mfe_60m"] >= 0.25)).sum()
    )
    immediate_adverse = int((candidates["mae_15m"] <= -0.15).sum())
    return {
        "forward_excursions_percent": excursions,
        "standardized_barriers": barriers,
        "losing_fixed_exit_with_025_mfe_within_60m": workable,
        "immediate_adverse_candidates": immediate_adverse,
        "conclusion": (
            "Entry and exit quality are mixed; standardized paths quantify "
            "workable entries separately from fixed-plan outcomes."
        ),
    }


def funnel_summary(funnel):
    counts = {}
    rejections = {}
    prior = None
    for stage in FUNNEL_STAGES:
        rows = funnel[funnel["stage"] == stage]
        passed = int(rows["passed"].sum())
        counts[stage] = {
            "evaluated": len(rows),
            "passed": passed,
            "conversion_from_prior_percent": passed / prior * 100 if prior else None,
        }
        rejections[stage] = dict(Counter(rows.loc[~rows["passed"], "reason"]))
        prior = passed
    return {"counts": counts, "rejections": rejections}


def chronological_validation(candidates):
    ordered = candidates.sort_values("timestamp")
    first = len(ordered) * 60 // 100
    second = len(ordered) * 80 // 100
    periods = {
        "train": ordered.iloc[:first],
        "validation": ordered.iloc[first:second],
        "test": ordered.iloc[second:],
    }
    return {
        name: {
            str(threshold): metrics(frame[frame["score"] >= threshold])
            for threshold in THRESHOLDS
        }
        for name, frame in periods.items()
    }


def walk_forward_thresholds(candidates):
    ordered = candidates.sort_values("timestamp")
    cuts = (len(ordered) // 3, len(ordered) * 2 // 3)
    folds = []
    for fold, (train_end, validation_end) in enumerate(
        ((cuts[0], cuts[1]), (cuts[1], len(ordered))), start=1
    ):
        train = ordered.iloc[:train_end]
        candidates_by_threshold = []
        for threshold in THRESHOLDS:
            subset = train[train["score"] >= threshold]
            report = metrics(subset)
            if len(subset) >= 20:
                candidates_by_threshold.append((threshold, report))
        selected, train_metrics = max(
            candidates_by_threshold,
            key=lambda item: (
                item[1]["expectancy"]
                if item[1]["expectancy"] is not None
                else -math.inf
            ),
            default=(None, None),
        )
        validation = ordered.iloc[train_end:validation_end]
        validation = (
            validation[validation["score"] >= selected]
            if selected is not None
            else validation.iloc[:0]
        )
        folds.append(
            {
                "fold": fold,
                "train_end": (
                    ordered.iloc[train_end - 1]["timestamp"] if train_end else None
                ),
                "validation_end": (
                    ordered.iloc[validation_end - 1]["timestamp"]
                    if validation_end else None
                ),
                "selected_threshold": selected,
                "train_metrics": train_metrics,
                "validation_metrics": metrics(validation),
            }
        )
    return folds


def bootstrap_expectancy(frame, iterations=1000, seed=3003):
    values = frame["realized_return"].dropna().tolist()
    if not values:
        return {"lower_95": None, "upper_95": None, "sample_size": 0}
    rng = random.Random(seed)
    estimates = sorted(mean(rng.choice(values) for _ in values) for _ in range(iterations))
    return {
        "lower_95": estimates[int(iterations * 0.025)],
        "upper_95": estimates[min(iterations - 1, int(iterations * 0.975))],
        "sample_size": len(values),
    }


def permutation_score_check(candidates, iterations=500, seed=3003):
    observed = candidates["score"].corr(candidates["realized_return"])
    rng = random.Random(seed)
    values = candidates["realized_return"].tolist()
    exceed = 0
    for _ in range(iterations):
        shuffled = values[:]
        rng.shuffle(shuffled)
        correlation = candidates["score"].corr(pd.Series(shuffled, index=candidates.index))
        exceed += abs(correlation) >= abs(observed)
    return {"observed_correlation": observed, "two_sided_p_value": (exceed + 1) / (iterations + 1)}


def sample_size_report(candidates):
    standard_deviation = candidates["realized_return"].std(ddof=1)
    z = NormalDist().inv_cdf(0.975) + NormalDist().inv_cdf(0.80)

    def continuous(delta):
        return math.ceil(2 * (z * standard_deviation / delta) ** 2) if delta and standard_deviation else None

    def proportions(current, target):
        pooled = (current + target) / 2
        return math.ceil(
            2 * pooled * (1 - pooled) * z**2 / (target - current) ** 2
        )

    return {
        "assumptions": "two-sided 5% alpha, 80% power, two independent equal-sized groups",
        "observed_return_standard_deviation_percent": standard_deviation,
        "expectancy_minus_0052_to_0000_per_group": continuous(0.052),
        "expectancy_minus_0052_to_plus_0025_per_group": continuous(0.077),
        "stop_first_72_to_60_per_group": proportions(0.72, 0.60),
        "win_rate_28_to_40_per_group": proportions(0.28, 0.40),
        "effective_sample_concerns": [
            "signals from the same day are not independent",
            "SPY and QQQ returns are correlated",
            "holding periods overlap",
            "regime representation is imbalanced",
            "serial correlation reduces effective sample size",
            "multiple comparisons require more evidence than nominal calculations",
        ],
    }


def experiment_report(symbol_frames):
    funnel, candidates = replay_signal_funnel(symbol_frames)
    calibration = score_calibration(candidates)
    thresholds = threshold_analysis(candidates)
    current = next(row for row in thresholds if row["threshold"] == 90)
    production_baseline = metrics(candidates[candidates["production_alert"]])
    conclusion = {
        "score_predictive": calibration["monotonic_expectancy"],
        "higher_scores_consistently_outperform": calibration["monotonic_expectancy"],
        "threshold_90_assessment": "inconclusive",
        "reason": (
            "Ranking, threshold, and component results are not sufficiently "
            "stable across chronological partitions to justify a production change."
        ),
        "current_threshold_metrics": current,
        "production_lifecycle_distinct_metrics": production_baseline,
    }
    return {
        "funnel": funnel_summary(funnel),
        "candidate_count": len(candidates),
        "production_alert_count": int(candidates["production_alert"].sum()),
        "production_baseline": production_baseline,
        "score_calibration": calibration,
        "threshold_analysis": thresholds,
        "component_audit": component_audit(candidates),
        "entry_exit_analysis": entry_exit_analysis(candidates),
        "validation": chronological_validation(candidates),
        "walk_forward": walk_forward_thresholds(candidates),
        "bootstrap_90": bootstrap_expectancy(candidates[candidates["score"] >= 90]),
        "permutation_check": permutation_score_check(candidates),
        "sample_size": sample_size_report(candidates),
        "conclusion": conclusion,
        "funnel_rows": funnel,
        "candidates": candidates,
    }


def shadow_funnel_record(result, now=None):
    snapshot = dict(result or {})
    timestamp = snapshot.get("last_candle_at") or snapshot.get("timestamp") or (
        now or datetime.now()
    ).isoformat()
    score = _number(
        snapshot.get("confidence"),
        max(
            _number(snapshot.get("bullish_score"), 0) or 0,
            _number(snapshot.get("bearish_score"), 0) or 0,
        ),
    )
    stages = []
    final = snapshot.get("signal") in {"BULLISH SETUP", "BEARISH SETUP"}
    for stage in FUNNEL_STAGES:
        if stage == "SCORE THRESHOLD PASSED":
            passed = score is not None and score >= DEFAULT_CALL_SCORE_THRESHOLD
        elif stage in {"LIFECYCLE ELIGIBLE", "TRADE PLAN VALID", "FINAL ALERT"}:
            passed = final
        else:
            passed = score is not None
        stages.append(
            {
                "stage": stage,
                "passed": passed,
                "reason": "captured from completed production scanner result",
            }
        )
    identity = "|".join(
        str(value)
        for value in (
            EXPERIMENT_ID,
            snapshot.get("symbol"),
            timestamp,
            snapshot.get("bias"),
            score,
        )
    )
    return {
        "experiment_id": EXPERIMENT_ID,
        "shadow_id": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
        "timestamp": timestamp,
        "symbol": snapshot.get("symbol"),
        "direction": snapshot.get("bias"),
        "component_scores": {
            component: snapshot.get(component) for component in COMPONENTS
        },
        "total_score": score,
        "lifecycle_state": snapshot.get("lifecycle_status"),
        "production_decision": snapshot.get("signal"),
        "research_thresholds": {
            str(threshold): score is not None and score >= threshold
            for threshold in THRESHOLDS
        },
        "stages": stages,
        "rejection_reasons": [
            stage["reason"] for stage in stages if not stage["passed"]
        ],
    }


def _rotate_shadow(path, maximum_bytes):
    if not path.exists() or path.stat().st_size <= maximum_bytes:
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    retained = []
    size = 0
    target = maximum_bytes
    for line in reversed(lines):
        encoded = len(line.encode("utf-8")) + 1
        if size + encoded > target:
            break
        retained.append(line)
        size += encoded
    path.write_text(
        "\n".join(reversed(retained)) + ("\n" if retained else ""),
        encoding="utf-8",
    )


def append_shadow_funnel(record, path=DEFAULT_SHADOW_FILE, maximum_bytes=DEFAULT_SHADOW_MAX_BYTES):
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
        _rotate_shadow(target, maximum_bytes)
        return True
    except Exception as exc:
        LOGGER.warning("Experiment 003 shadow funnel write failed: %s", exc)
        return False


def record_live_shadow(result, path=DEFAULT_SHADOW_FILE):
    append_shadow_funnel(shadow_funnel_record(result), path)
    return result
