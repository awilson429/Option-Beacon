import json
import logging
from types import SimpleNamespace

import pytest

from optionbeacon.worker import run as worker
from optionbeacon.worker.database_diagnostics import (
    DatabaseProbeError,
    database_url_metadata,
    log_sanitized_traceback,
    probe_postgresql,
)
from trade_repository import TradeRepository
from trade_repository import RepositoryUnavailable


SAFE_URL = (
    "postgresql://railway-user:railway-password@"
    "ep-example-pooler.invalid/neondb?sslmode=require"
)


class FakeCursor:
    def __init__(self, *, fail_at=None):
        self.fail_at = fail_at
        self.executed = None
        self.closed = False

    def execute(self, statement):
        if self.fail_at == "execute":
            detail = "sensitive execute detail"
            raise RuntimeError(detail)
        self.executed = statement

    def fetchone(self):
        if self.fail_at == "fetch":
            detail = "sensitive fetch detail"
            raise RuntimeError(detail)
        return (1,)

    def close(self):
        if self.fail_at == "close":
            detail = "sensitive close detail"
            raise RuntimeError(detail)
        self.closed = True


class FakeConnection:
    def __init__(self, *, fail_at=None):
        self.fail_at = fail_at
        self.cursor_instance = FakeCursor(fail_at=fail_at)
        self.closed = False

    def cursor(self):
        if self.fail_at == "cursor":
            detail = "sensitive cursor detail"
            raise RuntimeError(detail)
        return self.cursor_instance

    def close(self):
        if self.fail_at == "connection_close":
            detail = "sensitive close detail"
            raise RuntimeError(detail)
        self.closed = True


def fake_driver(*, fail_at=None):
    connection = FakeConnection(fail_at=fail_at)

    def connect(_url, **_kwargs):
        if fail_at == "connect":
            detail = "sensitive connection detail"
            raise RuntimeError(detail)
        return connection

    return SimpleNamespace(
        __version__="2.9.10 test",
        connect=connect,
        connection=connection,
    )


def messages(caplog):
    return [json.loads(record.message) for record in caplog.records]


def test_database_url_metadata_is_structural_and_non_reversible():
    record = database_url_metadata(
        SAFE_URL,
        environ={"OPTIONBEACON_REQUIRE_DURABLE_STORAGE": "true"},
    )

    assert record == {
        "event": "database_environment_diagnostics",
        "database_url_configured": True,
        "database_url_length": len(SAFE_URL),
        "detected_scheme": "postgresql",
        "contains_username": True,
        "contains_password": True,
        "contains_host": True,
        "contains_database_name": True,
        "sslmode_present": True,
        "pooler_hostname_detected": True,
        "durable_storage_required": True,
    }
    encoded = json.dumps(record)
    for secret in ("railway-user", "railway-password", "ep-example", "neondb"):
        assert secret not in encoded


def test_database_probe_connects_selects_and_closes(caplog):
    driver = fake_driver()
    with caplog.at_level(logging.INFO):
        result = probe_postgresql(
            SAFE_URL, driver_loader=lambda _name: driver, timeout=3
        )

    events = [record["event"] for record in messages(caplog)]
    assert events == [
        "database_probe_started",
        "database_environment_diagnostics",
        "worker_runtime_diagnostics",
        "database_connection_opened",
        "database_select_one_passed",
        "database_probe_completed",
    ]
    assert driver.connection.cursor_instance.executed == "SELECT 1"
    assert driver.connection.cursor_instance.closed is True
    assert driver.connection.closed is True
    assert result["elapsed_milliseconds"] >= 0


@pytest.mark.parametrize(
    ("failure", "expected_stage"),
    [
        ("connect", "connect"),
        ("cursor", "cursor"),
        ("execute", "execute"),
        ("fetch", "fetch"),
        ("close", "close"),
        ("connection_close", "close"),
    ],
)
def test_database_probe_reports_exact_sanitized_failure_stage(
    failure, expected_stage, caplog
):
    with caplog.at_level(logging.ERROR), pytest.raises(DatabaseProbeError) as caught:
        probe_postgresql(
            SAFE_URL,
            driver_loader=lambda _name: fake_driver(fail_at=failure),
        )

    assert caught.value.stage == expected_stage
    assert "sensitive" not in caplog.text
    failure_record = next(
        record for record in messages(caplog) if record["event"] == "database_probe_failed"
    )
    assert failure_record["stage"] == expected_stage
    assert failure_record["exception_type"] == "RuntimeError"


