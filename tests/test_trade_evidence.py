from datetime import datetime, timedelta, timezone

from signal_history import create_trade_record
from trade_evidence import (
    UNAVAILABLE,
    actionable_trade_plan,
    evidence_summary,
    format_evidence_metric,
    historical_evidence,
)


START = datetime(2026, 7, 27, 14, 0, tzinfo=timezone.utc)


def live_result(**overrides):
    result = {
        "symbol": "SPY",
        "signal": "BULLISH SETUP",
        "bias": "Bullish",
        "confidence": 85,
        "setup_stage": "Armed",
        "entry_timing": "Watch closely",
        "trade_plan": {
            "setup_type": "Bullish breakout",
            "direction": "Bullish",
            "trigger_price": 100,
        },
    }
    result.update(overrides)
    return result


def outcome(realized_return=2, *, setup="Bullish breakout", exit_reason="TARGET_1"):
    record = create_trade_record(
        symbol="SPY",
        direction="Bullish",
        setup=setup,
        confidence=85,
        entry=100,
        stop=95,
        target_1=103,
        target_2=106,
        target_3=109,
        timestamp=START,
        entry_time=START,
    )
    record.exit_time = START + timedelta(minutes=30)
    record.exit_reason = exit_reason
    record.realized_return = realized_return
    record.hold_minutes = 30
    record.max_favorable_excursion = max(realized_return, 0)
    record.max_adverse_excursion = min(realized_return, 0)
    return record


def evidence_for(wins, losses):
    history = [
        *[outcome(2) for _ in range(wins)],
        *[outcome(-1, exit_reason="STOP") for _ in range(losses)],
    ]
    return historical_evidence(live_result(), history)


def test_strong_evidence_display():
    evidence = evidence_for(7, 3)

    assert evidence["display_grade"] == "STRONG"
    assert "strong across 10 similar trades" in evidence["summary"]


def test_positive_evidence_display():
    evidence = evidence_for(6, 4)

    assert evidence["display_grade"] == "POSITIVE"
    assert "positive across 10 similar trades" in evidence["summary"]


def test_mixed_evidence_display():
    history = [
        *[outcome(1) for _ in range(5)],
        *[outcome(-1, exit_reason="STOP") for _ in range(5)],
    ]

    evidence = historical_evidence(live_result(), history)

    assert evidence["display_grade"] == "MIXED"
    assert evidence["summary"].startswith("Results are mixed")


def test_weak_evidence_display():
    evidence = evidence_for(4, 6)

    assert evidence["display_grade"] == "WEAK"
    assert "results are weak" in evidence["summary"].lower()


def test_insufficient_data_state():
    evidence = historical_evidence(live_result(), [outcome(2) for _ in range(3)])

    assert evidence["display_grade"] == "INSUFFICIENT DATA"
    assert "Not enough completed historical trades" in evidence["summary"]


def test_empty_history_uses_insufficient_data_state():
    evidence = historical_evidence(live_result(), [])

    assert evidence["display_grade"] == "INSUFFICIENT DATA"
    assert "sample size is still too small" in evidence["summary"]


def test_no_match_state():
    history = [outcome(2, setup="Different setup") for _ in range(10)]

    evidence = historical_evidence(live_result(), history)

    assert evidence["display_grade"] == "NO MATCH"
    assert evidence["summary"] == "No matching historical setup data is available yet."


def test_unavailable_metric_formatting():
    assert format_evidence_metric(None) == UNAVAILABLE
    assert format_evidence_metric(float("nan")) == UNAVAILABLE
    assert format_evidence_metric(float("inf")) == UNAVAILABLE
    assert format_evidence_metric("missing") == UNAVAILABLE
    assert format_evidence_metric(2.5, percentage=True) == "2.50%"


def test_confidence_gap_wording():
    summary = evidence_summary(
        {
            "historical_grade": "POSITIVE",
            "match_level": "LEVEL_1",
            "sample_size": 20,
            "confidence_gap": -12,
        }
    )

    assert (
        "current confidence is 12 percentage points above the historical win rate"
        in summary
    )


def test_actionable_setup_eligibility():
    assert actionable_trade_plan(live_result()) is True


def test_invalid_setup_exclusion():
    assert actionable_trade_plan(
        live_result(entry_timing="Setup invalidated")
    ) is False


def test_extended_setup_exclusion():
    assert actionable_trade_plan(
        live_result(setup_stage="Extended", entry_timing="Do not chase")
    ) is False


def test_neutral_setup_exclusion():
    result = live_result(bias="Neutral")
    result["trade_plan"] = {
        "setup_type": "Directional setup",
        "direction": "Neutral",
        "trigger_price": 100,
    }

    assert actionable_trade_plan(result) is False
