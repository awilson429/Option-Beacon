import sqlite3
from datetime import datetime, timedelta, timezone

from trade_desk_compact import status_strip_markup, status_strip_model
from trade_repository import TradeRepository
from trade_state_service import authoritative_trade_state, scanner_health_state


NOW = datetime(2026, 8, 5, 18, tzinfo=timezone.utc)
FIELDS = {
    "current_run_number", "current_symbols_attempted", "current_symbol_count",
    "current_results", "current_failures", "progress_updated_at", "current_owner_id",
}


def test_additive_migration_preserves_legacy_health_row(tmp_path):
    database = tmp_path / "legacy.db"
    connection = sqlite3.connect(database)
    connection.execute("""CREATE TABLE scanner_health (
        scanner_id TEXT PRIMARY KEY,last_started_at TEXT,last_completed_at TEXT,
        last_success_at TEXT,last_error_at TEXT,last_error_message TEXT,
        last_symbols_processed INTEGER,scan_duration REAL,code_version TEXT,
        market_data_state TEXT,updated_at TEXT NOT NULL)""")
    connection.execute(
        "INSERT INTO scanner_health (scanner_id,last_success_at,last_symbols_processed,market_data_state,updated_at) VALUES (?,?,?,?,?)",
        ("production", NOW.isoformat(), 68, "AVAILABLE", NOW.isoformat()),
    )
    connection.commit()
    connection.close()

    repository = TradeRepository(database, database_url="")
    row = repository.get_scan_health("production")
    assert row["last_symbols_processed"] == 68
    assert FIELDS <= row.keys()
    assert all(row[field] is None for field in FIELDS)


def test_current_run_progress_and_completion_remain_separate(tmp_path):
    repository = TradeRepository(tmp_path / "state.db", database_url="")
    repository.record_scan_heartbeat(
        "production", completed_at=NOW - timedelta(minutes=8),
        success_at=NOW - timedelta(minutes=8), symbols_processed=68,
        market_data_state="AVAILABLE",
    )
    owner = repository.acquire_scan_lock(
        "production", owner_id="deployment-new", ttl_seconds=1200
    )
    repository.start_scan_run(
        "production", run_number=3, owner_id=owner, started_at=NOW,
        code_version="abc",
    )
    assert repository.record_scan_progress(
        "production", run_number=3, owner_id=owner, symbols_attempted=30,
        symbol_count=68, results=30, failures=0, at=NOW + timedelta(minutes=7),
    )
    active = repository.get_scan_health("production")
    assert active["last_symbols_processed"] == 68
    assert active["current_symbols_attempted"] == 30
    assert active["current_symbol_count"] == 68
    state = scanner_health_state(
        active, scan_lock=repository.get_scan_lock("production"),
        now=NOW + timedelta(minutes=7),
    )
    assert state["state"] == "SCANNING"

    assert repository.finish_scan_run(
        "production", run_number=3, owner_id=owner,
        completed_at=NOW + timedelta(minutes=17), symbols_attempted=68,
        symbol_count=68, results=68, failures=0, scan_duration=1020,
        code_version="abc", market_data_state="AVAILABLE",
    )
    completed = repository.get_scan_health("production")
    assert completed["last_symbols_processed"] == 68
    assert completed["current_symbols_attempted"] == 68
    assert completed["current_symbol_count"] == 68
    assert completed["current_owner_id"] is None


def test_expired_owner_cannot_overwrite_takeover_progress(tmp_path, monkeypatch):
    import trade_repository

    repository = TradeRepository(tmp_path / "takeover.db", database_url="")
    monkeypatch.setattr(trade_repository, "utc_now", lambda: NOW)
    old = repository.acquire_scan_lock("production", owner_id="old", ttl_seconds=60)
    repository.start_scan_run("production", run_number=1, owner_id=old, started_at=NOW)
    monkeypatch.setattr(trade_repository, "utc_now", lambda: NOW + timedelta(seconds=61))
    new = repository.acquire_scan_lock("production", owner_id="new", ttl_seconds=60)
    repository.start_scan_run(
        "production", run_number=2, owner_id=new,
        started_at=NOW + timedelta(seconds=61), symbol_count=68,
    )
    assert repository.record_scan_progress(
        "production", run_number=1, owner_id=old, symbols_attempted=60,
        symbol_count=68, results=60, failures=0,
    ) is False
    assert repository.record_scan_progress(
        "production", run_number=2, owner_id=new, symbols_attempted=10,
        symbol_count=68, results=10, failures=0,
    ) is True
    assert repository.get_scan_health("production")["current_symbols_attempted"] == 10


def test_scanner_state_semantics_cover_current_stale_waiting_and_error():
    current = scanner_health_state({
        "last_success_at": NOW.isoformat(), "market_data_state": "AVAILABLE",
    }, now=NOW)
    stale = scanner_health_state({
        "last_success_at": (NOW - timedelta(minutes=20)).isoformat(),
        "market_data_state": "AVAILABLE",
    }, now=NOW, stale_minutes=15)
    waiting = scanner_health_state({}, now=NOW)
    error = scanner_health_state({
        "last_error_at": NOW.isoformat(), "market_data_state": "ERROR",
    }, now=NOW)
    assert [current["state"], stale["state"], waiting["state"], error["state"]] == [
        "CURRENT", "STALE", "WAITING", "ERROR",
    ]


def test_stale_progress_is_not_presented_as_active_even_with_live_lease():
    health = {
        "last_success_at": (NOW - timedelta(minutes=20)).isoformat(),
        "market_data_state": "SCANNING", "current_owner_id": "worker",
        "progress_updated_at": (NOW - timedelta(minutes=6)).isoformat(),
    }
    lock = {
        "owner_id": "worker", "expires_at": (NOW + timedelta(minutes=1)).isoformat(),
    }
    assert scanner_health_state(health, scan_lock=lock, now=NOW)["state"] == "STALE"


def test_authoritative_state_propagates_completed_and_current_counts(tmp_path):
    repository = TradeRepository(tmp_path / "shared.db", database_url="")
    repository.record_scan_heartbeat(
        "production", completed_at=NOW, success_at=NOW,
        symbols_processed=68, market_data_state="AVAILABLE",
    )
    state = authoritative_trade_state(
        db_file=tmp_path / "shared.db", database_url="", now=NOW,
    )
    assert state["last_symbols_processed"] == 68
    markup = status_strip_markup(status_strip_model(
        {**state, "current_symbol_count": 68},
        market_open=True, paper_active=False, now=NOW,
    ))
    assert "SCANNER CURRENT · 68/68" in markup
    assert "0/8" not in markup
