import json
import os
import threading
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from optionbeacon.worker import run as worker
from optionbeacon.worker.healthcheck import check_health
from optionbeacon.worker.scan_once import main as scan_once_main
from reliability_dashboard import reliability_status_model
from trade_repository import RepositoryUnavailable, TradeRepository
from trade_state_service import authoritative_trade_state, repository_for_runtime
import trade_state_service


NOW = datetime(2026, 7, 30, 15, 0, tzinfo=timezone.utc)


class ImmediateWaitEvent:
    def __init__(self):
        self.stopped = False
        self.delays = []

    def is_set(self):
        return self.stopped

    def set(self):
        self.stopped = True

    def wait(self, delay):
        self.delays.append(delay)
        return False


def test_local_mode_uses_sqlite_and_survives_reinitialization(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("OPTIONBEACON_REQUIRE_DURABLE_STORAGE", raising=False)
    monkeypatch.delenv("OPTIONBEACON_ENVIRONMENT", raising=False)
    path = tmp_path / "state.db"
    first = repository_for_runtime(db_file=path, database_url="")
    opportunity = first.create_opportunity(
        symbol="SPY",
        direction="Bullish",
        playbook="Breakout",
        signal_timestamp=NOW,
        source_version="test",
    )
    second = repository_for_runtime(db_file=path, database_url="")

    assert first.backend == second.backend == "sqlite"
    assert second.get_opportunity(opportunity["id"]) is not None


def test_broken_production_configuration_never_falls_back(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("OPTIONBEACON_REQUIRE_DURABLE_STORAGE", "true")
    monkeypatch.setenv("OPTIONBEACON_ENVIRONMENT", "production")

    with pytest.raises(RepositoryUnavailable):
        repository_for_runtime(db_file=tmp_path / "must-not-exist.db", database_url="")
    assert not (tmp_path / "must-not-exist.db").exists()

    state = authoritative_trade_state(
        branch="main",
        database_url="",
        db_file=tmp_path / "must-not-exist.db",
        now=NOW,
    )
    model = reliability_status_model(
        state,
        market_open=True,
        latest_results={},
    )
    assert state["storage_state"] == "UNAVAILABLE"
    assert model["severity"] == "error"
    assert "No open trades" not in model["summary"]


def test_streamlit_and_worker_configuration_share_repository_factory(monkeypatch):
    captured = {}

    class FakeRepository:
        def __init__(self, db_file, *, database_url, require_durable):
            captured.update(
                {
                    "db_file": db_file,
                    "database_url": database_url,
                    "require_durable": require_durable,
                }
            )

    monkeypatch.setattr(
        trade_state_service,
        "configured_database_url",
        lambda: "postgresql://configured-without-printing",
    )
    monkeypatch.setattr(trade_state_service, "TradeRepository", FakeRepository)
    repository_for_runtime(branch="main")

    assert captured["database_url"].startswith("postgresql://")
    assert captured["require_durable"] is True


def test_scan_once_returns_nonzero_when_durable_storage_missing(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("OPTIONBEACON_REQUIRE_DURABLE_STORAGE", "true")
    monkeypatch.setenv("OPTIONBEACON_ENVIRONMENT", "production")
    assert scan_once_main() == 1


def test_invalid_database_error_does_not_disclose_url(monkeypatch, tmp_path):
    secret_url = "postgresql://user:super-secret@invalid.invalid:5432/db"
    state = authoritative_trade_state(
        branch="main",
        database_url=secret_url,
        db_file=tmp_path / "no-fallback.db",
        now=NOW,
    )
    encoded = json.dumps(state, default=str)
    assert state["storage_state"] == "UNAVAILABLE"
    assert secret_url not in encoded
    assert "super-secret" not in encoded
    assert not (tmp_path / "no-fallback.db").exists()


def test_scan_interval_environment_and_bounds(monkeypatch):
    monkeypatch.setenv("OPTIONBEACON_SCAN_SECONDS", "420")
    assert worker.configured_scan_seconds() == 420
    for invalid in ("0", "1", "29", "3601", "not-a-number"):
        with pytest.raises(worker.WorkerConfigurationError):
            worker.configured_scan_seconds(invalid)


def test_worker_remains_alive_without_busy_loop_and_uses_backoff(tmp_path):
    repo = TradeRepository(tmp_path / "state.db", database_url="")
    event = ImmediateWaitEvent()
    outcomes = iter([1, 1, 0])

    completed = worker.run(
        repository=repo,
        interval_seconds=60,
        scanner_id="test-worker",
        max_runs=3,
        scan_once=lambda **_kwargs: next(outcomes),
        stop_event=event,
    )

    assert completed == 3
    assert event.delays == [60, 60]
    assert worker.failure_backoff_seconds(6, 60) <= 900


def test_worker_startup_record_is_sanitized(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://user:secret@database.example/db"
    )
    repo = TradeRepository(tmp_path / "state.db", database_url="")
    encoded = json.dumps(worker.startup_record(repo, 300, "scanner-a"))

    assert "secret" not in encoded
    assert "DATABASE_URL" not in encoded
    assert '"storage_backend": "sqlite"' in encoded


def test_healthcheck_exit_codes(tmp_path):
    repo = TradeRepository(tmp_path / "state.db", database_url="")
    code, never = check_health(repository=repo, scanner_id="health")
    assert code == 1
    assert never["scanner_state"] == "NEVER RUN"

    repo.record_scan_heartbeat(
        "health",
        completed_at=NOW,
        success_at=NOW,
        market_data_state="AVAILABLE",
    )
    code, healthy = check_health(
        repository=repo,
        scanner_id="health",
        stale_minutes=10**9,
    )
    assert code == 0
    assert healthy["database_reachable"] is True


def test_dashboard_does_not_launch_worker_loop():
    source = open("app.py", encoding="utf-8").read()
    assert "optionbeacon.worker.run" not in source
    assert "worker.run(" not in source


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL is not configured",
)
def test_real_postgresql_repository_lifecycle_and_concurrency():
    url = os.environ["TEST_DATABASE_URL"]
    repo = TradeRepository(database_url=url, require_durable=True)
    token = uuid4().hex
    opportunity_id = f"test-opportunity-{token}"
    trade_id = f"test-trade-{token}"
    scanner_id = f"test-scanner-{token}"
    errors = []

    def create_duplicate():
        try:
            TradeRepository(database_url=url, require_durable=True).create_opportunity(
                opportunity_id=opportunity_id,
                idempotency_key=opportunity_id,
                symbol="SPY",
                direction="Bullish",
                playbook="Integration",
                signal_timestamp=NOW,
                source_version=token,
            )
        except Exception as exc:
            errors.append(exc)

    try:
        threads = [threading.Thread(target=create_duplicate) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert errors == []
        opportunity = repo.get_opportunity(opportunity_id)
        assert opportunity["id"] == opportunity_id

        trade = repo.open_trade(
            opportunity_id,
            trade_id=trade_id,
            opened_at=NOW,
            entry_price=500,
            last_price=501,
        )
        assert repo.open_trade(
            opportunity_id,
            opened_at=NOW,
            entry_price=500,
        )["id"] == trade_id
        assert repo.list_open_trades()
        assert repo.update_trade(trade_id, last_price=502)["last_price"] == 502

        repo.record_scan_heartbeat(
            scanner_id,
            started_at=NOW,
            completed_at=NOW,
            success_at=NOW,
            symbols_processed=1,
            market_data_state="AVAILABLE",
        )
        repo.record_scan_error("integration test", scanner_id, at=NOW)
        assert repo.get_scan_health(scanner_id)["last_error_at"] is not None

        repo.close_trade(
            trade_id,
            closed_at=NOW,
            exit_price=505,
            exit_reason="TARGET_1",
            realized_result=1.0,
        )
        assert repo.list_open_trades() == [
            row for row in repo.list_open_trades() if row["id"] != trade_id
        ]
        reinitialized = TradeRepository(
            database_url=url,
            require_durable=True,
        )
        assert reinitialized.get_trade(trade_id=trade_id)["status"] == "CLOSED"
    finally:
        with repo.connection() as connection:
            repo._execute(
                connection,
                "DELETE FROM scanner_health WHERE scanner_id=?",
                (scanner_id,),
            ).close()
            repo._execute(
                connection,
                "DELETE FROM authoritative_trades WHERE id=?",
                (trade_id,),
            ).close()
            repo._execute(
                connection,
                "DELETE FROM opportunities WHERE id=?",
                (opportunity_id,),
            ).close()
