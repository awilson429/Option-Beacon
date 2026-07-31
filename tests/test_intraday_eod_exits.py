from datetime import datetime, timezone

import pytest

from intraday_session import (
    EndOfDayConfigurationError,
    configured_eod_exit_time,
    end_of_day_cutoff,
    end_of_day_exit_due,
    intraday_entry_allowed,
    intraday_trade_exit_due,
)
from live_trade_coach_dashboard import open_trade_coach_output
from optionbeacon.worker import run as worker
from optionbeacon.worker.scan_once import run_scan_once
from signal_history import TradeOutcome
from trade_desk_view_models import daily_scorecard
from trade_journal_dashboard import opened_alert_status, opened_alerts_analytics
from trade_repository import TradeRepository
from trade_state_service import (
    list_trade_outcomes,
    process_scanner_result,
    sync_trade_outcome,
)


UTC = timezone.utc
ENTRY_TIME = datetime(2026, 7, 30, 19, 0, tzinfo=UTC)
BEFORE_CUTOFF = datetime(2026, 7, 30, 19, 54, tzinfo=UTC)
AT_CUTOFF = datetime(2026, 7, 30, 19, 55, tzinfo=UTC)


def outcome(**changes):
    values = {
        "trade_id": "eod-trade",
        "timestamp": datetime(2026, 7, 30, 18, 50, tzinfo=UTC),
        "symbol": "FCX",
        "direction": "Bullish",
        "setup": "Breakout",
        "confidence": 80,
        "entry": 100.0,
        "stop": 98.0,
        "target_1": 103.0,
        "target_2": 106.0,
        "target_3": 109.0,
        "entry_time": ENTRY_TIME,
        "exit_time": None,
        "exit_reason": None,
        "max_favorable_excursion": 0.5,
        "max_adverse_excursion": -0.2,
        "realized_return": None,
        "hold_minutes": 54.0,
    }
    values.update(changes)
    return TradeOutcome(**values)


def result(price, symbol="FCX"):
    return {"symbol": symbol, "signal": "WAIT", "price": price}


@pytest.mark.parametrize(
    ("direction", "price", "expected_return"),
    [("Bullish", 101.0, 1.0), ("Bearish", 101.0, -1.0)],
)
def test_open_winner_or_loser_closes_at_cutoff(
    tmp_path, direction, price, expected_return
):
    repository = TradeRepository(tmp_path / "state.db", database_url="")
    levels = (
        {"stop": 102.0, "target_1": 97.0, "target_2": 94.0, "target_3": 91.0}
        if direction == "Bearish"
        else {}
    )
    sync_trade_outcome(repository, outcome(direction=direction, **levels))

    assert process_scanner_result(
        repository,
        result(price),
        current_timestamp=AT_CUTOFF,
    ) == 1

    closed = list_trade_outcomes(repository)[0]
    stored = repository.get_trade(trade_id=closed.trade_id)
    assert closed.exit_reason == "END_OF_DAY"
    assert closed.exit_time == AT_CUTOFF
    assert closed.realized_return == pytest.approx(expected_return)
    assert stored["status"] == "CLOSED"
    assert stored["exit_reason"] == "END_OF_DAY"
    assert stored["exit_price"] == pytest.approx(price)


def test_stop_before_cutoff_is_not_overwritten_and_closed_is_idempotent(tmp_path):
    database = tmp_path / "state.db"
    repository = TradeRepository(database, database_url="")
    sync_trade_outcome(repository, outcome())
    process_scanner_result(
        repository,
        result(98.0),
        current_timestamp=BEFORE_CUTOFF,
    )
    first = list_trade_outcomes(repository)[0]
    assert first.exit_reason == "STOP"

    process_scanner_result(
        repository,
        result(101.0),
        current_timestamp=AT_CUTOFF,
    )
    restarted = TradeRepository(database, database_url="")
    process_scanner_result(
        restarted,
        result(102.0),
        current_timestamp=AT_CUTOFF,
    )
    unchanged = list_trade_outcomes(restarted)[0]
    assert unchanged.exit_reason == "STOP"
    assert unchanged.exit_time == first.exit_time
    assert len(restarted.list_recent_trades()) == 1


def test_target_before_cutoff_is_not_overwritten(tmp_path):
    repository = TradeRepository(tmp_path / "state.db", database_url="")
    sync_trade_outcome(repository, outcome())
    process_scanner_result(
        repository,
        result(103.0),
        current_timestamp=BEFORE_CUTOFF,
    )
    process_scanner_result(
        repository,
        result(101.0),
        current_timestamp=AT_CUTOFF,
    )
    closed = list_trade_outcomes(repository)[0]
    assert closed.exit_reason == "TARGET_1"
    assert closed.realized_return == pytest.approx(3.0)


def test_eastern_cutoff_handles_standard_and_daylight_time():
    winter = end_of_day_cutoff(datetime(2026, 1, 15, 20, 0, tzinfo=UTC))
    summer = end_of_day_cutoff(datetime(2026, 7, 15, 19, 0, tzinfo=UTC))
    assert winter.astimezone(UTC).hour == 20
    assert winter.minute == 55
    assert summer.astimezone(UTC).hour == 19
    assert summer.minute == 55


