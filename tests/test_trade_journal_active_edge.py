from datetime import datetime, timedelta, timezone

import pytest

from signal_history import create_trade_record
from trade_journal_dashboard import (
    UNAVAILABLE,
    active_edge_analytics,
    filter_trade_outcomes,
    format_signed_return,
    journal_summary_metrics,
    performance_caption,
)


NOW = datetime(2026, 7, 28, 16, 0, tzinfo=timezone.utc)


def record(
    *,
    symbol="SPY",
    direction="Bullish",
    status="OPEN",
    entry=100,
    entry_time=None,
    realized_return=None,
    hold_minutes=None,
):
    entered_at = entry_time or NOW - timedelta(minutes=30)
    outcome = create_trade_record(
        symbol=symbol,
        direction=direction,
        setup=f"{direction} setup",
        confidence=80,
        entry=entry,
        stop=95 if direction == "Bullish" else 105,
        target_1=110 if direction == "Bullish" else 90,
        target_2=120 if direction == "Bullish" else 80,
        target_3=130 if direction == "Bullish" else 70,
        timestamp=entered_at - timedelta(minutes=5),
        entry_time=entered_at,
    )
    if status == "CANDIDATE":
        outcome.entry_time = None
    elif status == "NEVER_TRIGGERED":
        outcome.entry_time = None
        outcome.exit_time = NOW
        outcome.exit_reason = "NEVER_TRIGGERED"
    elif status == "CLOSED":
        outcome.exit_time = NOW
        outcome.exit_reason = "TARGET_1" if (realized_return or 0) >= 0 else "STOP"
        outcome.realized_return = realized_return
        outcome.hold_minutes = hold_minutes
    return outcome


def test_journal_summary_open_and_closed_counts():
    metrics = journal_summary_metrics(
        [
            record(status="OPEN"),
            record(status="CLOSED", realized_return=1),
            record(status="CANDIDATE"),
        ]
    )

    assert metrics["open_trades"] == 1
    assert metrics["closed_trades"] == 1


def test_journal_summary_winner_loser_and_breakeven_counts():
    metrics = journal_summary_metrics(
        [
            record(status="CLOSED", realized_return=2),
            record(status="CLOSED", realized_return=-1),
            record(status="CLOSED", realized_return=0),
        ]
    )

    assert metrics["winning_trades"] == 1
    assert metrics["losing_trades"] == 1
    assert metrics["breakeven_trades"] == 1


def test_win_rate_denominator_excludes_breakeven():
    metrics = journal_summary_metrics(
        [
            record(status="CLOSED", realized_return=2),
            record(status="CLOSED", realized_return=-1),
            record(status="CLOSED", realized_return=0),
        ]
    )

    assert metrics["win_rate"] == 50
    assert metrics["average_return"] == pytest.approx(1 / 3)


def test_positive_sign_return_formatting():
    assert format_signed_return(0.2) == "+0.20%"
    assert format_signed_return(-0.2) == "-0.20%"
    assert format_signed_return(0) == "0.00%"
    assert format_signed_return(None) == UNAVAILABLE


def test_completed_open_caption_uses_correct_grammar():
    assert performance_caption(1, 1) == (
        "Performance statistics are based on 1 completed trade. "
        "1 trade remains open."
    )
    assert performance_caption(2, 3) == (
        "Performance statistics are based on 2 completed trades. "
        "3 trades remain open."
    )


def test_bullish_open_return_is_direction_aware():
    analytics = active_edge_analytics([record()], {"SPY": 102}, NOW)

    assert analytics["average_open_return"] == 2
    assert analytics["winning_now"] == 1


def test_bearish_open_return_is_direction_aware():
    analytics = active_edge_analytics(
        [record(direction="Bearish")],
        {"SPY": 98},
        NOW,
    )

    assert analytics["average_open_return"] == 2
    assert analytics["winning_now"] == 1


def test_active_edge_winning_losing_and_breakeven_counts():
    analytics = active_edge_analytics(
        [
            record(symbol="WIN"),
            record(symbol="LOSS"),
            record(symbol="FLAT"),
        ],
        {"WIN": 102, "LOSS": 98, "FLAT": 100},
        NOW,
    )

    assert analytics["winning_now"] == 1
    assert analytics["losing_now"] == 1
    assert analytics["breakeven_now"] == 1


def test_missing_current_price_is_excluded_but_open_is_counted():
    analytics = active_edge_analytics(
        [record(symbol="SPY"), record(symbol="QQQ")],
        {"SPY": 102},
        NOW,
    )

    assert analytics["open_positions"] == 2
    assert analytics["winning_now"] == 1
    assert analytics["losing_now"] == 0
    assert analytics["breakeven_now"] == 0
    assert analytics["average_open_return"] == 2
    assert analytics["rows"][1]["Current Price"] == UNAVAILABLE
    assert analytics["rows"][1]["Open Return"] == UNAVAILABLE


def test_no_open_trades_state_has_no_percentage_averages():
    analytics = active_edge_analytics(
        [record(status="CLOSED", realized_return=1)],
        {"SPY": 102},
        NOW,
    )

    assert analytics["open_positions"] == 0
    assert analytics["rows"] == []
    assert analytics["average_open_return"] is None
    assert analytics["average_target_1_progress"] is None
    assert analytics["average_risk_remaining"] is None


def test_average_minutes_open():
    analytics = active_edge_analytics(
        [
            record(entry_time=NOW - timedelta(minutes=20)),
            record(symbol="QQQ", entry_time=NOW - timedelta(minutes=40)),
        ],
        {"SPY": 101, "QQQ": 101},
        NOW,
    )

    assert analytics["average_minutes_open"] == 30


def test_active_edge_rows_sort_newest_entry_first():
    analytics = active_edge_analytics(
        [
            record(symbol="OLD", entry_time=NOW - timedelta(minutes=60)),
            record(symbol="NEW", entry_time=NOW - timedelta(minutes=10)),
        ],
        {"OLD": 101, "NEW": 101},
        NOW,
    )

    assert [row["Symbol"] for row in analytics["rows"]] == ["NEW", "OLD"]


def test_filtered_metrics_are_calculated_from_filtered_records_only():
    records = [
        record(symbol="SPY", status="OPEN"),
        record(symbol="SPY", status="CLOSED", realized_return=2),
        record(symbol="QQQ", status="CLOSED", realized_return=-2),
    ]
    filtered = filter_trade_outcomes(records, symbol="SPY")
    summary = journal_summary_metrics(filtered)
    active = active_edge_analytics(filtered, {"SPY": 101}, NOW)

    assert summary["total_signals"] == 2
    assert summary["open_trades"] == 1
    assert summary["closed_trades"] == 1
    assert summary["winning_trades"] == 1
    assert summary["losing_trades"] == 0
    assert active["open_positions"] == 1
