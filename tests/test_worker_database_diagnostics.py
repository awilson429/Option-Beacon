import json
import logging
import sys
from types import SimpleNamespace

import pytest

from optionbeacon.worker import run as worker
from optionbeacon.worker.database_diagnostics import (
    DatabaseProbeError,
    SanitizedDiagnosticError,
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


class OperationalError(RuntimeError):
    pass


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


def fake_driver(*, fail_at=None, connect_error=None, connect_exception=RuntimeError):
    connection = FakeConnection(fail_at=fail_at)

    def connect(_url, **_kwargs):
        if fail_at == "connect":
            detail = connect_error or "connection refused"
            raise connect_exception(detail)
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
    for secret in (
        SAFE_URL,
        "railway-user",
        "railway-password",
        "ep-example",
        "neondb",
    ):
        assert secret not in caplog.text
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
    original = next(
        record
        for record in messages(caplog)
        if record["event"] == "database_original_failure"
    )
    assert original["original_exception_type"] == "ImportError"
    assert original["sanitized_original_exception_message"] == "sensitive driver path"


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


@pytest.mark.parametrize(
    ("category", "error_message"),
    [
        (
            "Name or service not known",
            'could not translate host name "ep-example-pooler.invalid" to address: '
            "Name or service not known",
        ),
        (
            "connection timeout expired",
            'connection to server at "ep-example-pooler.invalid" failed: '
            "connection timeout expired",
        ),
        (
            "Connection refused",
            'connection to server at "ep-example-pooler.invalid" failed: '
            "Connection refused",
        ),
        (
            "SSL SYSCALL error",
            'connection to server at "ep-example-pooler.invalid" failed: '
            "SSL SYSCALL error: EOF detected",
        ),
        (
            "server closed the connection unexpectedly",
            "server closed the connection unexpectedly",
        ),
        (
            "channel binding required",
            "channel binding required, but server did not offer it",
        ),
        (
            "password authentication failed",
            'password authentication failed for user "railway-user"',
        ),
        ("does not exist", 'database "neondb" does not exist'),
        ("project exceeded quota", "project exceeded quota"),
        (
            "no pg_hba.conf entry",
            'no pg_hba.conf entry for host "ep-example-pooler.invalid", '
            'user "railway-user", database "neondb", SSL on',
        ),
        (
            "Network is unreachable",
            'connection to server at "ep-example-pooler.invalid" '
            "(2600:1f18::1), port 5432 failed: Network is unreachable",
        ),
        ("TLS handshake failed", "TLS handshake failed"),
        ("other libpq connection error", 'other libpq connection error'),
    ],
)
def test_original_postgres_error_category_is_preserved_and_secrets_redacted(
    category, error_message, caplog
):
    detail = (
        f"{error_message}\n"
        f"connection string: {SAFE_URL}\n"
        "password=railway-password user=railway-user host=ep-example-pooler.invalid "
        "dbname=neondb"
    )
    driver = fake_driver(
        fail_at="connect",
        connect_error=detail,
        connect_exception=OperationalError,
    )

    with caplog.at_level(logging.INFO), pytest.raises(DatabaseProbeError):
        probe_postgresql(SAFE_URL, driver_loader=lambda _name: driver)

    original = next(
        record
        for record in messages(caplog)
        if record["event"] == "database_original_failure"
    )
    assert original["original_exception_type"] == "OperationalError"
    assert category in original["sanitized_original_exception_message"]
    assert category in original["sanitized_original_traceback"]
    assert original["stage"] == "connect"
    assert original["python_version"] == sys.version
    assert original["psycopg2_version"] == "2.9.10 test"
    for secret in (
        SAFE_URL,
        "railway-user",
        "railway-password",
        "ep-example-pooler.invalid",
        "ep-example",
        "neondb",
    ):
        assert secret not in caplog.text
    wrapped = next(
        record
        for record in caplog.records
        if '"event": "database_probe_failed"' in record.message
    )
    wrapped_payload = json.loads(wrapped.message)
    assert category in wrapped_payload["message"]
    assert category in str(wrapped.exc_info[1])
    assert wrapped.exc_info[0] is SanitizedDiagnosticError


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
        "opportunity_context",
        "intelligence_setup_snapshots",
        "intelligence_outcome_labels",
        "intelligence_shadow_events",
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
