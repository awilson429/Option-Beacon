import json
import os
import sys
import threading
import time
import traceback
from types import SimpleNamespace
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from optionbeacon.worker import run as worker
from optionbeacon.worker import healthcheck as healthcheck_worker
from optionbeacon.worker import scan_once as scan_once_worker
from optionbeacon.worker.healthcheck import check_health, main as healthcheck_main
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


def test_worker_repository_configuration_uses_environment_only(monkeypatch):
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

    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://configured-without-printing"
    )
    monkeypatch.setattr(trade_state_service, "TradeRepository", FakeRepository)
    repository_for_runtime(branch="main")

    assert captured["database_url"].startswith("postgresql://")
    assert captured["require_durable"] is True


def test_scan_once_returns_quickly_when_durable_storage_missing(
    monkeypatch, tmp_path
):
    class SecretsThatMustNotBeRead(dict):
        def get(self, *_args, **_kwargs):
            raise AssertionError("CLI attempted to read Streamlit secrets")

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("OPTIONBEACON_REQUIRE_DURABLE_STORAGE", "true")
    monkeypatch.setenv("OPTIONBEACON_ENVIRONMENT", "production")
    monkeypatch.setitem(
        sys.modules,
        "streamlit",
        SimpleNamespace(secrets=SecretsThatMustNotBeRead()),
    )
    monkeypatch.chdir(tmp_path)

    started = time.monotonic()
    assert scan_once_main() == 1
    assert time.monotonic() - started < 5
    assert not (tmp_path / "optionbeacon_state.db").exists()


def test_worker_factory_does_not_read_streamlit_database_secret(monkeypatch, tmp_path):
    class SecretsThatMustNotBeRead(dict):
        def get(self, *_args, **_kwargs):
            raise AssertionError("CLI attempted to read Streamlit secrets")

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("OPTIONBEACON_REQUIRE_DURABLE_STORAGE", "true")
    monkeypatch.setitem(
        sys.modules,
        "streamlit",
        SimpleNamespace(
            secrets=SecretsThatMustNotBeRead(
                {"DATABASE_URL": "postgresql://must-not-be-used"}
            )
        ),
    )

    with pytest.raises(RepositoryUnavailable):
        repository_for_runtime(db_file=tmp_path / "must-not-exist.db")
    assert not (tmp_path / "must-not-exist.db").exists()


def test_all_cli_entrypoints_ignore_streamlit_database_secret(monkeypatch, tmp_path):
    class SecretsThatMustNotBeRead(dict):
        def get(self, *_args, **_kwargs):
            raise AssertionError("CLI attempted to read Streamlit secrets")

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("OPTIONBEACON_REQUIRE_DURABLE_STORAGE", "true")
    monkeypatch.setenv("OPTIONBEACON_ENVIRONMENT", "production")
    monkeypatch.setitem(
        sys.modules,
        "streamlit",
        SimpleNamespace(
            secrets=SecretsThatMustNotBeRead(
                {"DATABASE_URL": "postgresql://must-not-be-used"}
            )
        ),
    )
    monkeypatch.chdir(tmp_path)

    started = time.monotonic()
    assert scan_once_main() == 1
    assert worker.main(["--max-runs", "0"]) == 2
    assert healthcheck_main() == 2
    assert time.monotonic() - started < 5
    assert not (tmp_path / "optionbeacon_state.db").exists()


def test_dashboard_can_explicitly_resolve_streamlit_database_url(monkeypatch):
    from dashboard_storage_config import dashboard_database_url

    monkeypatch.delenv("DATABASE_URL", raising=False)
    fake_streamlit = SimpleNamespace(
        secrets={"DATABASE_URL": "postgresql://dashboard-explicit"}
    )

    assert (
        dashboard_database_url(st_module=fake_streamlit)
        == "postgresql://dashboard-explicit"
    )
    source = open("app.py", encoding="utf-8").read()
    assert "database_url=dashboard_database_url()" in source


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


