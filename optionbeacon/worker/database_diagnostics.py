"""Sanitized PostgreSQL startup diagnostics for the production worker."""

from __future__ import annotations

import importlib
import json
import logging
import os
import platform
import time
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from trade_repository import database_connect_timeout_seconds


EXPECTED_DRIVER = "psycopg2"


@dataclass(frozen=True)
class DatabaseProbeError(RuntimeError):
    stage: str
    cause_type: str
    safe_message: str
    sqlstate: str | None = None

    def __str__(self):
        return self.safe_message


class SanitizedDiagnosticError(RuntimeError):
    """Synthetic exception used to emit a traceback without secret values."""


def durable_storage_required(environ) -> bool:
    return (
        str(environ.get("OPTIONBEACON_REQUIRE_DURABLE_STORAGE", "")).strip().lower()
        in {"1", "true", "yes"}
        or str(environ.get("OPTIONBEACON_ENVIRONMENT", "")).strip().lower()
        == "production"
    )


def database_url_metadata(database_url: str | None, *, environ=None) -> dict:
    """Describe URL structure without returning any reversible component."""
    value = str(database_url or "").strip()
    parsed = urlsplit(value) if value else None
    scheme = (parsed.scheme or "").lower() if parsed else ""
    query_names = set(parse_qs(parsed.query, keep_blank_values=True)) if parsed else set()
    hostname = (parsed.hostname or "") if parsed else ""
    path = parsed.path.lstrip("/") if parsed else ""
    return {
        "event": "database_environment_diagnostics",
        "database_url_configured": bool(value),
        "database_url_length": len(value),
        "detected_scheme": scheme if scheme in {"postgresql", "postgres"} else "unknown",
        "contains_username": bool(parsed and parsed.username),
        "contains_password": bool(parsed and parsed.password),
        "contains_host": bool(hostname),
        "contains_database_name": bool(path),
        "sslmode_present": "sslmode" in query_names,
        "pooler_hostname_detected": "pooler" in hostname.lower(),
        "durable_storage_required": durable_storage_required(
            os.environ if environ is None else environ
        ),
    }


def runtime_dependency_record(driver=None) -> dict:
    """Report the expected runtime without filesystem paths or credentials."""
    return {
        "event": "worker_runtime_diagnostics",
        "python_version": platform.python_version(),
        "expected_driver": EXPECTED_DRIVER,
        "driver_import_succeeded": driver is not None,
        "driver_version": str(getattr(driver, "__version__", "unknown")) if driver else None,
        "driver_connect_api_available": callable(getattr(driver, "connect", None)) if driver else False,
        "expected_requirement": "psycopg2-binary>=2.9.9,<3",
        "repository_class": "trade_repository.TradeRepository",
    }


def safe_probe_message(stage: str) -> str:
    return {
        "parse": "Database URL parsing failed.",
        "driver_import": "PostgreSQL driver import failed.",
        "connect": "PostgreSQL connection could not be opened.",
        "cursor": "PostgreSQL cursor creation failed.",
        "execute": "PostgreSQL SELECT 1 execution failed.",
        "fetch": "PostgreSQL SELECT 1 result could not be read.",
        "close": "PostgreSQL connection cleanup failed.",
    }.get(stage, "PostgreSQL startup probe failed.")


def safe_sqlstate(exc) -> str | None:
    value = getattr(exc, "pgcode", None)
    if not value:
        value = getattr(getattr(exc, "diag", None), "sqlstate", None)
    value = str(value or "").strip().upper()
    return value if 1 <= len(value) <= 5 and value.isalnum() else None


def log_json(logger, level: int, record: dict) -> None:
    logger.log(level, json.dumps(record, sort_keys=True))


def log_sanitized_traceback(logger, record: dict, exc: BaseException) -> None:
    """Log original frames with a synthetic, non-sensitive final exception."""
    root = exc
    seen = set()
    while id(root) not in seen:
        seen.add(id(root))
        nested = root.__cause__ or root.__context__
        if nested is None:
            break
        root = nested
    safe = SanitizedDiagnosticError(record.get("message") or type(exc).__name__)
    logger.error(
        json.dumps(record, sort_keys=True),
        exc_info=(SanitizedDiagnosticError, safe, root.__traceback__),
    )


def _fail(logger, stage, exc, started):
    record = {
        "event": "database_probe_failed",
        "stage": stage,
        "exception_type": type(exc).__name__,
        "message": safe_probe_message(stage),
        "sqlstate": safe_sqlstate(exc),
        "elapsed_milliseconds": round((time.monotonic() - started) * 1000, 1),
    }
    log_sanitized_traceback(logger, record, exc)
    raise DatabaseProbeError(
        stage=stage,
        cause_type=type(exc).__name__,
        safe_message=record["message"],
        sqlstate=record["sqlstate"],
    ) from None


def probe_postgresql(database_url, *, logger=None, driver_loader=None, timeout=None):
    """Import psycopg2, connect, execute SELECT 1, and close safely."""
    logger = logger or logging.getLogger(__name__)
    started = time.monotonic()
    log_json(logger, logging.INFO, {"event": "database_probe_started"})
    try:
        metadata = database_url_metadata(database_url)
    except Exception as exc:
        _fail(logger, "parse", exc, started)
    log_json(logger, logging.INFO, metadata)
    if not metadata["database_url_configured"] or metadata["detected_scheme"] == "unknown":
        _fail(logger, "parse", ValueError("database URL is absent or unsupported"), started)

    try:
        driver = (driver_loader or importlib.import_module)(EXPECTED_DRIVER)
        if not callable(getattr(driver, "connect", None)):
            raise AttributeError("driver connect API unavailable")
    except Exception as exc:
        log_json(logger, logging.INFO, runtime_dependency_record(None))
        _fail(logger, "driver_import", exc, started)
    log_json(logger, logging.INFO, runtime_dependency_record(driver))

    parsed = urlsplit(str(database_url).strip())
    kwargs = {"connect_timeout": database_connect_timeout_seconds(timeout)}
    if "sslmode" not in parse_qs(parsed.query, keep_blank_values=True):
        kwargs["sslmode"] = "require"
    connection = None
    cursor = None
    try:
        try:
            connection = driver.connect(database_url, **kwargs)
        except Exception as exc:
            _fail(logger, "connect", exc, started)
        log_json(logger, logging.INFO, {"event": "database_connection_opened"})
        try:
            cursor = connection.cursor()
        except Exception as exc:
            _fail(logger, "cursor", exc, started)
        try:
            cursor.execute("SELECT 1")
        except Exception as exc:
            _fail(logger, "execute", exc, started)
        try:
            row = cursor.fetchone()
            if not row or row[0] != 1:
                raise ValueError("unexpected SELECT 1 result")
        except Exception as exc:
            _fail(logger, "fetch", exc, started)
        log_json(logger, logging.INFO, {"event": "database_select_one_passed"})
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception as exc:
                _fail(logger, "close", exc, started)
        if connection is not None:
            try:
                connection.close()
            except Exception as exc:
                _fail(logger, "close", exc, started)
    record = {
        "event": "database_probe_completed",
        "elapsed_milliseconds": round((time.monotonic() - started) * 1000, 1),
    }
    log_json(logger, logging.INFO, record)
    return record
