from datetime import datetime, timedelta, timezone

import pytest

from selectivity_analysis import (
    MODEL_VERSION,
    analyze_selectivity,
    assign_percentile_tiers,
    build_analysis_rows,
    chronological_split,
    classify_entry_exit,
    feature_bins,
    filter_trade_review,
    fit_quality_model,
    sample_confidence,
    score_quality,
    summarize_rows,
)


NOW = datetime(2026, 1, 2, 15, tzinfo=timezone.utc)


def dataset(count=40):
    snapshots, outcomes = [], []
    for index in range(count):
        opportunity_id = f"trade-{index:03d}"
        entered = NOW + timedelta(days=index)
        strong = index % 3 != 0
        snapshots.append({"snapshot": {
            "opportunity_id": opportunity_id, "symbol": "SPY" if index % 2 else "NVDA",
            "direction": "Bullish", "setup_type": "Breakout",
            "entry_timestamp": entered.isoformat(), "eastern_trading_date": entered.date().isoformat(),
            "session_segment": "MORNING" if index % 4 else "CLOSING_PERIOD",
            "features": {"relative_volume": 1.8 if strong else .8, "rsi": 58 if strong else 78,
                         "vwap_relationship": "ABOVE", "trend_alignment": "BULLISH"},
            "scoring": {"confidence": 95 if strong else 82},
            "market_regime": {"regime": "BULLISH_TREND"},
            "sector_context": {"sector": "Technology", "alignment_status": "OUTPERFORMING", "sector_rank": 1},
        }})
        realized = 1.0 if strong else -1.0
        outcomes.append({"outcome": {
            "opportunity_id": opportunity_id, "entered": True, "never_entered": False,
            "entry_timestamp": entered.isoformat(),
            "exit_timestamp": (entered + timedelta(minutes=10)).isoformat(),
            "entry_price": 100, "realized_return": realized,
            "maximum_favorable_excursion": 1.2 if strong else .1,
            "maximum_adverse_excursion": -.2 if strong else -.8,
            "duration_minutes": 10, "exit_reason": "TARGET_1" if strong else "STOP",
            "target_1_reached": strong, "stop_reached": not strong,
            "end_of_day_exit": False, "maximum_hold_exit": False,
            "time_to_mfe_minutes": None, "time_to_mae_minutes": None,
        }})
    return snapshots, outcomes


def test_immutable_entry_features_and_missing_data_are_used_without_estimation():
    snapshots, outcomes = dataset(2)
    snapshots[0]["snapshot"]["features"]["atr"] = None
    rows, exclusions = build_analysis_rows(snapshots, outcomes)
    assert rows[0]["atr"] is None
    assert rows[0]["time_to_mfe_minutes"] is None
    assert "selectivity_score" not in rows[0]
    outcomes.append({"outcome": {"opportunity_id": "missing", "entered": True,
                                  "exit_timestamp": NOW.isoformat(), "realized_return": 1}})
    _, exclusions = build_analysis_rows(snapshots, outcomes)
    assert exclusions["missing_entry_snapshot"] == 1


def test_winner_mfe_mae_and_exit_metrics_are_exact():
    snapshots, outcomes = dataset(6)
    rows, _ = build_analysis_rows(snapshots, outcomes)
    summary = summarize_rows(rows)
    assert summary["trade_count"] == 6
    assert summary["wins"] == 4 and summary["losses"] == 2
    assert summary["win_rate"] == pytest.approx(66.6667)
    assert summary["average_return"] == pytest.approx(1 / 3)
    assert summary["target_exit_rate"] == pytest.approx(66.6667)
    assert summary["stop_out_rate"] == pytest.approx(100 / 3)


@pytest.mark.parametrize(("row", "expected"), [
    ({"mfe": 1, "mae": -.2, "realized_return": .5}, "GOOD TRADE"),
    ({"mfe": 1, "mae": -.2, "realized_return": -.1}, "GOOD ENTRY / BAD EXIT"),
    ({"mfe": .1, "mae": -.8, "realized_return": -.5}, "BAD ENTRY"),
    ({"mfe": .2, "mae": -.2, "realized_return": 0}, "CHOP / INCONCLUSIVE"),
    ({"mfe": None, "mae": -.2, "realized_return": 0}, "INSUFFICIENT DATA"),
])
def test_entry_exit_classification(row, expected):
    assert classify_entry_exit(row) == expected


def test_quality_score_is_reproducible_explainable_and_has_no_validation_leakage():
    snapshots, outcomes = dataset(40)
    rows, _ = build_analysis_rows(snapshots, outcomes)
    train, validation = chronological_split(rows)
    model = fit_quality_model(train)
    before = score_quality(validation[0], model)
    changed = {**validation[0], "realized_return": -999, "mfe": 999}
    after = score_quality(changed, model)
    assert before == after
    assert before["model_version"] == MODEL_VERSION
    assert before["calibrated_probability"] is None and before["shadow_only"]
    assert before["positive_factors"] or before["negative_factors"]


def test_tiers_percentiles_reduction_and_temporal_validation():
    snapshots, outcomes = dataset(40)
    report = analyze_selectivity(snapshots, outcomes)
    assert report["training_count"] == 28 and report["validation_count"] == 12
    assert report["methodology"] == "CHRONOLOGICAL SHADOW DESCRIPTIVE"
    assert report["tiers"][0]["tier"] == "BASELINE"
    elite = next(row for row in report["tiers"] if row["tier"].startswith("ELITE"))
    assert 0 < elite["trade_count"] < report["validation_count"]
    assert elite["trade_reduction"] > 0
    ordered = sorted(report["rows"], key=lambda row: row["exit_timestamp"])
    assert ordered[27]["exit_timestamp"] < ordered[28]["exit_timestamp"]


def test_feature_bins_thresholds_filters_and_sample_governance():
    snapshots, outcomes = dataset(25)
    report = analyze_selectivity(snapshots, outcomes)
    bins = feature_bins(report["rows"], "rule_score", (0, 85, 90, 101))
    assert sum(row["trade_count"] for row in bins) == 25
    assert all("reliable" in row for row in bins)
    winners = filter_trade_review(report["rows"], result="WINNER", symbol="SPY")
    assert winners and all(row["winner"] and row["symbol"] == "SPY" for row in winners)
    assert sample_confidence(19) == "EXPLORATORY ONLY"
    assert sample_confidence(20) == "DESCRIPTIVE"
    assert sample_confidence(50) == "PRELIMINARY"
    assert sample_confidence(100) == "STRONGER EVIDENCE"


def test_analysis_module_cannot_import_or_change_production_gates_or_ranking():
    from pathlib import Path
    source = Path("selectivity_analysis.py").read_text(encoding="utf-8")
    for forbidden in (
        "process_scanner_result", "evaluate_execution", "scanner_entry_eligibility",
        "rank_opportunities", "capture_qualified_signal", "update_position",
    ):
        assert forbidden not in source
