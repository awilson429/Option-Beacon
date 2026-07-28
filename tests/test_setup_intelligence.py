import math
from datetime import datetime, timedelta, timezone

from signal_history import create_trade_record, rewrite_trade_outcomes
from setup_intelligence import historical_grade, setup_intelligence


START = datetime(2026, 7, 27, 14, 0, tzinfo=timezone.utc)


def current_result(
    *,
    symbol="SPY",
    setup="Bullish breakout",
    direction="Bullish",
    confidence=85,
):
    return {
        "symbol": symbol,
        "bias": direction,
        "confidence": confidence,
        "trade_plan": {
            "setup_type": setup,
            "direction": direction,
        },
    }


def outcome(
    realized_return=2,
    *,
    symbol="SPY",
    setup="Bullish breakout",
    direction="Bullish",
    confidence=85,
    exit_reason="TARGET_1",
    hold_minutes=30,
    mfe=3,
    mae=-1,
):
    record = create_trade_record(
        symbol=symbol,
        direction=direction,
        setup=setup,
        confidence=confidence,
        entry=100,
        stop=95,
        target_1=103,
        target_2=106,
        target_3=109,
        timestamp=START,
        entry_time=START,
    )
    record.exit_time = START + timedelta(minutes=hold_minutes)
    record.exit_reason = exit_reason
    record.realized_return = realized_return
    record.hold_minutes = hold_minutes
    record.max_favorable_excursion = mfe
    record.max_adverse_excursion = mae
    return record


def repeated(count, **overrides):
    return [outcome(**overrides) for _ in range(count)]


def test_exact_symbol_setup_direction_matching():
    exact = repeated(10, symbol="SPY")
    other_symbols = repeated(10, symbol="QQQ")

    result = setup_intelligence(current_result(), exact + other_symbols)

    assert result["match_level"] == "LEVEL_1"
    assert result["sample_size"] == 10


def test_direct_trade_plan_input():
    plan = {
        "symbol": "SPY",
        "setup_type": "Bullish breakout",
        "direction": "Bullish",
        "confidence": 85,
    }

    result = setup_intelligence(plan, repeated(10))

    assert result["match_level"] == "LEVEL_1"
    assert result["current_confidence"] == 85


def test_fallback_to_setup_and_direction():
    exact = repeated(2, symbol="SPY")
    same_direction = repeated(8, symbol="QQQ")

    result = setup_intelligence(current_result(), exact + same_direction)

    assert result["match_level"] == "LEVEL_2"
    assert result["sample_size"] == 10


def test_fallback_to_setup_only():
    bullish = repeated(4, direction="Bullish")
    bearish = repeated(6, direction="Bearish")

    result = setup_intelligence(current_result(), bullish + bearish)

    assert result["match_level"] == "LEVEL_3"
    assert result["sample_size"] == 10


def test_insufficient_sample_handling():
    result = setup_intelligence(current_result(), repeated(3))

    assert result["sample_size"] == 3
    assert result["historical_grade"] == "INSUFFICIENT DATA"


def test_weak_grade():
    assert historical_grade(10, 70, -0.1) == "WEAK"
    assert historical_grade(10, 44.99, 1) == "WEAK"


def test_mixed_grade():
    assert historical_grade(10, 50, 0) == "MIXED"


def test_positive_grade():
    assert historical_grade(10, 60, 1) == "POSITIVE"


def test_strong_grade():
    assert historical_grade(10, 65, 1) == "STRONG"


def test_never_triggered_is_excluded():
    history = repeated(9)
    never_triggered = outcome(
        99,
        exit_reason="NEVER_TRIGGERED",
    )
    never_triggered.entry_time = None

    result = setup_intelligence(current_result(), [*history, never_triggered])

    assert result["sample_size"] == 9
    assert result["wins"] == 9
    assert result["historical_grade"] == "INSUFFICIENT DATA"


def test_missing_return_is_excluded():
    result = setup_intelligence(
        current_result(),
        [*repeated(9), outcome(None)],
    )

    assert result["sample_size"] == 9


def test_target_and_stop_rate_calculations():
    history = [
        *repeated(4, exit_reason="TARGET_1"),
        *repeated(3, exit_reason="TARGET_2"),
        *repeated(1, exit_reason="TARGET_3"),
        *repeated(2, realized_return=-1, exit_reason="STOP"),
    ]

    result = setup_intelligence(current_result(), history)

    assert result["target_1_rate"] == 40
    assert result["target_2_rate"] == 30
    assert result["target_3_rate"] == 10
    assert result["stop_rate"] == 20


def test_confidence_bucket_comparison():
    history = [
        *repeated(6, confidence=82, realized_return=2),
        *repeated(4, confidence=89, realized_return=-1, exit_reason="STOP"),
    ]

    result = setup_intelligence(current_result(confidence=85), history)

    assert result["confidence_bucket"] == "80-89"
    assert result["current_confidence"] == 85
    assert result["historical_confidence_win_rate"] == 60
    assert result["confidence_gap"] == -25


def test_empty_history():
    result = setup_intelligence(current_result(), [])

    assert result["match_level"] == "NO_MATCH"
    assert result["sample_size"] == 0
    assert result["historical_grade"] == "INSUFFICIENT DATA"
    assert result["average_return"] is None


def test_no_matching_setup():
    result = setup_intelligence(
        current_result(),
        repeated(10, setup="Different setup"),
    )

    assert result["match_level"] == "NO_MATCH"
    assert result["sample_size"] == 0


def test_custom_minimum_sample_size():
    result = setup_intelligence(
        current_result(),
        repeated(3),
        minimum_sample_size=3,
    )

    assert result["match_level"] == "LEVEL_1"
    assert result["sample_size"] == 3
    assert result["historical_grade"] == "STRONG"


def test_only_winners_and_zero_loss_profit_factor():
    result = setup_intelligence(current_result(), repeated(10, realized_return=2))

    assert result["wins"] == 10
    assert result["losses"] == 0
    assert result["profit_factor"] == math.inf


def test_only_losers():
    result = setup_intelligence(
        current_result(),
        repeated(10, realized_return=-1, exit_reason="STOP"),
    )

    assert result["wins"] == 0
    assert result["losses"] == 10
    assert result["profit_factor"] == 0
    assert result["historical_grade"] == "WEAK"


def test_history_path_uses_existing_loader(tmp_path):
    history_file = tmp_path / "signal_history.jsonl"
    rewrite_trade_outcomes(repeated(10), history_file)

    result = setup_intelligence(current_result(), history_file)

    assert result["match_level"] == "LEVEL_1"
    assert result["sample_size"] == 10
