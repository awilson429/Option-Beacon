import inspect
from datetime import datetime, timedelta, timezone

import pytest

import app
from mirror_execution import MirrorExecutionRepository
from option_translation_autopsy import (
    analyze_option_translation, chronological_split, dte_bucket,
    moneyness_bucket, simulate_exit, spread_bucket, timing_snapshots,
    underlying_magnitude_bucket,
)
from option_translation_autopsy_dashboard import render_option_translation_autopsy


NOW = datetime(2026, 8, 10, 14, tzinfo=timezone.utc)


def fixture(count=24):
    snapshots, outcomes, mirrors, marks = [], [], [], []
    for index in range(count):
        identity, trade = f"auth-{index}", f"mirror-{index}"
        at = NOW + timedelta(minutes=index * 60)
        auth_return = .05 if index % 4 == 0 else .4 if index % 2 == 0 else -.3
        mirror_return = -10 if index % 3 == 0 else 15
        snapshots.append({"snapshot": {"opportunity_id": identity, "symbol": "SPY" if index < 10 else "QQQ",
            "direction": "Bullish", "setup_type": "BREAKOUT", "entry_timestamp": at.isoformat(),
            "features": {"relative_volume": 1.5, "rsi": 55, "distance_from_vwap": .1, "atr": 1.2},
            "scoring": {"confidence": 75, "quality": 80}, "market_regime": {"regime": "TREND"}}})
        outcomes.append({"outcome": {"opportunity_id": identity, "entered": True,
            "entry_timestamp": at.isoformat(), "exit_timestamp": (at + timedelta(minutes=10)).isoformat(),
            "entry_price": 100, "exit_price": 100.4, "realized_return": auth_return}})
        mirrors.append({"mirror_trade_id": trade, "opportunity_id": identity, "symbol": "SPY", "direction": "Bullish",
            "option_symbol": f"SPY-C-{index}", "option_type": "CALL", "strike": 100, "expiration": "2026-08-14",
            "dte": index % 11, "quantity": 1, "contract_multiplier": 100, "underlying_entry_price": 100,
            "entry_bid": .9, "entry_ask": 1.1, "entry_mid": 1, "entry_fill": 1.05,
            "spread_dollars": .2, "spread_percent": 20, "total_debit": 105,
            "entry_event_at": at, "opened_at": at, "status": "CLOSED", "disposition_code": "MIRROR_OPENED",
            "exit_quote_at": at + timedelta(minutes=10), "exit_bid": .8, "exit_ask": 1,
            "exit_mid": .9, "exit_fill": .85, "realized_pnl": mirror_return / 100 * 105,
            "realized_return_percent": mirror_return, "authoritative_exit_reason": "TARGET"})
        for minute, value in ((1, -5), (5, 20), (10, mirror_return)):
            marks.append({"mark_id": f"{trade}-{minute}", "mirror_trade_id": trade,
                "observed_at": at + timedelta(minutes=minute), "return_pct": value,
                "conservative_mark": 1.05 * (1 + value / 100), "unrealized_pnl": value / 100 * 105,
                "time_since_entry_seconds": minute * 60})
    return snapshots, outcomes, mirrors, marks


def report(count=24):
    return analyze_option_translation(*fixture(count))


def test_exact_identity_join_excludes_non_authoritative_and_never_fuzzy_matches():
    values = list(fixture(2)); values[2][0]["opportunity_id"] = "not-the-same-id"
    result = analyze_option_translation(*values)
    assert result["eligible"] == 1
    assert result["excluded"] == {"missing_exact_authoritative_record": 1}


def test_exact_authoritative_outcome_remains_eligible_without_feature_snapshot():
    snapshots, outcomes, mirrors, marks = fixture(1)
    result = analyze_option_translation([], outcomes, mirrors, marks)
    assert result["eligible"] == 1 and result["excluded"] == {}
    assert result["rows"][0]["confidence"] is None


def test_outcome_matrix_and_auth_win_mirror_loss_are_exact_and_exclusive():
    result = report()
    assert sum(row["n"] for row in result["outcome_matrix"]) == result["eligible"]
    assert len(result["auth_win_mirror_loss"]) == sum(
        row["auth_return"] > 0 and row["mirror_return"] < 0 for row in result["rows"])
    assert all(row["failure_mode"] for row in result["auth_win_mirror_loss"])


