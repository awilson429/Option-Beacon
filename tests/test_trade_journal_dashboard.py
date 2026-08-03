from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from signal_history import create_trade_record
from trade_journal_dashboard import (
    UNAVAILABLE,
    default_opened_alert_date,
    filter_trade_outcomes,
    format_metric,
    opened_alert_dates,
    opened_alerts_for_date,
    sort_trade_outcomes_newest,
    trade_history_rows,
    trade_outcome_status,
)
from trade_desk_view_models import daily_scorecard, eastern_trade_date


START = datetime(2026, 7, 27, 14, 0, tzinfo=timezone.utc)


def record(
    *,
    symbol="SPY",
    setup="Bullish breakout",
    direction="Bullish",
    confidence=85,
    timestamp=START,
    status="CANDIDATE",
    exit_reason=None,
):
    outcome = create_trade_record(
        symbol=symbol,
        direction=direction,
        setup=setup,
        confidence=confidence,
        entry=100,
        stop=95,
        target_1=103,
        target_2=106,
        target_3=109,
        timestamp=timestamp,
        entry_time=timestamp,
    )
    if status == "CANDIDATE":
        outcome.entry_time = None
    elif status == "OPEN":
        outcome.entry_time = timestamp
    elif status == "CLOSED":
        outcome.entry_time = timestamp
        outcome.exit_time = timestamp + timedelta(minutes=30)
        outcome.exit_reason = exit_reason or "TARGET_1"
        outcome.realized_return = 3
    elif status == "NEVER TRIGGERED":
        outcome.entry_time = None
        outcome.exit_time = timestamp + timedelta(minutes=60)
        outcome.exit_reason = "NEVER_TRIGGERED"
    return outcome


def test_status_labeling():
    assert trade_outcome_status(record(status="CANDIDATE")) == "CANDIDATE"
    assert trade_outcome_status(record(status="OPEN")) == "OPEN"
    assert trade_outcome_status(record(status="CLOSED")) == "CLOSED"
    assert (
        trade_outcome_status(record(status="NEVER TRIGGERED"))
        == "NEVER TRIGGERED"
    )


def test_empty_history_handling():
    assert filter_trade_outcomes([]) == []
    assert sort_trade_outcomes_newest([]) == []
    assert trade_history_rows([]) == []


def test_filtering_by_record_fields_and_confidence_bucket():
    spy = record(status="CLOSED")
    qqq = record(
        symbol="QQQ",
        setup="Bearish breakdown",
        direction="Bearish",
        confidence=92,
        status="CLOSED",
        exit_reason="STOP",
    )
    records = [spy, qqq]

    assert filter_trade_outcomes(records, symbol="SPY") == [spy]
    assert filter_trade_outcomes(records, setup="Bearish breakdown") == [qqq]
    assert filter_trade_outcomes(records, direction="Bearish") == [qqq]
    assert filter_trade_outcomes(records, exit_reason="STOP") == [qqq]
    assert filter_trade_outcomes(records, confidence="90-94") == [qqq]


def test_filtering_by_status():
    candidate = record(status="CANDIDATE")
    open_trade = record(status="OPEN")
    closed = record(status="CLOSED")
    never_triggered = record(status="NEVER TRIGGERED")
    records = [candidate, open_trade, closed, never_triggered]

    assert filter_trade_outcomes(records, status="Candidates") == [candidate]
    assert filter_trade_outcomes(records, status="Entered/Open") == [open_trade]
    assert filter_trade_outcomes(records, status="Closed") == [closed]
    assert filter_trade_outcomes(
        records,
        status="Never Triggered",
    ) == [never_triggered]


def test_newest_first_sorting():
    oldest = record(timestamp=START)
    newest = record(timestamp=START + timedelta(minutes=10), symbol="QQQ")
    middle = record(timestamp=START + timedelta(minutes=5), symbol="IWM")

    sorted_records = sort_trade_outcomes_newest([oldest, newest, middle])

    assert [item.symbol for item in sorted_records] == ["QQQ", "IWM", "SPY"]
    assert [row["Symbol"] for row in trade_history_rows([oldest, newest, middle])] == [
        "QQQ",
        "IWM",
        "SPY",
    ]


def test_unavailable_metric_formatting():
    assert format_metric(None) == UNAVAILABLE
    assert format_metric(float("nan")) == UNAVAILABLE
    assert format_metric(float("inf")) == UNAVAILABLE
    assert format_metric(-float("inf")) == UNAVAILABLE
    assert format_metric("not a number") == UNAVAILABLE
    assert format_metric(2.5, percentage=True) == "2.50%"


