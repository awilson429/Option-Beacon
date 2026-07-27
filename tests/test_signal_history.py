from datetime import datetime, timezone

from signal_history import (
    TradeOutcome,
    append_trade_outcome,
    create_trade_record,
    deserialize_trade_outcome,
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
