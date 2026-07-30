from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pandas as pd

from optionbeacon_strategy import (
    DEFAULT_CALL_SCORE_THRESHOLD,
    DEFAULT_PUT_SCORE_THRESHOLD,
)
from signal_funnel_experiment import (
    COMPONENTS,
    FUNNEL_STAGES,
    SCORE_BUCKETS,
    THRESHOLDS,
    append_shadow_funnel,
    barrier_outcome,
    dataset_hash,
    funnel_for_bar,
    normalize_market_data,
    normalize_timestamp,
    provider_audit,
    record_live_shadow,
    score_bucket,
    shadow_funnel_record,
    threshold_analysis,
    walk_forward_thresholds,
)


def _frame(periods=40):
    index = pd.date_range(
        "2026-07-27 09:30",
        periods=periods,
        freq="5min",
        tz="America/New_York",
    )
    values = np.linspace(100, 102, periods)
    return pd.DataFrame(
        {
            "Open": values - 0.05,
            "High": values + 0.20,
            "Low": values - 0.20,
            "Close": values,
            "Volume": np.linspace(1000, 2500, periods),
            "EMA20": values - 0.10,
            "EMA50": values - 0.20,
            "EMA200": values - 0.30,
            "RSI": 60,
            "MACD": 1.0,
            "MACD_SIGNAL": 0.5,
            "MACD_HIST": np.linspace(0.1, 0.5, periods),
            "VWAP": values - 0.05,
            "ATR": 0.5,
            "AVG_ATR_20": 0.4,
            "AVG_VOLUME_20": 1200,
        },
        index=index,
    )


def _candidate_rows():
    rows = []
    for index, score in enumerate((55, 62, 72, 82, 87, 91, 97)):
        won = index % 2 == 0
        rows.append(
            {
                "timestamp": f"2026-07-{20 + index:02d}T10:00:00-04:00",
                "session_date": f"2026-07-{20 + index:02d}",
                "symbol": "SPY" if index % 2 else "QQQ",
                "direction": "Bullish" if index % 2 else "Bearish",
                "score": score,
                "score_bucket": score_bucket(score),
                "production_alert": score >= 90,
                "realized_return": 0.5 if won else -0.25,
                "exit_reason": "TARGET_1" if won else "STOP",
                "target_1_hit": won,
                "target_2_hit": False,
                "stop_first": not won,
                "invalidated_quickly": not won,
                "hold_minutes": 20,
                "mfe": 0.6 if won else 0.1,
                "mae": -0.1 if won else -0.3,
            }
        )
    return pd.DataFrame(rows)


def test_signal_funnel_stage_ordering_and_deterministic_reasons():
    first, result = funnel_for_bar(_frame(), 25, "SPY", production_threshold=0)
    second, _ = funnel_for_bar(_frame(), 25, "SPY", production_threshold=0)
    assert [row["stage"] for row in first] == list(FUNNEL_STAGES)
    assert first == second
    assert result["confidence"] >= 0


def test_lifecycle_stage_separates_threshold_crossing_from_final_alert():
    stages, result = funnel_for_bar(
        _frame(), 25, "SPY", production_threshold=0, lifecycle_eligible=False
    )
    by_stage = {row["stage"]: row for row in stages}
    assert result["confidence"] >= 0
    assert by_stage["SCORE THRESHOLD PASSED"]["passed"] is True
    assert by_stage["LIFECYCLE ELIGIBLE"]["passed"] is False
    assert "FINAL ALERT" not in by_stage


def test_all_score_buckets():
    probes = (0, 49.99, 50, 59.99, 60, 69, 70, 79, 80, 84, 85, 89, 90, 94, 95, 100)
    labels = {score_bucket(value) for value in probes}
    assert labels == {label for label, _, _ in SCORE_BUCKETS}


def test_threshold_comparisons_are_complete_and_ordered():
    reports = threshold_analysis(_candidate_rows())
    assert [row["threshold"] for row in reports] == list(THRESHOLDS)
    retained = [row["retained_candidates"] for row in reports]
    assert retained == sorted(retained, reverse=True)


def test_walk_forward_uses_chronological_folds():
    folds = walk_forward_thresholds(_candidate_rows())
    assert len(folds) == 2
    assert folds[0]["train_end"] < folds[0]["validation_end"]


def test_production_threshold_is_not_modified():
    assert DEFAULT_CALL_SCORE_THRESHOLD == 90
    assert DEFAULT_PUT_SCORE_THRESHOLD == 90