def test_driver_import_failure_is_sanitized(caplog):
    def broken_loader(_name):
        detail = "sensitive driver path"
        raise ImportError(detail)

    with caplog.at_level(logging.INFO), pytest.raises(DatabaseProbeError) as caught:
        probe_postgresql(SAFE_URL, driver_loader=broken_loader)

    assert caught.value.stage == "driver_import"
    assert "sensitive driver path" not in caplog.text


def test_sanitized_traceback_never_includes_original_exception_message(caplog):
    detail = "postgresql://user:password@private-host/database"
    try:
        raise RuntimeError(detail)
    except RuntimeError as exc:
        with caplog.at_level(logging.ERROR):
            log_sanitized_traceback(
                logging.getLogger("safe-diagnostic-test"),
                {"event": "failed", "message": "Safe failure."},
                exc,
            )

    assert "password" not in caplog.text
    assert "private-host" not in caplog.text
    assert "Safe failure." in caplog.text


def test_repository_reports_schema_operation_boundaries(tmp_path):
    events = []
    TradeRepository(
        tmp_path / "state.db",
        database_url="",
        diagnostic_callback=events.append,
    )

    names = [record["event"] for record in events]
    assert names[0] == "repository_construction_completed"
    assert "repository_connection_ready" in names
    assert "repository_schema_initialization_started" in names
    assert "repository_schema_initialization_completed" in names
    operations = [
        record["operation"]
        for record in events
        if record["event"] == "repository_schema_operation_completed"
    ]
    assert operations == [
        "opportunities",
        "authoritative_trades",
        "scanner_health",
        "scanner_locks",
        "legacy_imports",
    ]


def test_worker_probes_before_repository_initialization(monkeypatch):
    order = []
    repository = SimpleNamespace(backend="postgresql", durable=True)
    monkeypatch.setenv("DATABASE_URL", SAFE_URL)
    monkeypatch.setenv("OPTIONBEACON_ENVIRONMENT", "production")
    monkeypatch.setattr(
        worker, "probe_postgresql", lambda *_args, **_kwargs: order.append("probe")
    )

    def construct(**kwargs):
        assert kwargs["database_url"] == SAFE_URL
        assert callable(kwargs["diagnostic_callback"])
        order.append("repository")
        return repository

    monkeypatch.setattr(worker, "repository_for_runtime", construct)
    monkeypatch.setattr(worker, "run", lambda **_kwargs: order.append("run"))

    assert worker.main(["--max-runs", "0"]) == 0
    assert order == ["probe", "repository", "run"]


def test_worker_reports_exact_repository_schema_operation(monkeypatch, caplog):
    monkeypatch.setenv("DATABASE_URL", SAFE_URL)
    monkeypatch.setenv("OPTIONBEACON_ENVIRONMENT", "production")
    monkeypatch.setattr(worker, "probe_postgresql", lambda *_args, **_kwargs: None)

    def construct(**kwargs):
        callback = kwargs["diagnostic_callback"]
        callback({"event": "repository_connection_ready"})
        callback(
            {
                "event": "repository_schema_operation_started",
                "operation": "scanner_health",
            }
        )
        raise RepositoryUnavailable("Trade repository unavailable: RuntimeError")

    monkeypatch.setattr(worker, "repository_for_runtime", construct)
    with caplog.at_level(logging.ERROR):
        assert worker.main(["--max-runs", "0"]) == 2

    record = next(
        record
        for record in messages(caplog)
        if record["event"] == "worker_configuration_error"
    )
    assert record["startup_stage"] == "repository_initialization"
    assert record["repository_stage"] == "repository_schema_operation_started"
    assert record["repository_operation"] == "scanner_health"
    assert SAFE_URL not in caplog.text
