from datetime import datetime, timedelta, timezone

from legacy_trade_import import import_legacy_history
from signal_history import TradeOutcome, append_trade_outcome
from trade_repository import TradeRepository


def outcome():
    now = datetime(2026, 7, 30, 15, 0, tzinfo=timezone.utc)
    return TradeOutcome(
        trade_id="legacy-trade",
        timestamp=now - timedelta(minutes=20),
        symbol="SPY",
        direction="Bullish",
        setup="Breakout",
        confidence=80,
        entry=500,
        stop=495,
        target_1=505,
        target_2=510,
        target_3=515,
        entry_time=now - timedelta(minutes=10),
        exit_time=None,
        exit_reason=None,
        max_favorable_excursion=None,
        max_adverse_excursion=None,
        realized_return=None,
        hold_minutes=10,
    )


def test_legacy_import_is_dry_run_by_default(tmp_path):
    source = tmp_path / "signal_history.jsonl"
    append_trade_outcome(outcome(), source)
    repo = TradeRepository(tmp_path / "state.db", database_url="")

    report = import_legacy_history(source, repo)

    assert report.imported == 1
    assert repo.list_opportunities() == []


def test_legacy_import_is_idempotent(tmp_path):
    source = tmp_path / "signal_history.jsonl"
    append_trade_outcome(outcome(), source)
    repo = TradeRepository(tmp_path / "state.db", database_url="")

    first = import_legacy_history(source, repo, dry_run=False)
    second = import_legacy_history(source, repo, dry_run=False)

    assert first.imported == 1
    assert second.duplicates == 1
    assert len(repo.list_opportunities()) == 1


def test_legacy_import_reports_invalid_rows(tmp_path):
    source = tmp_path / "signal_history.jsonl"
    source.write_text("{malformed}\n", encoding="utf-8")
    repo = TradeRepository(tmp_path / "state.db", database_url="")

    report = import_legacy_history(source, repo, dry_run=False)
    assert report.invalid == 1
    assert repo.list_opportunities() == []
