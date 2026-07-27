from datetime import datetime, timezone

from signal_history import (
    TradeOutcome,
    append_trade_outcome,
    create_trade_record,
    deserialize_trade_outcome,
    record_scanner_result,
    scanner_result_to_trade_outcome,
    serialize_trade_outcome,
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
