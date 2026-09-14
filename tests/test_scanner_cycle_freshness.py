import json
import logging
from datetime import datetime, timedelta, timezone

from api.services import OptionBeaconReadService
from optionbeacon.worker.scan_once import run_scan_once
from trade_repository import DEFAULT_SCANNER_ID, TradeRepository, parse_utc


NOW = datetime(2026, 9, 14, 17, 35, tzinfo=timezone.utc)
PRIOR_SUCCESS = NOW - timedelta(minutes=20)


def _json_events(caplog):
    events = []
    for record in caplog.records:
        message = record.getMessage()
        if not message.startswith("{"):
            continue
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("event"):
            events.append(payload)
    return events


def _seed_prior_success(repository, scanner_id=DEFAULT_SCANNER_ID):
    repository.record_scan_heartbeat(
        scanner_id, completed_at=PRIOR_SUCCESS, success_at=PRIOR_SUCCESS,
        symbols_processed=68, market_data_state="AVAILABLE",
    )


def test_symbol_success_does_not_advance_last_success_until_cycle_finishes(tmp_path):
    repository = TradeRepository(tmp_path / "state.db", database_url="")
    _seed_prior_success(repository)

    def fail_paper(*_args, **_kwargs):
        raise RuntimeError("paper hung after symbols")

    result = run_scan_once(
        repository=repository, scanner_id=DEFAULT_SCANNER_ID, run_number=110,
        symbol_groups_loader=lambda: ({"Core": ["SPY"]}, "test", ""),
        signal_generator=lambda symbol: {"symbol": symbol, "signal": "WAIT", "price": 500},
        snapshot_writer=lambda results: None,
        paper_executor=fail_paper,
    )
    assert result == 1
    health = repository.get_scan_health(DEFAULT_SCANNER_ID)
    assert parse_utc(health["last_success_at"]) == PRIOR_SUCCESS
    assert health["last_error_at"] is not None
    cycle = repository.latest_provenance_cycle()
    assert cycle["cycle_status"] == "ERROR"


def test_completed_cycle_updates_authoritative_freshness_and_snapshot(tmp_path):
    repository = TradeRepository(tmp_path / "done.db", database_url="")
    _seed_prior_success(repository)
    result = run_scan_once(
        repository=repository, scanner_id=DEFAULT_SCANNER_ID, run_number=110,
        symbol_groups_loader=lambda: ({"Core": ["SPY"]}, "test", ""),
        signal_generator=lambda symbol: {"symbol": symbol, "signal": "WAIT", "price": 500},
        snapshot_writer=lambda results: None,
        paper_executor=lambda *args, **kwargs: None,
        clock=lambda: NOW,
    )
    assert result == 0
    health = repository.get_scan_health(DEFAULT_SCANNER_ID)
    assert parse_utc(health["last_success_at"]) == NOW
    snapshot = OptionBeaconReadService(repository=repository, now=lambda: NOW).live_snapshot()
    assert snapshot["scanner"]["last_successful_completed_cycle"] == NOW
    assert snapshot["scanner"]["cycle_completion_state"] == "COMPLETED"
    assert snapshot["market"]["freshness"] == "fresh"
    assert snapshot["scanner"]["status"] == "CURRENT"


def test_in_progress_run_does_not_treat_lease_or_symbol_progress_as_completed(tmp_path, monkeypatch):
    import trade_repository
    monkeypatch.setattr(trade_repository, "utc_now", lambda: NOW)
    repository = TradeRepository(tmp_path / "running.db", database_url="")
    scanner_id = "railway-primary"
    _seed_prior_success(repository, scanner_id)
    owner = repository.acquire_scan_lock(scanner_id, owner_id="worker-110", ttl_seconds=1200)
    repository.start_scan_run(
        scanner_id, run_number=110, owner_id=owner, started_at=NOW - timedelta(minutes=18),
        symbol_count=68, code_version="test",
    )
    assert repository.record_scan_progress(
        scanner_id, run_number=110, owner_id=owner, symbols_attempted=40,
        symbol_count=68, results=40, failures=0, at=NOW,
    )
    snapshot = OptionBeaconReadService(repository=repository, now=lambda: NOW).live_snapshot()
    assert snapshot["scanner"]["status"] == "SCANNING"
    assert snapshot["scanner"]["last_successful_completed_cycle"] == PRIOR_SUCCESS
    assert snapshot["market"]["freshness"] == "stale"
    assert "scanner_stale_or_unavailable" in snapshot["system"]["stale_or_missing"]
    assert snapshot["system"]["state"]["worker_status"] == "degraded"
    assert snapshot["system"]["state"]["worker_last_success"] == PRIOR_SUCCESS


