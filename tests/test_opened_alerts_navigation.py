from datetime import datetime, timedelta, timezone

from signal_history import create_trade_record
from trade_journal_dashboard import (
    UNAVAILABLE,
    filter_trade_outcomes,
    opened_alert_status,
    opened_alerts_analytics,
)
from ui_navigation import (
    MAIN_NAVIGATION,
    NO_ACTIONABLE_OPPORTUNITY_MESSAGE,
    NO_OPEN_ALERTS_MESSAGE,
    RECORDED_CANDIDATES_LABEL,
    TRADE_DESK_SUBTITLE,
    TRADE_DESK_SECTIONS,
    TOOLS_SECTIONS,
)


NOW = datetime(2026, 7, 28, 16, 0, tzinfo=timezone.utc)


def record(
    *,
    symbol="SPY",
    entry_time=None,
    exit_reason=None,
    realized_return=None,
):
    entered_at = entry_time or NOW - timedelta(minutes=30)
    outcome = create_trade_record(
        symbol=symbol,
        direction="Bullish",
        setup="Bullish breakout",
        confidence=80,
        entry=100,
        stop=95,
        target_1=105,
        target_2=110,
        timestamp=entered_at - timedelta(minutes=5),
        entry_time=entered_at,
    )
    if exit_reason is not None:
        outcome.exit_time = NOW
        outcome.exit_reason = exit_reason
        outcome.realized_return = realized_return
    return outcome


def test_opened_alerts_include_entered_records_only():
    entered = record()
    candidate = record(symbol="QQQ")
    candidate.entry_time = None

    result = opened_alerts_analytics(
        [candidate, entered],
        {"SPY": 101},
        NOW,
    )

    assert result["opened_alerts"] == 1
    assert [row["Symbol"] for row in result["rows"]] == ["SPY"]


def test_opened_alerts_sort_newest_entry_first():
    result = opened_alerts_analytics(
        [
            record(symbol="OLD", entry_time=NOW - timedelta(hours=1)),
            record(symbol="NEW", entry_time=NOW - timedelta(minutes=5)),
        ],
        {"OLD": 101, "NEW": 101},
        NOW,
    )

    assert [row["Symbol"] for row in result["rows"]] == ["NEW", "OLD"]


def test_opened_alert_open_status():
    assert opened_alert_status(record()) == "OPEN"


def test_opened_alert_target_statuses():
    assert opened_alert_status(record(exit_reason="TARGET_1")) == "TARGET 1"
    assert opened_alert_status(record(exit_reason="TARGET_2")) == "TARGET 2"
    assert opened_alert_status(record(exit_reason="TARGET_3")) == "TARGET 3"


def test_opened_alert_stopped_and_time_exit_statuses():
    assert opened_alert_status(record(exit_reason="STOP")) == "STOPPED"
    assert opened_alert_status(record(exit_reason="TIME_EXIT")) == "TIME EXIT"


def test_opened_alert_generic_closed_status():
    assert opened_alert_status(record(exit_reason="MANUAL")) == "CLOSED"


def test_opened_alert_open_return_and_missing_price():
    result = opened_alerts_analytics(
        [record(symbol="SPY"), record(symbol="QQQ")],
        {"SPY": 101},
        NOW,
    )
    rows = {row["Symbol"]: row for row in result["rows"]}

    assert rows["SPY"]["Open Return"] == "+1.00%"
    assert rows["SPY"]["Coach Status"] == "HOLD"
    assert rows["QQQ"]["Current Price"] == UNAVAILABLE
    assert rows["QQQ"]["Open Return"] == UNAVAILABLE


def test_opened_alert_summary_counts_and_win_rate():
    result = opened_alerts_analytics(
        [
            record(symbol="OPEN"),
            record(symbol="WIN", exit_reason="TARGET_1", realized_return=2),
            record(symbol="LOSS", exit_reason="STOP", realized_return=-1),
            record(symbol="FLAT", exit_reason="TIME_EXIT", realized_return=0),
        ],
        {"OPEN": 101},
        NOW,
    )

    assert result["opened_alerts"] == 4
    assert result["currently_open"] == 1
    assert result["closed_alerts"] == 3
    assert result["winners"] == 1
    assert result["losers"] == 1
    assert result["breakeven"] == 1
    assert result["win_rate"] == 50
    assert result["average_realized_return"] == 1 / 3
    assert result["rows"][1]["Realized Return"] == "+2.00%"


def test_opened_alerts_respect_current_filters():
    records = [
        record(symbol="SPY"),
        record(symbol="QQQ", exit_reason="STOP", realized_return=-1),
    ]
    filtered = filter_trade_outcomes(records, symbol="SPY")
    result = opened_alerts_analytics(filtered, {"SPY": 101}, NOW)

    assert result["opened_alerts"] == 1
    assert result["currently_open"] == 1
    assert [row["Symbol"] for row in result["rows"]] == ["SPY"]


def test_manual_validation_fields_are_read_only_not_recorded():
    row = opened_alerts_analytics([record()], {"SPY": 101}, NOW)["rows"][0]

    assert row["Followed Manually"] == "Not Recorded"
    assert row["Manual Result"] == "Not Recorded"


def test_trade_desk_is_first_and_live_guide_is_removed():
    assert MAIN_NAVIGATION[0] == "Trade Desk"
    assert MAIN_NAVIGATION[-1] == "Developer Tools"
    assert "Trade Journal" not in MAIN_NAVIGATION
    assert "Live Guide" not in MAIN_NAVIGATION


def test_tools_show_scanner_health_only():
    assert TOOLS_SECTIONS == ("Scanner Health",)
    assert "Trade Replay" not in TOOLS_SECTIONS
    assert "Score Guide" not in TOOLS_SECTIONS
    assert "Saved Trade Tracker" not in TOOLS_SECTIONS


def test_trade_desk_layout_and_removed_live_guide_labels():
    assert TRADE_DESK_SECTIONS == (
        "Today's Best Trade",
        "Open Positions Needing Attention",
        "Today's Scorecard",
        "Opened Alerts",
        "Active Edge",
        "Performance Details",
        "Grouped Performance",
        "Complete Trade History",
    )
    assert "Market Status" not in TRADE_DESK_SECTIONS
    assert "Scanner Health" not in TRADE_DESK_SECTIONS
    assert "Guide Queue" not in TRADE_DESK_SECTIONS
    assert "Risk Watch" not in TRADE_DESK_SECTIONS
    assert "Recent Guide Alerts" not in TRADE_DESK_SECTIONS
    assert TRADE_DESK_SECTIONS.count("Today's Best Trade") == 1
    assert "Live Trade Coach Summary" not in TRADE_DESK_SECTIONS


def test_trade_desk_labels_are_current():
    assert TRADE_DESK_SUBTITLE == (
        "Live alert validation, open-trade management, and system performance."
    )
    assert RECORDED_CANDIDATES_LABEL == "Recorded Candidates"


def test_required_empty_states_are_declared():
    assert NO_OPEN_ALERTS_MESSAGE == "No entered trades are currently open."
    assert NO_ACTIONABLE_OPPORTUNITY_MESSAGE == (
        "No actionable opportunity currently meets the entry requirements."
    )