def test_postgresql_connection_uses_bounded_timeout_and_sanitized_error(
    monkeypatch, tmp_path
):
    import psycopg2

    captured = {}
    secret_url = "postgresql://user:super-secret@unreachable.invalid/db"

    def fail_connect(_url, **kwargs):
        captured.update(kwargs)
        raise psycopg2.OperationalError("connection failed")

    monkeypatch.setattr(psycopg2, "connect", fail_connect)
    monkeypatch.setenv("OPTIONBEACON_DB_CONNECT_TIMEOUT_SECONDS", "3")
    started = time.monotonic()
    with pytest.raises(RepositoryUnavailable) as error:
        TradeRepository(
            tmp_path / "no-fallback.db",
            database_url=secret_url,
            require_durable=True,
        )

    assert time.monotonic() - started < 5
    assert captured["connect_timeout"] == 3
    assert secret_url not in str(error.value)
    assert "super-secret" not in str(error.value)
    rendered_traceback = "".join(
        traceback.format_exception(
            type(error.value),
            error.value,
            error.value.__traceback__,
        )
    )
    assert secret_url not in rendered_traceback
    assert "super-secret" not in rendered_traceback
    assert not (tmp_path / "no-fallback.db").exists()


@pytest.mark.parametrize("value", ["", "zero", "0", "61", "1.5"])
def test_invalid_database_timeout_fails_before_connection(
    monkeypatch, tmp_path, value
):
    import psycopg2

    attempted = False

    def unexpected_connect(*_args, **_kwargs):
        nonlocal attempted
        attempted = True

    monkeypatch.setattr(psycopg2, "connect", unexpected_connect)
    monkeypatch.setenv("OPTIONBEACON_DB_CONNECT_TIMEOUT_SECONDS", value)

    with pytest.raises(RepositoryUnavailable) as error:
        TradeRepository(
            tmp_path / "no-fallback.db",
            database_url="postgresql://configured",
            require_durable=True,
        )

    assert attempted is False
    assert "DATABASE_URL" not in str(error.value)
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


def test_worker_configuration_error_logs_root_cause_and_traceback(
    monkeypatch, caplog
):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("OPTIONBEACON_ENVIRONMENT", "production")
    monkeypatch.setattr(
        worker,
        "repository_for_runtime",
        lambda **_kwargs: (_ for _ in ()).throw(
            RepositoryUnavailable(
                "Durable trade storage is required but DATABASE_URL is not configured."
            )
        ),
    )

    with caplog.at_level("ERROR"):
        assert worker.main(["--max-runs", "0"]) == 2

    record = next(
        item for item in caplog.records if "worker_configuration_error" in item.message
    )
    payload = json.loads(record.message)
    assert payload["error"] == "RepositoryUnavailable"
    assert payload["message"] == (
        "Durable trade storage is required but DATABASE_URL is not configured."
    )
    assert payload["database_url_configured"] is False
    assert payload["durable_storage_required"] is True
    assert record.exc_info is not None


def test_worker_configuration_error_never_logs_database_credentials(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://private-user:private-password@db.invalid/app"
    )
    error = RepositoryUnavailable("Trade repository unavailable: OperationalError")

    encoded = json.dumps(worker.configuration_error_record(error), sort_keys=True)

    assert "private-user" not in encoded
    assert "private-password" not in encoded
    assert "db.invalid" not in encoded
    assert '"database_url_configured": true' in encoded


def test_worker_diagnostic_entrypoints_log_repository_tracebacks(
    monkeypatch, caplog
):
    def unavailable():
        raise RepositoryUnavailable(
            "Durable trade storage is required but DATABASE_URL is not configured."
        )

    monkeypatch.setattr(scan_once_worker, "repository_for_runtime", unavailable)
    monkeypatch.setattr(healthcheck_worker, "repository_for_runtime", unavailable)

    with caplog.at_level("ERROR"):
        assert scan_once_worker.main() == 1
        code, result = healthcheck_worker.check_health()

    assert code == 2
    assert result["error"] == "RepositoryUnavailable"
    matching = [
        record
        for record in caplog.records
        if "repository initialization failed" in record.message
    ]
    assert len(matching) == 2
    assert all(record.exc_info is not None for record in matching)


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