def test_current_eastern_date_is_selected_during_market_hours():
    yesterday = record(
        symbol="QQQ",
        timestamp=datetime(2026, 7, 29, 15, 0, tzinfo=timezone.utc),
        status="OPEN",
    )
    today = record(
        symbol="SPY",
        timestamp=datetime(2026, 7, 30, 14, 0, tzinfo=timezone.utc),
        status="OPEN",
    )
    now = datetime(
        2026,
        7,
        30,
        11,
        0,
        tzinfo=ZoneInfo("America/New_York"),
    )

    assert default_opened_alert_date(
        [yesterday, today],
        now,
        market_open=True,
    ) == date(2026, 7, 30)


def test_most_recent_available_date_is_selected_outside_market_hours():
    older = record(
        symbol="QQQ",
        timestamp=datetime(2026, 7, 28, 14, 0, tzinfo=timezone.utc),
        status="OPEN",
    )
    latest = record(
        symbol="SPY",
        timestamp=datetime(2026, 7, 30, 14, 0, tzinfo=timezone.utc),
        status="OPEN",
    )
    weekend = datetime(
        2026,
        8,
        1,
        12,
        0,
        tzinfo=ZoneInfo("America/New_York"),
    )

    assert default_opened_alert_date(
        [older, latest],
        weekend,
        market_open=False,
    ) == date(2026, 7, 30)


def test_historical_date_selection_filters_by_eastern_entry_date():
    first = record(
        symbol="SPY",
        timestamp=datetime(2026, 7, 29, 15, 0, tzinfo=timezone.utc),
        status="OPEN",
    )
    second = record(
        symbol="QQQ",
        timestamp=datetime(2026, 7, 30, 15, 0, tzinfo=timezone.utc),
        status="OPEN",
    )

    assert opened_alerts_for_date(
        [first, second],
        date(2026, 7, 29),
    ) == [first]


def test_utc_timestamp_near_midnight_uses_eastern_trading_date():
    near_midnight_utc = datetime(2026, 7, 30, 1, 0, tzinfo=timezone.utc)
    alert = record(timestamp=near_midnight_utc, status="CLOSED")

    assert eastern_trade_date(near_midnight_utc) == date(2026, 7, 29)
    assert opened_alert_dates([alert]) == [date(2026, 7, 29)]
    assert daily_scorecard([alert], date(2026, 7, 29))["opened_alerts"] == 1


def test_closed_alerts_remain_in_selected_daily_blotter():
    opened = record(symbol="SPY", status="OPEN")
    closed = record(symbol="QQQ", status="CLOSED")

    selected = opened_alerts_for_date(
        [opened, closed],
        eastern_trade_date(START),
    )

    assert {item.symbol for item in selected} == {"SPY", "QQQ"}


def test_date_options_only_include_dates_with_entered_alerts():
    candidate = record(
        timestamp=datetime(2026, 7, 31, 14, 0, tzinfo=timezone.utc),
        status="CANDIDATE",
    )
    first = record(
        timestamp=datetime(2026, 7, 29, 14, 0, tzinfo=timezone.utc),
        status="OPEN",
    )
    second = record(
        timestamp=datetime(2026, 7, 30, 14, 0, tzinfo=timezone.utc),
        status="CLOSED",
    )

    assert opened_alert_dates([candidate, first, second]) == [
        date(2026, 7, 30),
        date(2026, 7, 29),
    ]


def test_empty_daily_alert_selection_is_safe():
    now = datetime(
        2026,
        7,
        30,
        12,
        0,
        tzinfo=ZoneInfo("America/New_York"),
    )
    assert opened_alert_dates([]) == []
    assert default_opened_alert_date([], now, market_open=True) is None
    assert opened_alerts_for_date([], None) == []


def test_trade_desk_removes_old_history_filters_and_uses_compact_empty_state():
    source = open("app.py", encoding="utf-8").read()
    start = source.index("def render_outcome_trade_journal(")
    end = source.index("def render_live_session_opportunity(", start)
    journal = source[start:end]

    for key in (
        "outcome_journal_symbol",
        "outcome_journal_setup",
        "outcome_journal_direction",
        "outcome_journal_exit_reason",
        "outcome_journal_confidence",
        "outcome_journal_status",
    ):
        assert key not in journal
    assert 'key="opened_alert_date"' not in journal
    assert "No active positions · best opportunity is prioritized below." in journal
    assert "trade_desk_activity_filter" in journal
    assert "No trade currently meets the entry requirements." in source
