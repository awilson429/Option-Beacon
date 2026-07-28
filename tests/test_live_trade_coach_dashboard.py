from datetime import datetime, timedelta, timezone

import pytest

from live_trade_coach_dashboard import (
    UNAVAILABLE,
    actionable_live_plan_coach_eligible,
    coach_display_model,
    format_coach_value,
    latest_symbol_price,
    live_plan_trade_outcome,
    matching_open_trade,
    open_trade_coach_eligible,
    open_trade_coach_output,
)
from signal_history import create_trade_record


NOW = datetime(2026, 7, 27, 15, 0, tzinfo=timezone.utc)


def outcome(*, status="OPEN", timestamp=NOW):
    record = create_trade_record(
        symbol="SPY",
        direction="Bullish",
        setup="Bullish breakout",
        confidence=85,
        entry=100,
        stop=95,
        target_1=103,
        target_2=106,
        target_3=109,
        timestamp=timestamp,
        entry_time=timestamp,
    )
    if status == "CANDIDATE":
        record.entry_time = None
    elif status == "CLOSED":
        record.exit_time = timestamp + timedelta(minutes=30)
        record.exit_reason = "TARGET_1"
    elif status == "NEVER_TRIGGERED":
        record.entry_time = None
        record.exit_time = timestamp + timedelta(minutes=60)
        record.exit_reason = "NEVER_TRIGGERED"
    return record


def live_result(**overrides):
    result = {
        "symbol": "SPY",
        "signal": "BULLISH SETUP",
        "bias": "Bullish",
        "confidence": 85,
        "price": 101,
        "timestamp": NOW.isoformat(),
        "setup_stage": "Armed",
        "entry_timing": "Watch closely",
        "trade_plan": {
            "setup_type": "Bullish breakout",
            "direction": "Bullish",
            "trigger_price": 100,
            "technical_stop": 95,
            "target_1": 103,
            "target_2": 106,
            "target_3": 109,
        },
    }
    result.update(overrides)
    return result


@pytest.mark.parametrize(
    ("status", "treatment"),
    [
        ("HOLD", "positive"),
        ("PROTECT PROFIT", "caution"),
        ("TAKE PARTIAL", "caution"),
        ("EXIT", "urgent"),
    ],
)
def test_recommendation_display_treatments(status, treatment):
    display = coach_display_model(
        {
            "status": status,
            "action": "Manage the trade.",
            "urgency": "LOW",
            "summary": "Summary",
            "reasons": ["Reason one", "Reason two"],
        }
    )

    assert display["status"] == status
    assert display["treatment"] == treatment
    assert display["action"] == "Manage the trade."


def test_unavailable_metric_formatting():
    assert format_coach_value(None) == UNAVAILABLE
    assert format_coach_value(float("nan")) == UNAVAILABLE
    assert format_coach_value(float("inf")) == UNAVAILABLE
    assert format_coach_value("missing") == UNAVAILABLE
    assert format_coach_value(12.5, percentage=True) == "12.50%"


def test_open_trade_eligibility():
    assert open_trade_coach_eligible(outcome(status="OPEN")) is True


def test_candidate_exclusion():
    candidate = outcome(status="CANDIDATE")

    assert open_trade_coach_eligible(candidate) is False
    assert open_trade_coach_output(candidate, 101, NOW) is None


def test_closed_trade_exclusion():
    closed = outcome(status="CLOSED")

    assert open_trade_coach_eligible(closed) is False
    assert open_trade_coach_output(closed, 101, NOW) is None


def test_never_triggered_exclusion():
    never_triggered = outcome(status="NEVER_TRIGGERED")

    assert open_trade_coach_eligible(never_triggered) is False
    assert open_trade_coach_output(never_triggered, 101, NOW) is None


def test_missing_current_price_returns_unavailable():
    result = open_trade_coach_output(outcome(), None, NOW)

    assert result["status"] == "UNAVAILABLE"
    assert latest_symbol_price({}, "SPY") is None


def test_actionable_live_plan_eligibility_and_ephemeral_outcome():
    result = live_result()

    assert actionable_live_plan_coach_eligible(result) is True
    record = live_plan_trade_outcome(
        result,
        [],
        current_price=101,
        current_timestamp=NOW,
    )
    assert record is not None
    assert record.entry_time == NOW


def test_live_plan_below_trigger_is_not_treated_as_entered():
    record = live_plan_trade_outcome(
        live_result(price=99),
        [],
        current_price=99,
        current_timestamp=NOW,
    )

    assert record is None


def test_invalid_live_plan_exclusion():
    assert actionable_live_plan_coach_eligible(
        live_result(entry_timing="Setup invalidated")
    ) is False


def test_extended_live_plan_exclusion():
    assert actionable_live_plan_coach_eligible(
        live_result(setup_stage="Extended", entry_timing="Do not chase")
    ) is False


def test_neutral_live_plan_exclusion():
    result = live_result(bias="Neutral")
    result["trade_plan"] = {
        "setup_type": "Directional setup",
        "direction": "Neutral",
        "trigger_price": 100,
    }

    assert actionable_live_plan_coach_eligible(result) is False


def test_newest_matching_open_trade_is_selected():
    older = outcome(timestamp=NOW - timedelta(minutes=5))
    newer = outcome(timestamp=NOW)

    assert matching_open_trade(live_result(), [older, newer]) is newer
