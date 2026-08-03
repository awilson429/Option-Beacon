from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from confidence_calibration import predict_shadow_probability, time_based_split, train_shadow_calibrator
from exit_coach_intelligence import assess_exit_conditions
from intelligence_analytics import analyze_intelligence_records
from intelligence_capture import eastern_session_segment, outcome_label, setup_feature_snapshot
from market_regime import classify_market_regime
from opportunity_ranking_v2 import rank_opportunities_v2
from sector_context import build_sector_context, rank_sector_returns, sector_for_symbol
from signal_history import create_trade_record, update_trade_outcome
from trade_repository import TradeRepository
from trade_state_service import process_scanner_result


UTC = timezone.utc


def _candidate(timestamp=None):
    at = timestamp or datetime(2026, 7, 30, 14, 0, tzinfo=UTC)
    record = create_trade_record(symbol="NVDA", direction="Bullish", setup="Breakout", confidence=90,
        entry=100, stop=99, target_1=102, target_2=104, target_3=106, timestamp=at)
    record.entry_time = None
    return record


def _result(timestamp=None):
    at = timestamp or datetime(2026, 7, 30, 14, 0, tzinfo=UTC)
    return {"symbol": "NVDA", "bias": "Bullish", "confidence": 90, "price": 100,
        "timestamp": at, "rsi": 61, "relative_volume": 1.8, "spy_direction": "BULLISH",
        "qqq_direction": "BULLISH", "normalized_volatility": 1.0,
        "trade_plan": {"direction": "Bullish", "setup_type": "Breakout", "trigger_price": 100,
                       "technical_stop": 99, "target_1": 102, "target_2": 104, "target_3": 106}}


def test_session_buckets_are_eastern_and_point_in_time():
    assert eastern_session_segment(datetime(2026, 7, 30, 13, 0, tzinfo=UTC)) == "PREMARKET"
    assert eastern_session_segment(datetime(2026, 7, 30, 13, 45, tzinfo=UTC)) == "OPENING_DRIVE"
    assert eastern_session_segment(datetime(2026, 7, 30, 16, 0, tzinfo=UTC)) == "MIDDAY"


@pytest.mark.parametrize(("features", "expected"), [
    ({"spy_direction":"UP","qqq_direction":"UP","normalized_volatility":1,"directional_efficiency":.7}, "BULLISH_TREND"),
    ({"spy_direction":"DOWN","qqq_direction":"DOWN","normalized_volatility":1,"directional_efficiency":.7}, "BEARISH_TREND"),
    ({"spy_direction":"UP","qqq_direction":"DOWN","normalized_volatility":1}, "RANGE_BOUND_CHOPPY"),
    ({"spy_direction":"UP","qqq_direction":"UP","normalized_volatility":2,"directional_efficiency":.7}, "HIGH_VOLATILITY_TREND"),
    ({"spy_direction":"UP","qqq_direction":"DOWN","normalized_volatility":2}, "HIGH_VOLATILITY_CHOP"),
    ({"spy_direction":"UP","qqq_direction":"DOWN","normalized_volatility":.3}, "LOW_VOLATILITY_COMPRESSION"),
    ({}, "INSUFFICIENT_DATA"),
])
def test_regime_classification(features, expected):
    assert classify_market_regime(features).regime == expected


def test_sector_mapping_ranking_alignment_and_missing_data():
    assert sector_for_symbol("NVDA") == ("Technology", "XLK")
    assert rank_sector_returns({"XLK": .01, "XLE": .02}) == {"XLE": 1, "XLK": 2}
    aligned = build_sector_context("NVDA", "Bullish", symbol_return=.03, sector_return=.01)
    assert aligned.alignment_status == "OUTPERFORMING"
    assert build_sector_context("UNKNOWN", "Bullish").alignment_status == "UNKNOWN"


def test_snapshot_is_point_in_time_and_repository_is_immutable(tmp_path):
    repository = TradeRepository(tmp_path / "state.db")
    assert repository.backend == "sqlite"
    assert repository.db_file == str(tmp_path / "state.db")
    result, record = _result(), _candidate()
    repository.create_opportunity(opportunity_id=record.trade_id, idempotency_key=record.trade_id,
        symbol=record.symbol, direction=record.direction, playbook=record.setup,
        signal_timestamp=record.timestamp, source_version="test")
    snapshot = setup_feature_snapshot(result, record)
    repository.create_intelligence_snapshot(record.trade_id, snapshot.to_dict())
    changed = snapshot.to_dict(); changed["features"]["rsi"] = 99
    repository.create_intelligence_snapshot(record.trade_id, changed)
    stored = repository.get_intelligence_snapshot(record.trade_id)["snapshot"]
    assert stored["features"]["rsi"] == 61
    assert stored["features"]["confirmation_level"] == 100
    assert stored["generated_timestamp"] == result["timestamp"].isoformat()


