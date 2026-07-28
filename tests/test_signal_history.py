from copy import deepcopy
from datetime import datetime, timedelta, timezone

from signal_history import (
    TradeOutcome,
    append_trade_outcome,
    create_trade_record,
    deserialize_trade_outcome,
    load_trade_outcomes,
    record_scanner_result,
    rewrite_trade_outcomes,
    scanner_result_to_trade_outcome,
    serialize_trade_outcome,
    update_trade_outcome,
    update_trade_outcomes_from_result,
)


def sample_record(**overrides):
    values = {
        "symbol": "SPY",
        "direction": "Bullish",
        "setup": "Bullish breakout",
        "confidence": 84,
        "entry": 500.25,
        "stop": 497.5,
        "target_1": 503.0,
        "target_2": 506.0,
        "target_3": 509.0,
        "timestamp": datetime(2026, 7, 27, 14, 30, tzinfo=timezone.utc),
        "trade_id": "trade-123",
    }
    values.update(overrides)
    return create_trade_record(**values)


def test_create_trade_record_initializes_open_outcome():
    record = sample_record()

    assert isinstance(record, TradeOutcome)
    assert record.trade_id == "trade-123"
    assert record.symbol == "SPY"
    assert record.entry_time == record.timestamp
    assert record.exit_time is None
    assert record.realized_return is None
    assert record.hold_minutes is None


def test_trade_outcome_json_round_trip():
    record = sample_record()

    restored = deserialize_trade_outcome(serialize_trade_outcome(record))

    assert restored == record


def test_append_trade_outcome_writes_json_lines(tmp_path):
    history_file = tmp_path / "history" / "signals.jsonl"
    first = sample_record()
    second = sample_record(
        trade_id="trade-456",
        symbol="QQQ",
        target_3=None,
    )

    returned_path = append_trade_outcome(first, history_file)
    append_trade_outcome(second, history_file)

    lines = history_file.read_text(encoding="utf-8").splitlines()
    assert returned_path == history_file
    assert len(lines) == 2
    assert deserialize_trade_outcome(lines[0]) == first
    assert deserialize_trade_outcome(lines[1]) == second


def scanner_result(direction="Bullish", **overrides):
    trigger = 500.25
    values = {
        "symbol": "SPY",
        "bias": direction,
        "confidence": 84,
        "setup_stage": "Armed",
        "entry_timing": "Watch closely",
        "last_candle_at": "2026-07-27T10:32:00-04:00",
        "timestamp": "2026-07-27T10:33:10-04:00",
        "trade_plan": {
            "direction": direction,
            "setup_type": (
                "Bullish breakout" if direction == "Bullish" else "Bearish breakdown"
            ),
            "trigger_price": trigger,
            "technical_stop": 497.5 if direction == "Bullish" else 503.0,
            "target_1": 503.0 if direction == "Bullish" else 497.5,
            "target_2": 506.0 if direction == "Bullish" else 495.0,
            "target_3": 509.0 if direction == "Bullish" else 492.5,
        },
    }
    values.update(overrides)
    return values


def test_actionable_bullish_signal_records(tmp_path):
    history_file = tmp_path / "signal_history.jsonl"

    assert record_scanner_result(scanner_result(), history_file) is True

    record = deserialize_trade_outcome(history_file.read_text(encoding="utf-8"))
    assert record.direction == "Bullish"
    assert record.entry == 500.25
    assert record.timestamp is not None
    assert record.entry_time is None
    assert record.exit_time is None
    assert record.realized_return is None


def test_actionable_bearish_signal_records(tmp_path):
    history_file = tmp_path / "signal_history.jsonl"

    assert record_scanner_result(scanner_result("Bearish"), history_file) is True

    record = deserialize_trade_outcome(history_file.read_text(encoding="utf-8"))
    assert record.direction == "Bearish"
    assert record.setup == "Bearish breakdown"


def test_neutral_signal_is_ignored():
    assert scanner_result_to_trade_outcome(scanner_result("Neutral")) is None


def test_invalid_signal_is_ignored():
    result = scanner_result(timing_label="INVALID")
    assert scanner_result_to_trade_outcome(result) is None


def test_extended_signal_is_ignored():
    result = scanner_result(timing_label="EXTENDED")
    assert scanner_result_to_trade_outcome(result) is None


def test_missing_trade_plan_is_ignored():
    assert scanner_result_to_trade_outcome(scanner_result(trade_plan={})) is None


def test_duplicate_signal_is_not_recorded_twice(tmp_path):
    history_file = tmp_path / "signal_history.jsonl"
    first = scanner_result(timestamp="2026-07-27T10:33:10-04:00")
    refreshed = scanner_result(timestamp="2026-07-27T10:34:59-04:00")

    assert record_scanner_result(first, history_file) is True
    assert record_scanner_result(refreshed, history_file) is False
    assert len(history_file.read_text(encoding="utf-8").splitlines()) == 1


