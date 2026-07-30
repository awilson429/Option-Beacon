from datetime import datetime, timedelta, timezone

from trade_plan_journal import load_trade_plan_journal
from trade_plan_models import PlanStatus
from trade_plan_service import process_scanner_trade_plan


NOW = datetime(2026, 7, 29, 14, 0, tzinfo=timezone.utc)


def result(**overrides):
    values = {
        "symbol": "SPY",
        "bias": "Bullish",
        "price": 500,
        "support": 498,
        "resistance": 500.5,
        "atr": 2,
        "relative_volume": 0.8,
        "confidence": 82,
        "confirmation_reached": False,
        "timestamp": NOW,
        "last_candle_at": NOW,
    }
    values.update(overrides)
    return values


def test_scanner_creates_one_plan_and_reuses_it_across_refreshes(tmp_path):
    path = tmp_path / "journal.jsonl"
    first = process_scanner_trade_plan(result(), path)
    original = first.original_signal_snapshot
    second = process_scanner_trade_plan(
        result(timestamp=NOW + timedelta(minutes=5), last_candle_at=NOW + timedelta(minutes=5)),
        path,
    )

    assert first.trade_plan_id == second.trade_plan_id
    assert second.original_signal_snapshot == original
    assert len(load_trade_plan_journal(path)) == 1


def test_ready_refresh_activates_existing_watch_plan(tmp_path):
    path = tmp_path / "journal.jsonl"
    watch = process_scanner_trade_plan(result(), path)
    active = process_scanner_trade_plan(
        result(
            price=500.6,
            relative_volume=1.5,
            confirmation_reached=True,
            timestamp=NOW + timedelta(minutes=5),
            last_candle_at=NOW + timedelta(minutes=5),
        ),
        path,
    )

    assert watch.status in {PlanStatus.WAIT, PlanStatus.WATCH}
    assert active.status == PlanStatus.ACTIVE
    assert active.current_status["entry_timestamp"] is not None


def test_non_supported_symbol_is_ignored(tmp_path):
    assert process_scanner_trade_plan(result(symbol="IWM"), tmp_path / "journal.jsonl") is None


def test_stale_refresh_cannot_activate_existing_watch_plan(tmp_path):
    path = tmp_path / "journal.jsonl"
    process_scanner_trade_plan(result(), path)
    stale = process_scanner_trade_plan(
        result(
            price=500.6,
            relative_volume=1.5,
            confirmation_reached=True,
            timestamp=NOW + timedelta(minutes=20),
            last_candle_at=NOW,
        ),
        path,
    )

    assert stale.status == PlanStatus.WAIT
    assert stale.current_status["entry_timestamp"] is None


def test_journal_failure_does_not_crash_scanning(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "trade_plan_service.save_trade_plan",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("read only")),
    )

    assert process_scanner_trade_plan(result(), tmp_path / "journal.jsonl") is None


def test_new_engine_has_no_provider_or_order_submission_path():
    from pathlib import Path

    source = "\n".join(
        Path(name).read_text(encoding="utf-8")
        for name in (
            "trade_plan_engine.py",
            "trade_plan_lifecycle.py",
            "trade_plan_journal.py",
            "trade_plan_service.py",
        )
    )
    obsolete_gate_name = "APP_" + "ACCESS" + "_CODE"

    assert "tradier" not in source.lower()
    assert "requests." not in source
    assert "submit_order" not in source
    assert "place_order" not in source
    assert obsolete_gate_name not in source
