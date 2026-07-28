from datetime import datetime, timezone

import pytest

from live_trade_coach import coach_trade_outcome
from signal_history import TradeOutcome


NOW = datetime(2026, 7, 27, 15, 0, tzinfo=timezone.utc)


def outcome(**overrides):
    values = {
        "trade_id": "trade-1",
        "timestamp": NOW,
        "symbol": "SPY",
        "direction": "Bullish",
        "setup": "Breakout",
        "confidence": 84,
        "entry": 100.0,
        "stop": 95.0,
        "target_1": 110.0,
        "target_2": 120.0,
        "target_3": 130.0,
        "entry_time": NOW,
        "exit_time": None,
        "exit_reason": None,
        "max_favorable_excursion": None,
        "max_adverse_excursion": None,
        "realized_return": None,
        "hold_minutes": None,
    }
    values.update(overrides)
    return TradeOutcome(**values)


def coach(record=None, price=102.0, history=None):
    return coach_trade_outcome(record or outcome(), price, NOW, history)


def test_bullish_hold():
    result = coach(price=102)

    assert result["status"] == "HOLD"
    assert result["current_return"] == pytest.approx(2)
    assert result["urgency"] == "LOW"


def test_bearish_hold():
    record = outcome(
        direction="Bearish",
        stop=105,
        target_1=90,
        target_2=80,
        target_3=70,
    )

    result = coach(record, 98)

    assert result["status"] == "HOLD"
    assert result["current_return"] == pytest.approx(2)


@pytest.mark.parametrize(
    ("record", "price"),
    [
        (outcome(), 95),
        (
            outcome(
                direction="Bearish",
                stop=105,
                target_1=90,
                target_2=80,
                target_3=70,
            ),
            105,
        ),
    ],
)
def test_stop_breach_returns_exit(record, price):
    result = coach(record, price)

    assert result["status"] == "EXIT"
    assert result["urgency"] == "HIGH"
    assert result["stop_threatened"] is True
    assert "stop" in result["summary"].lower()


def test_target_1_reached_and_take_partial():
    result = coach(price=110, history={"historical_grade": "POSITIVE"})

    assert result["target_1_reached"] is True
    assert result["target_2_reached"] is False
    assert result["status"] == "TAKE PARTIAL"
    assert "remainder" in result["action"].lower()


def test_target_2_reached_and_take_partial():
    result = coach(price=120, history={"historical_grade": "STRONG"})

    assert result["target_1_reached"] is True
    assert result["target_2_reached"] is True
    assert result["status"] == "TAKE PARTIAL"


def test_protect_profit_when_target_is_near():
    result = coach(price=108)

    assert result["status"] == "PROTECT PROFIT"
    assert "breakeven" in result["action"].lower()


def test_weak_history_produces_defensive_wording():
    result = coach(price=99, history={"historical_grade": "WEAK"})

    assert result["status"] == "EXIT"
    assert any("defensively" in reason for reason in result["reasons"])


def test_strong_history_reinforces_positive_trade():
    result = coach(price=103, history={"historical_grade": "STRONG"})

    assert result["status"] == "HOLD"
    assert any("reinforces" in reason for reason in result["reasons"])


def test_insufficient_history_avoids_certainty():
    result = coach(price=103)

    assert result["historical_grade"] == "INSUFFICIENT DATA"
    assert any("insufficient" in reason.lower() for reason in result["reasons"])


def test_closed_record_returns_closed():
    result = coach(outcome(exit_time=NOW, exit_reason="TARGET_1"), 110)

    assert result["status"] == "CLOSED"
    assert result["current_return"] is None


def test_never_entered_candidate_is_unavailable():
    result = coach(outcome(entry_time=None), 100)

    assert result["status"] == "UNAVAILABLE"


def test_missing_stop_is_safe():
    result = coach(outcome(stop=None), 102)

    assert result["status"] == "HOLD"
    assert result["risk_remaining"] is None
    assert result["stop_threatened"] is False


def test_missing_targets_is_safe():
    result = coach(
        outcome(target_1=None, target_2=None, target_3=None),
        102,
    )

    assert result["status"] == "HOLD"
    assert result["progress_to_target_1"] is None
    assert result["target_1_reached"] is False


@pytest.mark.parametrize("price", [None, 0, -1, "bad", float("nan")])
def test_invalid_current_price_is_unavailable(price):
    assert coach(price=price)["status"] == "UNAVAILABLE"


def test_progress_calculations_are_direction_aware_and_clamped():
    bullish = coach(price=105)
    bearish = coach(
        outcome(
            direction="Bearish",
            stop=105,
            target_1=90,
            target_2=80,
            target_3=70,
        ),
        95,
    )
    beyond_target = coach(price=150)

    assert bullish["progress_to_target_1"] == pytest.approx(50)
    assert bearish["progress_to_target_1"] == pytest.approx(50)
    assert beyond_target["progress_to_target_1"] == 200


def test_zero_distance_target_is_unavailable_for_progress():
    result = coach(outcome(target_1=100), 102)

    assert result["progress_to_target_1"] is None
    assert result["target_1_reached"] is True


def test_risk_remaining_calculations_are_direction_aware():
    bullish = coach(price=97.5)
    bearish = coach(
        outcome(
            direction="Bearish",
            stop=105,
            target_1=90,
            target_2=80,
            target_3=70,
        ),
        102.5,
    )

    assert bullish["risk_remaining"] == pytest.approx(50)
    assert bearish["risk_remaining"] == pytest.approx(50)


def test_material_reversal_after_target_returns_exit():
    result = coach(outcome(max_favorable_excursion=12), 104)

    assert result["status"] == "EXIT"
    assert "reversed" in result["summary"].lower()
