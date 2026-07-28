from datetime import date, datetime, timedelta, timezone

import pytest

from signal_history import create_trade_record
from trade_desk_view_models import (
    attention_positions,
    daily_scorecard,
    historical_edge_grade,
    historical_edge_summary,
    position_health,
    trade_timeline,
)


NOW = datetime(2026, 7, 28, 16, 0, tzinfo=timezone.utc)


def record(*, symbol="SPY", entered=True, closed=False, result=None, reason=None):
    outcome = create_trade_record(
        symbol=symbol,
        direction="Bullish",
        setup="Breakout",
        confidence=80,
        entry=100,
        stop=95,
        target_1=105,
        target_2=110,
        target_3=115,
        timestamp=NOW - timedelta(minutes=35),
        entry_time=NOW - timedelta(minutes=30),
    )
    if not entered:
        outcome.entry_time = None
    if closed:
        outcome.exit_time = NOW
        outcome.exit_reason = reason or "TARGET_1"
        outcome.realized_return = result
        outcome.hold_minutes = 30
    return outcome


@pytest.mark.parametrize(
    ("evidence", "grade"),
    [
        ({"sample_size": 30, "win_rate": 65, "average_return": 0.1, "profit_factor": 1.5}, "A+"),
        ({"sample_size": 20, "win_rate": 58, "average_return": 0.1, "profit_factor": 1.2}, "A"),
        ({"sample_size": 10, "win_rate": 52, "average_return": 0}, "B"),
        ({"sample_size": 10, "win_rate": 40, "average_return": -0.1}, "C"),
        ({"sample_size": 9, "win_rate": 100, "average_return": 2}, "Insufficient Data"),
        ({"sample_size": 30, "win_rate": 65, "average_return": 0.1}, "A+"),
        ({"sample_size": 30, "win_rate": None, "average_return": 0.1}, "Insufficient Data"),
    ],
)
def test_historical_edge_grades(evidence, grade):
    assert historical_edge_grade(evidence) == grade


def test_historical_edge_summary_is_deterministic():
    evidence = {"sample_size": 24, "win_rate": 63.2, "average_return": 0.314}
    assert historical_edge_summary(evidence) == (
        "24 similar trades · 63% wins · +0.31% average return"
    )


@pytest.mark.parametrize(
    ("kwargs", "label", "treatment"),
    [
        (
            dict(current_price=102, current_return=2, risk_remaining=70, coach_status="HOLD"),
            "Healthy",
            "positive",
        ),
        (
            dict(current_price=99, current_return=-1, risk_remaining=50, coach_status="HOLD"),
            "Watch",
            "caution",
        ),
        (
            dict(current_price=94, current_return=-6, risk_remaining=0, coach_status="EXIT"),
            "Action Needed",
            "negative",
        ),
        (
            dict(current_price=None, current_return=None, risk_remaining=None, coach_status="UNAVAILABLE"),
            "Unavailable",
            "neutral",
        ),
        (
            dict(current_price=101, current_return=1, risk_remaining=60, coach_status="EXIT"),
            "Action Needed",
            "negative",
        ),
        (
            dict(current_price=95, current_return=-5, risk_remaining=0, coach_status="HOLD", stop_threatened=True),
            "Action Needed",
            "negative",
        ),
    ],
)
def test_position_health_states(kwargs, label, treatment):
    assert position_health(**kwargs) == {"label": label, "treatment": treatment}


def test_attention_includes_only_watch_and_action_needed_and_sorts_priority():
    rows = [
        {"Symbol": "HEALTHY", "Position Health": "Healthy", "Entry Datetime": NOW},
        {"Symbol": "WATCH", "Position Health": "Watch", "Entry Datetime": NOW},
        {"Symbol": "EXIT", "Position Health": "Action Needed", "Entry Datetime": NOW},
    ]
    assert [row["Symbol"] for row in attention_positions(rows)] == ["EXIT", "WATCH"]
    assert attention_positions([rows[0]]) == []


def test_daily_scorecard_entered_only_and_open_excluded_from_results():
    scorecard = daily_scorecard(
        [
            record(symbol="OPEN"),
            record(symbol="WIN", closed=True, result=2),
            record(symbol="LOSS", closed=True, result=-1, reason="STOP"),
            record(symbol="FLAT", closed=True, result=0, reason="TIME_EXIT"),
            record(symbol="CANDIDATE", entered=False),
        ],
        date(2026, 7, 28),
    )
    assert scorecard["opened_alerts"] == 4
    assert scorecard["closed_trades"] == 3
    assert scorecard["winners"] == 1
    assert scorecard["losers"] == 1
    assert scorecard["breakeven"] == 1
    assert scorecard["win_rate"] == 50
    assert scorecard["best_trade"] == 2
    assert scorecard["worst_trade"] == -1


def test_daily_scorecard_selected_date_and_unavailable_values():
    old = record(closed=True, result=1)
    old.entry_time = NOW - timedelta(days=1)
    scorecard = daily_scorecard([old], date(2026, 7, 28))
    assert scorecard["opened_alerts"] == 0
    assert scorecard["win_rate"] is None
    assert scorecard["average_realized_return"] is None


def test_trade_timeline_is_chronological_and_supported_only():
    outcome = record(closed=True, result=5, reason="TARGET_1")
    events = trade_timeline(outcome)
    assert [event["event"] for event in events] == [
        "Alert recorded",
        "Entry triggered",
        "Target 1 reached",
        "Trade closed",
    ]
    assert [event["timestamp"] for event in events] == sorted(
        event["timestamp"] for event in events
    )
    assert all("Coach changed" not in event["event"] for event in events)


def test_trade_timeline_stop_and_missing_timestamps():
    stopped = record(closed=True, result=-5, reason="STOP")
    assert "Stop reached" in [event["event"] for event in trade_timeline(stopped)]
    stopped.timestamp = None
    stopped.entry_time = None
    assert [event["event"] for event in trade_timeline(stopped)] == [
        "Stop reached",
        "Trade closed",
    ]
