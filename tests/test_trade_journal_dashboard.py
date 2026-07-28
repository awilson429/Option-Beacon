from datetime import datetime, timedelta, timezone

from signal_history import create_trade_record
from trade_journal_dashboard import (
    UNAVAILABLE,
    filter_trade_outcomes,
    format_metric,
    sort_trade_outcomes_newest,
    trade_history_rows,
    trade_outcome_status,
)


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