def test_mfe_mae_giveback_and_profitable_to_loser_come_from_marks():
    row = report()["rows"][0]
    assert row["mfe"] == 20 and row["mae"] == -10
    assert row["giveback"] == 30 and row["profitable_then_loser"] is True
    assert row["causal_confidence"] == "SUPPORTED"


def test_timing_uses_nearest_persisted_mark_with_tolerance_and_no_interpolation():
    marks = [{"mark_id": "near", "observed_at": NOW + timedelta(seconds=70), "return_pct": 7},
             {"mark_id": "far", "observed_at": NOW + timedelta(minutes=2, seconds=50), "return_pct": 9}]
    result = timing_snapshots(NOW, marks)
    assert result["return_1m"] == 7
    assert result["return_2m"] is None and result["return_3m"] == 9


def test_spread_fill_drag_bucket_magnitude_dte_and_moneyness_math():
    row = report()["rows"][0]
    assert row["entry_fill_drag"] == pytest.approx(5)
    assert row["exit_fill_drag"] == pytest.approx(5)
    assert row["round_trip_drag"] == pytest.approx(10)
    assert spread_bucket(2) == "<=2%" and spread_bucket(20.1) == ">20%"
    assert underlying_magnitude_bucket(.1) == "0% to 0.10%"
    assert dte_bucket(0) == "0DTE" and dte_bucket(7) == "5-9 DTE"
    assert moneyness_bucket("CALL", 100, 100.2) == "ATM / near ATM"


def test_capital_efficiency_and_predeclared_selective_what_if():
    result = report()
    assert result["capital"]["cumulative_gross_debit"] == 24 * 105
    assert result["capital"]["peak_capital"] >= 105
    assert {row["variant"] for row in result["selective_what_if"]} == {
        "EXCLUDE SPREAD >20%", "EXCLUDE UNDERLYING MOVE <=0.10%", "EXCLUDE 0DTE", "REQUIRE CONFIDENCE >=70"}


def test_exit_simulation_uses_deterministic_first_hit_persisted_mark():
    row = report()["rows"][0]
    result = simulate_exit(row, "TP15")
    assert result["return"] == 20
    assert result["observed_at"] == NOW + timedelta(minutes=5)


def test_chronological_split_and_minimum_validation_rules():
    rows = report()["rows"]
    development, validation = chronological_split(rows)
    assert len(development) == 16 and len(validation) == 8
    assert max(row["opened_at"] for row in development) < min(row["opened_at"] for row in validation)
    assert all(row["validation_label"] == "INSUFFICIENT DATA" for row in report(10)["exit_what_if"] if row["variant"] != "CONTROL")


def test_missing_marks_and_nonpersisted_greeks_remain_unavailable():
    snapshots, outcomes, mirrors, _ = fixture(1)
    result = analyze_option_translation(snapshots, outcomes, mirrors, [])
    assert result["rows"][0]["telemetry_coverage"] == "DATA UNAVAILABLE"
    assert result["rows"][0]["return_5m"] is None
    assert result["coverage"]["delta"] == result["coverage"]["iv"] == "NOT PERSISTED"


def test_dashboard_is_on_demand_read_only_and_has_no_provider_or_execution_calls():
    dashboard = inspect.getsource(render_option_translation_autopsy)
    analytics = inspect.getsource(analyze_option_translation)
    assert dashboard.index("Run Option Translation Autopsy") < dashboard.index("list_intelligence_snapshots")
    assert "analytics_marks" in dashboard and "observed_after=start_at" in dashboard
    for source in (dashboard, analytics):
        for forbidden in ("option_quote", "chain_provider", "run_mirror_execution", "record_disposition", "update_mark"):
            assert forbidden not in source
    assert "render_option_translation_autopsy" in inspect.getsource(app.render_strategy_lab)
    marks_source = inspect.getsource(MirrorExecutionRepository.analytics_marks)
    assert "SELECT *" not in marks_source
    assert marks_source.index("WHERE mirror_trade_id IN") < marks_source.index("LIMIT ?")