def test_write_failure_does_not_crash_scanning(monkeypatch, caplog, tmp_path):
    def fail_write(*args, **kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr("signal_history.append_trade_outcome_once", fail_write)

    assert record_scanner_result(
        scanner_result(),
        tmp_path / "signal_history.jsonl",
    ) is False
    assert "Could not record signal outcome for SPY" in caplog.text


UPDATE_TIME = datetime(2026, 7, 27, 15, 0, tzinfo=timezone.utc)


def lifecycle_record(direction="Bullish", entered=False, **overrides):
    bearish = direction == "Bearish"
    values = {
        "direction": direction,
        "entry": 100,
        "stop": 105 if bearish else 95,
        "target_1": 97 if bearish else 103,
        "target_2": 94 if bearish else 106,
        "target_3": 91 if bearish else 109,
    }
    values.update(overrides)
    record = sample_record(**values)
    record.entry_time = UPDATE_TIME if entered else None
    return record


def test_bullish_signal_does_not_enter_below_entry():
    record = lifecycle_record()

    update_trade_outcome(record, 99, UPDATE_TIME)

    assert record.entry_time is None
    assert record.max_favorable_excursion is None
    assert record.max_adverse_excursion is None
    assert record.realized_return is None
    assert record.hold_minutes is None


def test_bullish_signal_enters_at_or_above_entry():
    record = lifecycle_record()
    entered_at = UPDATE_TIME + timedelta(minutes=5)

    update_trade_outcome(record, 100, entered_at)

    assert record.entry_time == entered_at
    assert record.max_favorable_excursion is None
    assert record.max_adverse_excursion is None


def test_bearish_signal_does_not_enter_above_entry():
    record = lifecycle_record("Bearish")

    update_trade_outcome(record, 101, UPDATE_TIME)

    assert record.entry_time is None


def test_bearish_signal_enters_at_or_below_entry():
    record = lifecycle_record("Bearish")
    entered_at = UPDATE_TIME + timedelta(minutes=5)

    update_trade_outcome(record, 100, entered_at)

    assert record.entry_time == entered_at


def test_mfe_updates_correctly():
    record = lifecycle_record(entered=True, stop=90, target_1=110)

    update_trade_outcome(record, 104, UPDATE_TIME + timedelta(minutes=10))

    assert record.max_favorable_excursion == 4
    assert record.max_adverse_excursion == 0
    assert record.hold_minutes == 10


def test_mae_updates_correctly():
    record = lifecycle_record(entered=True, stop=90)

    update_trade_outcome(record, 96, UPDATE_TIME + timedelta(minutes=15))

    assert record.max_favorable_excursion == 0
    assert record.max_adverse_excursion == -4
    assert record.hold_minutes == 15


def test_bullish_stop_closes_correctly():
    record = lifecycle_record(entered=True)
    closed_at = UPDATE_TIME + timedelta(minutes=20)

    update_trade_outcome(record, 94, closed_at)

    assert record.exit_time == closed_at
    assert record.exit_reason == "STOP"
    assert record.realized_return == -5
    assert record.hold_minutes == 20


def test_bearish_stop_closes_correctly():
    record = lifecycle_record("Bearish", entered=True)

    update_trade_outcome(record, 106, UPDATE_TIME + timedelta(minutes=10))

    assert record.exit_reason == "STOP"
    assert record.realized_return == -5


def test_target_1_closes_correctly():
    record = lifecycle_record(entered=True)

    update_trade_outcome(record, 103, UPDATE_TIME + timedelta(minutes=5))

    assert record.exit_reason == "TARGET_1"
    assert record.realized_return == 3


def test_target_2_closes_correctly():
    record = lifecycle_record(entered=True)

    update_trade_outcome(record, 107, UPDATE_TIME + timedelta(minutes=5))

    assert record.exit_reason == "TARGET_2"
    assert record.realized_return == 6


def test_target_3_closes_correctly():
    record = lifecycle_record("Bearish", entered=True)

    update_trade_outcome(record, 90, UPDATE_TIME + timedelta(minutes=5))

    assert record.exit_reason == "TARGET_3"
    assert record.realized_return == 9


def test_closed_records_do_not_change():
    record = lifecycle_record(entered=True)
    record.exit_time = UPDATE_TIME + timedelta(minutes=5)
    record.exit_reason = "TARGET_1"
    record.realized_return = 3
    original = deepcopy(record)

    update_trade_outcome(record, 90, UPDATE_TIME + timedelta(minutes=30))

    assert record == original


def test_missing_history_file_is_safe(tmp_path):
    history_file = tmp_path / "missing.jsonl"

    assert load_trade_outcomes(history_file) == []
    assert update_trade_outcomes_from_result(
        {"symbol": "SPY", "price": 101, "timestamp": UPDATE_TIME.isoformat()},
        history_file,
    ) == 0
    assert not history_file.exists()


def test_malformed_history_record_is_logged_and_valid_records_continue(
    tmp_path,
    caplog,
):
    history_file = tmp_path / "signal_history.jsonl"
    valid = lifecycle_record()
    history_file.write_text(
        f"not json\n{serialize_trade_outcome(valid)}\n",
        encoding="utf-8",
    )

    records = load_trade_outcomes(history_file)

    assert records == [valid]
    assert "Could not load signal outcome" in caplog.text


def test_update_write_failure_does_not_crash_scanning(
    monkeypatch,
    caplog,
    tmp_path,
):
    history_file = tmp_path / "signal_history.jsonl"
    rewrite_trade_outcomes([lifecycle_record(entered=True)], history_file)

    def fail_write(*args, **kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr("signal_history.rewrite_trade_outcomes", fail_write)

    assert update_trade_outcomes_from_result(
        {
            "symbol": "SPY",
            "price": 101,
            "last_candle_at": (UPDATE_TIME + timedelta(minutes=5)).isoformat(),
        },
        history_file,
    ) == 0
    assert "Could not update signal outcomes for SPY" in caplog.text