def test_scoring_component_capture():
    record = shadow_funnel_record(
        {
            "symbol": "SPY",
            "timestamp": "2026-07-27T10:00:00-04:00",
            "signal": "WATCHLIST",
            "bias": "Bullish",
            "confidence": 82,
            **{component: index for index, component in enumerate(COMPONENTS)},
        }
    )
    assert set(record["component_scores"]) == set(COMPONENTS)
    assert record["research_thresholds"]["80"] is True
    assert record["research_thresholds"]["85"] is False


def test_timestamp_normalization():
    naive = normalize_timestamp("2026-07-27 10:00")
    utc = normalize_timestamp("2026-07-27T14:00:00Z")
    assert str(naive.tz) == "America/New_York"
    assert naive == utc


def test_duplicate_bar_handling_and_missing_bar_detection():
    raw = _frame(3)[["Open", "High", "Low", "Close", "Volume"]]
    duplicated = pd.concat([raw, raw.iloc[[1]]]).sort_index(kind="stable")
    normalized = normalize_market_data(duplicated, "SPY")
    real = normalized[~normalized["missing_bar"]]
    assert real["timestamp"].is_unique
    assert len(real) == 3
    assert real["duplicate_bar"].sum() == 1
    assert normalized["missing_bar"].sum() == 75


def test_dataset_hash_is_deterministic_and_sensitive():
    normalized = normalize_market_data(
        _frame(3)[["Open", "High", "Low", "Close", "Volume"]], "SPY"
    )
    assert dataset_hash(normalized) == dataset_hash(normalized.sample(frac=1))
    changed = normalized.copy()
    changed.loc[0, "close"] = 999
    assert dataset_hash(normalized) != dataset_hash(changed)


def test_point_in_time_funnel_has_no_future_bar_leakage():
    original = _frame()
    first, _ = funnel_for_bar(original, 25, "SPY")
    changed = original.copy()
    changed.iloc[26:, changed.columns.get_loc("Close")] = 9999
    second, _ = funnel_for_bar(changed, 25, "SPY")
    assert first == second


def test_barrier_ordering_is_conservative_for_same_bar():
    frame = _frame(3)
    frame.iloc[1, frame.columns.get_loc("High")] = 101
    frame.iloc[1, frame.columns.get_loc("Low")] = 99
    result, bars = barrier_outcome(frame, 0, "Bullish", 100, 0.25, 0.25)
    assert result == "ADVERSE"
    assert bars == 1


def test_bullish_and_bearish_mfe_mae_directionality():
    from signal_funnel_experiment import _forward_metrics

    frame = _frame(4)
    bullish = _forward_metrics(frame, 0, "Bullish", frame.iloc[0]["Close"])
    bearish = _forward_metrics(frame, 0, "Bearish", frame.iloc[0]["Close"])
    assert bullish["mfe_15m"] > 0
    assert bullish["mae_15m"] <= 0
    assert bearish["mfe_15m"] >= 0
    assert bearish["mae_15m"] < 0


def test_shadow_isolation_duplicate_prevention_and_no_production_writes(tmp_path):
    source = {
        "symbol": "SPY",
        "timestamp": "2026-07-27T10:00:00-04:00",
        "signal": "WATCHLIST",
        "bias": "Bullish",
        "confidence": 82,
    }
    original = deepcopy(source)
    target = tmp_path / "funnel.jsonl"
    returned = record_live_shadow(source, target)
    assert returned is source
    assert source == original
    record = shadow_funnel_record(source)
    assert not append_shadow_funnel(record, target)
    assert len(target.read_text().splitlines()) == 1
    assert not (tmp_path / "signal_history.jsonl").exists()
    assert not (tmp_path / "paper_option_positions.json").exists()


def test_bounded_shadow_log_behavior(tmp_path):
    target = tmp_path / "funnel.jsonl"
    for index in range(20):
        record = shadow_funnel_record(
            {
                "symbol": "SPY",
                "timestamp": f"2026-07-27T10:{index:02d}:00-04:00",
                "signal": "WATCHLIST",
                "bias": "Bullish",
                "confidence": 70 + index,
            }
        )
        append_shadow_funnel(record, target, maximum_bytes=4000)
    assert target.stat().st_size <= 4000
    lines = target.read_text().splitlines()
    assert lines
    assert all(json.loads(line)["experiment_id"].startswith("EXP-003") for line in lines)


def test_provider_audit_does_not_expose_credentials():
    audit = provider_audit(
        yfinance_configured=True,
        finnhub_configured=True,
        tradier_configured=True,
    )
    encoded = json.dumps(audit)
    assert "token" not in encoded.lower()
    assert all(isinstance(row["credentials_configured"], bool) for row in audit)