def test_scanner_hook_persists_snapshot_and_evolving_outcome(tmp_path):
    repository = TradeRepository(tmp_path / "state.db", database_url="")
    assert process_scanner_result(repository, _result(), source_version="test") == 1
    snapshots = repository.list_intelligence_snapshots()
    outcomes = repository.list_intelligence_outcomes()
    assert len(snapshots) == len(outcomes) == 1
    assert snapshots[0]["snapshot"]["data_quality"]["scanner_version"] == "test"
    assert outcomes[0]["outcome"]["entered"] is False
    reloaded = TradeRepository(tmp_path / "state.db")
    assert len(reloaded.list_intelligence_snapshots()) == 1


def test_outcome_label_distinguishes_result_and_missing_measurements():
    record = _candidate(); record.entry_time = record.timestamp; record.exit_time = record.timestamp + timedelta(minutes=5)
    record.exit_reason = "STOP"; record.realized_return = -1; record.max_favorable_excursion = .2; record.max_adverse_excursion = -1
    label = outcome_label(record)
    assert label.result_class == "LOSER" and label.favorable_before_failure is True
    assert "time_to_mfe_minutes" in label.missing_fields


def test_analytics_expectancy_profit_factor_threshold_and_exclusions():
    snapshots = [{"opportunity_id": str(i), "setup_type": "Breakout"} for i in range(4)]
    outcomes = [
        {"opportunity_id":"0","exit_timestamp":"t","realized_return":2,"never_entered":False},
        {"opportunity_id":"1","exit_timestamp":"t","realized_return":-1,"never_entered":False},
        {"opportunity_id":"2","exit_timestamp":"t","realized_return":99,"never_entered":True},
        {"opportunity_id":"3","exit_timestamp":None,"realized_return":None,"never_entered":False},
    ]
    report = analyze_intelligence_records(snapshots, outcomes, minimum_sample_size=3)
    row = report["groups"][0]
    assert row["expectancy"] == .5 and row["profit_factor"] == 2
    assert row["sufficient_sample"] is False
    assert report["exclusions"]["incomplete_or_ineligible_outcome"] == 2


def test_time_split_is_chronological_and_shadow_fallback_is_safe():
    rows = [{"exit_timestamp": f"2026-01-{day:02d}", "rule_score": 80, "realized_return": 1} for day in range(1, 6)]
    train, validation = time_based_split(list(reversed(rows)), validation_fraction=.4)
    assert train[-1]["exit_timestamp"] < validation[0]["exit_timestamp"]
    model = train_shadow_calibrator(rows, minimum_samples=10)
    prediction = predict_shadow_probability(model, 80)
    assert model["shadow_only"] and prediction["probability"] is None
    assert model["promotion_status"] if "promotion_status" in model else True


def test_shadow_model_version_persists_and_cannot_auto_promote():
    rows = [{"exit_timestamp": f"2026-01-{(i%28)+1:02d}T{i:02d}", "rule_score": 70+i%20, "realized_return": 1 if i%2 else -1} for i in range(70)]
    model = train_shadow_calibrator(rows, minimum_samples=20)
    assert model["available"] and model["shadow_only"]
    assert model["model_version"] == "empirical-shrinkage-v1"
    assert model["promotion_status"] == "SHADOW_REQUIRES_HUMAN_APPROVAL"


def test_ranking_flag_disabled_ties_and_reasons():
    items = [{"opportunity_id":"b","rule_score":80,"regime_alignment":"ALIGNED"},
             {"opportunity_id":"a","rule_score":80,"regime_alignment":"ALIGNED"}]
    assert rank_opportunities_v2(items, enabled=False)["results"] == []
    ranked = rank_opportunities_v2(items, enabled=True)["results"]
    assert [row["opportunity_id"] for row in ranked] == ["a", "b"]
    assert ranked[0]["top_strengths"]


def test_exit_coach_is_advisory_with_reason_codes():
    result = assess_exit_conditions({"momentum_strengthening": True, "volume_expanding": True})
    assert result["state"] == "HOLD - MOMENTUM STRONG"
    assert result["reason_codes"] and result["authoritative_lifecycle_unchanged"]


def test_authoritative_stop_behavior_is_unchanged():
    record = _candidate(); record.entry_time = record.timestamp
    update_trade_outcome(record, 99, record.timestamp + timedelta(minutes=1))
    assert record.exit_reason == "STOP"


def test_shadow_event_model_version_persists(tmp_path):
    repository = TradeRepository(tmp_path / "state.db")
    identifier = repository.record_intelligence_shadow_event("CALIBRATION", {"shadow_only": True}, model_version="v1")
    with repository.connection() as connection:
        row = repository._fetchone(connection, "SELECT * FROM intelligence_shadow_events WHERE id=?", (identifier,))
    assert row["model_version"] == "v1"


def test_intelligence_failure_cannot_interrupt_scanner(tmp_path, monkeypatch):
    repository = TradeRepository(tmp_path / "state.db")
    monkeypatch.setattr(repository, "create_intelligence_snapshot", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("shadow store unavailable")))
    assert process_scanner_result(repository, _result(), source_version="test") == 1
    assert len(repository.list_opportunities()) == 1
