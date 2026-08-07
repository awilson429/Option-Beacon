import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import optionbeacon.worker.scan_once as scan_module
from authoritative_entry_funnel import AuthoritativeEntryFunnelRepository
from optionbeacon.worker.scan_once import record_authoritative_entry_funnel, run_scan_once
from signal_history import TradeOutcome
from trade_repository import TradeRepository
from trade_state_service import sync_trade_outcome


NOW = datetime(2026, 8, 6, 15, 0, tzinfo=timezone.utc)


def valid_result(symbol="SPY", *, directional=True, triggered=False):
    direction = "Bullish" if directional else "Neutral"
    return {
        "symbol": symbol, "signal": "BULLISH SETUP" if triggered else "WATCHLIST",
        "bias": direction, "confidence": 95 if triggered else 80, "price": 100.1 if triggered else 99.5,
        "setup_stage": "Triggered" if triggered else "Developing",
        "entry_timing": "Trigger confirmed" if triggered else "Too early",
        "timestamp": NOW.isoformat(),
        "trade_plan": ({
            "direction": direction, "setup_type": "Bullish breakout", "trigger_price": 100,
            "technical_stop": 99, "target_1": 101, "target_2": 102, "target_3": 103,
        } if directional else {}),
    }


def cycle_count(repository):
    with repository.connection() as connection:
        return repository._fetchone(connection, "SELECT COUNT(*) AS count FROM authoritative_entry_funnel_cycles")["count"]


def messages(caplog):
    return [json.loads(record.getMessage()) for record in caplog.records if record.getMessage().startswith("{")]


def test_healthy_zero_trade_cycle_persists_exactly_one_snapshot(tmp_path, caplog):
    repository = TradeRepository(tmp_path / "state.db", database_url="")
    with caplog.at_level(logging.INFO):
        result = run_scan_once(
            repository=repository, scanner_id="production", run_number=7,
            symbol_groups_loader=lambda: ({"Full": ["SPY", "QQQ"]}, "test", ""),
            signal_generator=lambda symbol: valid_result(symbol),
            snapshot_writer=lambda results: None,
            clock=lambda: NOW,
        )
    cycle = AuthoritativeEntryFunnelRepository(repository, initialize=False).latest_cycle("2026-08-06")
    events = messages(caplog)
    assert result == 0 and cycle_count(repository) == 1
    assert cycle["scanned"] == 2 and cycle["valid_results"] == 2
    assert cycle["trade_entered"] == 0 and cycle["trigger_reached"] == 0
    assert sum(cycle["blocker_counts"].values()) == 2
    assert sum(row.get("event") == "authoritative_entry_funnel_started" for row in events) == 1
    assert sum(row.get("event") == "authoritative_entry_funnel_completed" for row in events) == 1


def test_zero_directional_ready_and_trigger_counts_still_persist(tmp_path):
    repository = TradeRepository(tmp_path / "state.db", database_url="")
    assert run_scan_once(
        repository=repository, scanner_id="production", run_number=8,
        symbol_groups_loader=lambda: ({"Full": ["SPY"]}, "test", ""),
        signal_generator=lambda symbol: valid_result(symbol, directional=False),
        snapshot_writer=lambda results: None,
        clock=lambda: NOW,
    ) == 0
    cycle = AuthoritativeEntryFunnelRepository(repository, initialize=False).latest_cycle("2026-08-06")
    assert cycle["directional_candidates"] == 0
    assert cycle["armed"] == 0 and cycle["trigger_reached"] == 0


def test_cycle_with_authoritative_entry_persists_one_snapshot(tmp_path):
    repository = TradeRepository(tmp_path / "state.db", database_url="")
    candidate = TradeOutcome(
        trade_id="existing", timestamp=NOW - timedelta(minutes=5), symbol="SPY",
        direction="Bullish", setup="Bullish breakout", confidence=80, entry=100,
        stop=99, target_1=101, target_2=102, target_3=103, entry_time=None,
        exit_time=None, exit_reason=None, max_favorable_excursion=None,
        max_adverse_excursion=None, realized_return=None, hold_minutes=None,
    )
    sync_trade_outcome(repository, candidate)
    result = run_scan_once(
        repository=repository, scanner_id="production", run_number=9,
        symbol_groups_loader=lambda: ({"Full": ["SPY"]}, "test", ""),
        signal_generator=lambda symbol: valid_result(symbol, triggered=True),
        snapshot_writer=lambda results: None, clock=lambda: NOW,
    )
    cycle = AuthoritativeEntryFunnelRepository(repository, initialize=False).latest_cycle("2026-08-06")
    assert result == 0 and cycle_count(repository) == 1
    assert cycle["trade_entered"] == 1


def test_funnel_failure_is_structured_and_cannot_block_paper_mirror_or_lock(tmp_path, monkeypatch, caplog):
    repository = TradeRepository(tmp_path / "state.db", database_url="")
    paper_calls, mirror_calls = [], []
    monkeypatch.setattr(
        scan_module, "AuthoritativeEntryFunnelRepository",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("schema unavailable")),
    )
    monkeypatch.setattr(scan_module, "run_mirror_execution", lambda *args, **kwargs: mirror_calls.append(True))
    with caplog.at_level(logging.INFO):
        result = run_scan_once(
            repository=repository, scanner_id="production", run_number=10,
            symbol_groups_loader=lambda: ({"Full": ["SPY"]}, "test", ""),
            signal_generator=lambda symbol: valid_result(symbol),
            snapshot_writer=lambda results: None,
            paper_executor=lambda *args, **kwargs: paper_calls.append(True),
        )
    events = messages(caplog)
    failed = [row for row in events if row.get("event") == "authoritative_entry_funnel_failed"]
    assert result == 0 and len(failed) == 1
    assert failed[0]["stage"] == "initialization" and failed[0]["exception_type"] == "RuntimeError"
    assert paper_calls == [True] and mirror_calls == [True]
    assert repository.get_scan_lock("production") is None


def test_retry_same_cycle_identity_upserts_instead_of_duplicating(tmp_path):
    repository = TradeRepository(tmp_path / "state.db", database_url="")
    values = dict(
        repository=repository, scanner_id="production", run_number=11,
        started_at=NOW - timedelta(minutes=1), completed_at=NOW,
        symbols=[("SPY", valid_result("SPY"))],
    )
    assert record_authoritative_entry_funnel(**values)
    assert record_authoritative_entry_funnel(**values)
    assert cycle_count(repository) == 1
    with repository.connection() as connection:
        symbols = repository._fetchone(connection, "SELECT COUNT(*) AS count FROM authoritative_entry_funnel_symbols")["count"]
    assert symbols == 1


def test_schema_initialization_is_additive_and_idempotent(tmp_path):
    repository = TradeRepository(tmp_path / "state.db", database_url="")
    AuthoritativeEntryFunnelRepository(repository)
    AuthoritativeEntryFunnelRepository(repository)
    with repository.connection() as connection:
        names = {row["name"] for row in repository._fetchall(connection,
            "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"authoritative_entry_funnel_cycles", "authoritative_entry_funnel_symbols"} <= names


def test_railway_entrypoint_imports_funnel_enabled_scan_once():
    railway = Path("railway.toml").read_text(encoding="utf-8")
    worker = Path("optionbeacon/worker/run.py").read_text(encoding="utf-8")
    scanner = Path("optionbeacon/worker/scan_once.py").read_text(encoding="utf-8")
    assert "python -m optionbeacon.worker.run" in railway
    assert "from optionbeacon.worker.scan_once import run_scan_once" in worker
    assert "record_authoritative_entry_funnel(" in scanner
