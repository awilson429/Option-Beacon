import json

import pandas as pd
import pytest

from generate_optimization_baseline import generate_reports
from optimization_analysis import (
    REGIME_BULLISH_TREND,
    baseline_report,
    classify_market_regime,
    failure_mode_audit,
    performance_metrics,
    replay_fixed_plan,
)
from trade_replay import add_replay_indicators


def _bars(periods=240, *, trend=0.04, frequency="5min"):
    index = pd.date_range("2026-05-01 09:45", periods=periods, freq=frequency)
    prices = [100 + trend * position for position in range(periods)]
    return pd.DataFrame(
        {
            "Open": [price - 0.02 for price in prices],
            "High": [price + 0.10 for price in prices],
            "Low": [price - 0.10 for price in prices],
            "Close": prices,
            "Volume": [1000 + position * 3 for position in range(periods)],
        },
        index=index,
    )


def _trade_rows():
    return pd.DataFrame(
        [
            {
                "symbol": "SPY",
                "direction": "Bullish",
                "setup": "BULLISH SETUP",
                "hour": "10:00",
                "confidence_bucket": "90-94",
                "regime": "bullish trend",
                "period": "60-trading-days",
                "timeframe": "5m",
                "higher_timeframe_alignment": "aligned",
                "signal_time": "2026-05-01T10:00:00",
                "realized_return": 1.0,
                "hold_minutes": 20,
                "mfe": 1.5,
                "mae": -0.2,
                "target_1_hit": True,
                "target_2_hit": False,
                "stop_first": False,
                "exit_reason": "TARGET_1",
                "late": False,
                "invalidated_quickly": False,
                "formation_delay_minutes": 5,
                "failure_modes": [],
            },
            {
                "symbol": "QQQ",
                "direction": "Bearish",
                "setup": "BEARISH SETUP",
                "hour": "14:00",
                "confidence_bucket": "95-100",
                "regime": "range-bound",
                "period": "60-trading-days",
                "timeframe": "5m",
                "higher_timeframe_alignment": "non-aligned",
                "signal_time": "2026-05-02T14:00:00",
                "realized_return": -0.5,
                "hold_minutes": 15,
                "mfe": 0.1,
                "mae": -0.7,
                "target_1_hit": False,
                "target_2_hit": False,
                "stop_first": True,
                "exit_reason": "STOP",
                "late": True,
                "invalidated_quickly": True,
                "formation_delay_minutes": 20,
                "failure_modes": [
                    "alert arrived late",
                    "market regime mismatch",
                ],
            },
        ]
    )


def test_regime_classifier_uses_trailing_data_only():
    frame = add_replay_indicators(_bars())
    index = 80
    before = classify_market_regime(frame, index)
    altered = frame.copy()
    altered.iloc[index + 1 :, altered.columns.get_loc("Close")] = 1

    assert classify_market_regime(altered, index) == before


def test_regime_classifier_finds_objective_bullish_trend():
    frame = add_replay_indicators(_bars(periods=400, trend=0.08))

    result = classify_market_regime(frame, len(frame) - 1)

    assert result["regime"] == REGIME_BULLISH_TREND
    assert result["bullish_alignment"] is True


def test_replay_fixed_plan_is_direction_aware_and_conservative():
    frame = _bars(periods=4, trend=0)
    frame.iloc[1, frame.columns.get_loc("Low")] = 99.7
    frame.iloc[1, frame.columns.get_loc("High")] = 100.8

    bullish = replay_fixed_plan(
        frame,
        0,
        entry=100,
        direction="Bullish",
        max_hold_candles=3,
    )

    assert bullish.exit_reason == "STOP"
    assert bullish.exit_price == pytest.approx(99.75)
    assert bullish.mae_percent == pytest.approx(-0.3)


def test_comprehensive_metrics_include_drawdown_and_timeliness():
    metrics = performance_metrics(_trade_rows(), trading_days=2)

    assert metrics["total_alerts"] == 2
    assert metrics["alerts_per_day"] == 1
    assert metrics["win_rate"] == 50
    assert metrics["expectancy"] == 0.25
    assert metrics["profit_factor"] == 2
    assert metrics["maximum_drawdown"] == -0.5
    assert metrics["longest_losing_streak"] == 1
    assert metrics["target_1_rate"] == 50
    assert metrics["stop_first_rate"] == 50
    assert metrics["late_rate"] == 50


def test_failure_audit_counts_frequency_and_performance():
    audit = failure_mode_audit(_trade_rows())
    indexed = {row["failure_mode"]: row for row in audit}

    assert indexed["alert arrived late"]["frequency"] == 1
    assert indexed["alert arrived late"]["average_return"] == -0.5
    assert indexed["market regime mismatch"]["symbols"] == {"QQQ": 1}


def test_baseline_groups_symbol_direction_setup_hour_and_regime():
    report = baseline_report(_trade_rows(), [])

    assert {row["group"] for row in report["by_symbol"]} == {"SPY", "QQQ"}
    assert {row["group"] for row in report["by_direction"]} == {
        "Bullish",
        "Bearish",
    }
    assert len(report["by_setup"]) == 2
    assert len(report["by_hour"]) == 2
    assert len(report["by_regime"]) == 2


def test_report_generator_is_versioned_and_registry_is_append_only(tmp_path):
    def fetcher(_symbol, _period, _interval):
        return _bars(periods=260)

    first_paths, first_report = generate_reports(
        tmp_path,
        fetcher=fetcher,
        generated_at=pd.Timestamp("2026-07-29T12:00:00Z"),
    )
    second_paths, _ = generate_reports(
        tmp_path,
        fetcher=fetcher,
        generated_at=pd.Timestamp("2026-07-29T12:00:00Z"),
    )

    assert first_report["data_manifest"]
    assert first_paths["baseline"].exists()
    assert first_paths["failure_modes"].exists()
    assert first_paths["regimes"].exists()
    assert first_paths["summary"].exists()
    registry_lines = second_paths["registry"].read_text(encoding="utf-8").splitlines()
    assert len(registry_lines) == 1
    assert json.loads(registry_lines[0])["experiment_id"] == "baseline-2026-07-29"


def test_report_generator_records_unavailable_periods_without_crashing(tmp_path):
    def unavailable(*_args):
        raise RuntimeError("offline")

    paths, report = generate_reports(
        tmp_path,
        fetcher=unavailable,
        generated_at=pd.Timestamp("2026-07-29T12:00:00Z"),
    )

    assert report["trade_count"] == 0
    assert all(item["status"] == "unavailable" for item in report["data_manifest"])
    assert paths["baseline"].exists()