def test_owner_mismatch_does_not_persist_cycle_completion(tmp_path):
    repository = TradeRepository(tmp_path / "mismatch.db", database_url="")
    _seed_prior_success(repository)
    owner = repository.acquire_scan_lock(DEFAULT_SCANNER_ID, owner_id="owner-a", ttl_seconds=1200)
    repository.start_scan_run(
        DEFAULT_SCANNER_ID, run_number=110, owner_id=owner, started_at=NOW,
    )
    assert repository.finish_scan_run(
        DEFAULT_SCANNER_ID, run_number=110, owner_id="someone-else",
        completed_at=NOW, symbols_attempted=68, symbol_count=68, results=68,
        failures=0, scan_duration=1200, market_data_state="AVAILABLE",
    ) is False
    health = repository.get_scan_health(DEFAULT_SCANNER_ID)
    assert parse_utc(health["last_success_at"]) == PRIOR_SUCCESS
    assert health["current_owner_id"] == owner


def test_cycle_lifecycle_logs_distinguish_symbols_from_completion(tmp_path, caplog):
    repository = TradeRepository(tmp_path / "logs.db", database_url="")
    with caplog.at_level(logging.INFO):
        result = run_scan_once(
            repository=repository, scanner_id=DEFAULT_SCANNER_ID, run_number=110,
            symbol_groups_loader=lambda: ({"Core": ["SPY"]}, "test", ""),
            signal_generator=lambda symbol: {"symbol": symbol, "signal": "WAIT", "price": 500},
            snapshot_writer=lambda results: None,
            paper_executor=lambda *args, **kwargs: None,
        )
    assert result == 0
    names = [row["event"] for row in _json_events(caplog)]
    assert "scanner_symbol_timing" in names
    assert "scanner_cycle_started" in names
    assert "scanner_cycle_finalizing" in names
    assert "scanner_cycle_persisted" in names
    assert "scanner_cycle_completed" in names
    assert "scan_completed" not in names
    assert "scan_failed" not in names
    persisted = next(row for row in _json_events(caplog) if row["event"] == "scanner_cycle_persisted")
    assert persisted["health_row_updated"] is True
    assert persisted["run_number"] == 110
    completed = next(row for row in _json_events(caplog) if row["event"] == "scanner_cycle_completed")
    assert completed["cycle_id"]
    assert completed["completed_symbol_count"] == 1


def test_lock_contention_skips_before_cycle_start_and_does_not_advance_last_success(tmp_path, caplog):
    repository = TradeRepository(tmp_path / "skip.db", database_url="")
    _seed_prior_success(repository)
    owner = repository.acquire_scan_lock(DEFAULT_SCANNER_ID, owner_id="existing-owner", ttl_seconds=1200)
    with caplog.at_level(logging.INFO):
        result = run_scan_once(
            repository=repository, scanner_id=DEFAULT_SCANNER_ID, run_number=2,
            lock_owner_id="new-worker",
            symbol_groups_loader=lambda: ({"Core": ["SPY"]}, "test", ""),
            signal_generator=lambda symbol: {"symbol": symbol, "signal": "WAIT", "price": 500},
            snapshot_writer=lambda results: None,
        )
    assert result == 2
    names = [row["event"] for row in _json_events(caplog)]
    skipped = next(row for row in _json_events(caplog) if row["event"] == "scanner_cycle_skipped")
    assert skipped["reason"] == "lock_unavailable"
    assert skipped["lock_owner_id"] == owner
    assert skipped["run_number"] == 2
    assert "scanner_cycle_started" not in names
    assert "scanner_cycle_completed" not in names
    health = repository.get_scan_health(DEFAULT_SCANNER_ID)
    assert parse_utc(health["last_success_at"]) == PRIOR_SUCCESS

