from datetime import datetime, timezone

import pytest

from signal_history import create_trade_record
from ui_polish import (
    UNAVAILABLE,
    decision_state_label,
    format_ui_value,
    open_trade_summary,
    opportunity_summary,
    scanner_summary,
    status_emphasis,
)


NOW = datetime(2026, 7, 27, 15, 0, tzinfo=timezone.utc)


def live_result(**overrides):
    result = {
        "symbol": "SPY",
        "bias": "Bullish",
        "confidence": 88,
        "price": 101.25,
        "entry_timing": "Trigger confirmed",
        "setup_stage": "Triggered",
        "trade_plan": {
            "setup_type": "Bullish breakout",
            "direction": "Bullish",
            "trigger_price": 100,
            "technical_stop": 97,
            "target_1": 104,
        },
    }
    result.update(overrides)
    return result


def coach(status="HOLD"):
    return {
        "status": status,
        "action": "Hold while respecting the planned stop and targets.",
        "urgency": "LOW",
        "current_return": 1.25,
        "risk_remaining": 141.67,
        "progress_to_target_1": 31.25,
        "progress_to_target_2": None,
        "progress_to_target_3": None,
        "target_1_reached": False,
        "target_2_reached": False,
        "target_3_reached": False,
        "stop_threatened": False,
        "historical_grade": "POSITIVE",
        "summary": "The trade remains within its plan.",
        "reasons": ["The stop is not threatened.", "Target 1 is not reached."],
    }


@pytest.mark.parametrize(
    ("status", "emphasis"),
    [
        ("BUY", "positive"),
        ("ENTERABLE", "positive"),
        ("HOLD", "positive"),
        ("PROTECT PROFIT", "caution"),
        ("TAKE PARTIAL", "caution"),
        ("EXTENDED", "caution"),
        ("EXIT", "urgent"),
        ("INVALID", "urgent"),
        ("WAIT", "muted"),
        ("INSUFFICIENT DATA", "muted"),
    ],
)
def test_status_emphasis_mapping(status, emphasis):
    assert status_emphasis(status) == emphasis


def test_unavailable_value_formatting():
    assert format_ui_value(None) == UNAVAILABLE
    assert format_ui_value(float("nan")) == UNAVAILABLE
    assert format_ui_value(float("inf")) == UNAVAILABLE
    assert format_ui_value("missing") == UNAVAILABLE
    assert format_ui_value(101.25, price=True) == "$101.25"


def test_actionable_opportunity_summary_fields():
    summary = opportunity_summary(
        live_result(),
        {
            "display_grade": "POSITIVE",
            "sample_size": 24,
            "win_rate": 62.5,
        },
        coach(),
    )

    assert summary == {
        "symbol": "SPY",
        "direction": "Bullish",
        "current_price": "$101.25",
        "setup": "Bullish breakout",
        "confidence": "88%",
        "timing": "Trigger confirmed",
        "entry": "$100.00",
        "stop": "$97.00",
        "target_1": "$104.00",
        "historical_grade": "POSITIVE",
        "historical_sample_size": "24",
        "historical_win_rate": "62.50%",
        "coach_status": "HOLD",
        "coach_action": "Hold while respecting the planned stop and targets.",
        "decision_state": "HOLD",
        "treatment": "positive",
    }


def test_scanner_summary_contains_required_fields():
    summary = scanner_summary(
        live_result(),
        {"display_grade": "POSITIVE"},
        coach(),
    )

    assert set(summary) == {
        "symbol",
        "direction",
        "setup",
        "confidence",
        "timing",
        "historical_grade",
        "coach_status",
        "coach_action",
        "entry",
        "stop",
        "target_1",
        "decision_state",
        "treatment",
    }


def test_open_trade_summary_fields():
    record = create_trade_record(
        symbol="SPY",
        direction="Bullish",
        setup="Bullish breakout",
        confidence=88,
        entry=100,
        stop=97,
        target_1=104,
        target_2=108,
        timestamp=NOW,
        entry_time=NOW,
    )

    summary = open_trade_summary(record, coach())

    assert summary["symbol"] == "SPY"
    assert summary["direction"] == "Bullish"
    assert summary["current_return"] == "1.25%"
    assert summary["coach_status"] == "HOLD"
    assert summary["risk_remaining"] == "141.67%"
    assert summary["target_progress"] == "31.25%"
    assert summary["historical_grade"] == "POSITIVE"


def test_invalid_state_label():
    assert (
        decision_state_label(live_result(entry_timing="Setup invalidated"))
        == "INVALID"
    )


def test_extended_state_label():
    assert (
        decision_state_label(
            live_result(setup_stage="Extended", entry_timing="Do not chase")
        )
        == "EXTENDED"
    )


def test_enterable_state_label_without_open_coach():
    assert decision_state_label(live_result(), None) == "ENTERABLE"