def test_early_close_uses_same_five_minute_safety_margin():
    early_close_day = datetime(2026, 11, 27, 17, 55, tzinfo=UTC)
    cutoff = end_of_day_cutoff(early_close_day)
    assert cutoff.hour == 12
    assert cutoff.minute == 55
    assert end_of_day_exit_due(early_close_day) is True


def test_weekends_and_market_holidays_do_not_trigger_eod():
    saturday = datetime(2026, 7, 4, 20, 0, tzinfo=UTC)
    observed_holiday = datetime(2026, 7, 3, 20, 0, tzinfo=UTC)
    assert end_of_day_cutoff(saturday) is None
    assert end_of_day_cutoff(observed_holiday) is None
    assert end_of_day_exit_due(saturday) is False
    assert intraday_trade_exit_due(ENTRY_TIME, saturday) is False
    assert intraday_entry_allowed(observed_holiday) is False


def test_overdue_trade_closes_on_next_valid_worker_session(tmp_path):
    repository = TradeRepository(tmp_path / "state.db", database_url="")
    sync_trade_outcome(repository, outcome())
    next_session = datetime(2026, 7, 31, 14, 0, tzinfo=UTC)

    process_scanner_result(
        repository,
        result(99.5),
        current_timestamp=next_session,
    )

    closed = list_trade_outcomes(repository)[0]
    assert closed.exit_reason == "END_OF_DAY"
    assert closed.exit_time == next_session


def test_after_cutoff_candidate_does_not_enter(tmp_path):
    repository = TradeRepository(tmp_path / "state.db", database_url="")
    candidate = outcome(
        entry_time=None,
        max_favorable_excursion=None,
        max_adverse_excursion=None,
        hold_minutes=None,
    )
    sync_trade_outcome(repository, candidate)
    process_scanner_result(
        repository,
        result(101.0),
        current_timestamp=AT_CUTOFF,
    )
    unchanged = list_trade_outcomes(repository)[0]
    assert unchanged.entry_time is None
    assert unchanged.exit_reason == "NEVER_TRIGGERED"


def test_quote_failure_retries_and_later_success_closes(tmp_path, caplog):
    repository = TradeRepository(tmp_path / "state.db", database_url="")
    sync_trade_outcome(repository, outcome())
    replies = [None, None, 101.0]
    calls = []
    delays = []

    def quote(symbol):
        calls.append(symbol)
        price = replies.pop(0)
        return result(price, symbol)

    exit_code = run_scan_once(
        repository=repository,
        symbol_groups_loader=lambda: ({}, "test", ""),
        signal_generator=quote,
        snapshot_writer=lambda _results: None,
        clock=lambda: AT_CUTOFF,
        sleep=delays.append,
    )

    assert exit_code == 0
    assert calls == ["FCX", "FCX", "FCX"]
    assert delays == [1, 2]
    assert list_trade_outcomes(repository)[0].exit_reason == "END_OF_DAY"


def test_quote_unavailable_keeps_trade_open_and_logs_pending_exit(tmp_path, caplog):
    repository = TradeRepository(tmp_path / "state.db", database_url="")
    sync_trade_outcome(repository, outcome())
    calls = []

    def unavailable(symbol):
        calls.append(symbol)
        return result(None, symbol)

    run_scan_once(
        repository=repository,
        symbol_groups_loader=lambda: ({}, "test", ""),
        signal_generator=unavailable,
        snapshot_writer=lambda _results: None,
        clock=lambda: AT_CUTOFF,
        sleep=lambda _seconds: None,
    )

    assert calls == ["FCX", "FCX", "FCX"]
    assert list_trade_outcomes(repository)[0].exit_time is None
    assert '"eod_exit_pending": true' in caplog.text


def test_eod_exit_updates_scorecard_blotter_and_open_positions(tmp_path):
    repository = TradeRepository(tmp_path / "state.db", database_url="")
    sync_trade_outcome(repository, outcome())
    process_scanner_result(
        repository,
        result(101.0),
        current_timestamp=AT_CUTOFF,
    )
    records = list_trade_outcomes(repository)
    scorecard = daily_scorecard(records, AT_CUTOFF.date())
    blotter = opened_alerts_analytics(records, {}, AT_CUTOFF)

    assert repository.list_open_trades() == []
    assert scorecard["closed_trades"] == 1
    assert scorecard["winners"] == 1
    assert scorecard["average_realized_return"] == pytest.approx(1.0)
    assert blotter["opened_alerts"] == 1
    assert blotter["currently_open"] == 0
    assert opened_alert_status(records[0]) == "EOD EXIT"


def test_coach_stops_recommending_hold_near_cutoff():
    coach = open_trade_coach_output(outcome(), 100.5, BEFORE_CUTOFF)
    assert coach["status"] == "EXIT BEFORE CLOSE"
    assert "before the regular session closes" in coach["action"]


@pytest.mark.parametrize("value", ["", "3:55", "16:00", "09:29", "noon"])
def test_eod_configuration_rejects_malformed_or_unsafe_values(value):
    with pytest.raises(EndOfDayConfigurationError):
        configured_eod_exit_time(value)


def test_worker_rejects_invalid_eod_configuration_before_repository(
    monkeypatch,
):
    monkeypatch.setenv("OPTIONBEACON_EOD_EXIT_TIME_ET", "16:30")
    monkeypatch.setattr(
        worker,
        "repository_for_runtime",
        lambda **_kwargs: pytest.fail("repository must not initialize"),
    )
    assert worker.main(["--max-runs", "0"]) == 2
