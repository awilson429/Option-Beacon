"""Authoritative, transactional opportunity/trade/scanner-health repository."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo


DEFAULT_REPOSITORY_FILE = "optionbeacon_state.db"
DEFAULT_SCANNER_ID = "optionbeacon-scanner"
DEFAULT_DB_CONNECT_TIMEOUT_SECONDS = 10
MIN_DB_CONNECT_TIMEOUT_SECONDS = 1
MAX_DB_CONNECT_TIMEOUT_SECONDS = 60
UTC = timezone.utc
LOGGER = logging.getLogger(__name__)


def verbose_storage_diagnostics_enabled(value=None) -> bool:
    raw = (
        os.getenv("OPTIONBEACON_VERBOSE_STORAGE_DIAGNOSTICS", "false")
        if value is None
        else value
    )
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}


def query_egress_diagnostics_enabled(value=None) -> bool:
    raw = os.getenv("OPTIONBEACON_QUERY_EGRESS_DIAGNOSTICS", "false") if value is None else value
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}


class RepositoryUnavailable(RuntimeError):
    """Raised when authoritative storage cannot be reached."""


REQUIRED_EVENT_READ_API = ("list_trade_event_summaries", "count_trade_events")


def repository_event_api_status(repository) -> dict:
    """Describe the real runtime repository contract without touching storage."""
    missing = [name for name in REQUIRED_EVENT_READ_API if not callable(getattr(repository, name, None))]
    return {"available": not missing, "missing": missing,
            "repository_class": type(repository).__name__}


def projected_trade_event_summaries(repository, *, limit=500, event_type=None,
                                    event_types=None, start_at=None, end_at=None):
    """Compatibility-safe projected event read for mixed deployment restarts.

    A coherent deployment delegates to the class API. The fallback intentionally
    repeats the same bounded explicit-column projection and never restores the
    legacy full-row event query.
    """
    method = getattr(repository, "list_trade_event_summaries", None)
    if callable(method):
        options = {
            "limit": limit, "event_type": event_type,
            "start_at": start_at, "end_at": end_at,
        }
        if event_types:
            options["event_types"] = event_types
        return method(**options)
    LOGGER.error(json.dumps({
        "event": "trade_repository_event_api_compatibility_fallback",
        **repository_event_api_status(repository),
    }, sort_keys=True))
    query = """SELECT id,trade_id,opportunity_id,symbol,direction,setup,event_type,
        event_timestamp,underlying_price,entry_price,exit_price,current_return,
        realized_return,exit_reason,rule_score,description
        FROM authoritative_trade_events"""
    clauses, params = [], []
    if event_type:
        clauses.append("event_type=?"); params.append(str(event_type))
    if event_types:
        values = tuple(str(value) for value in event_types)
        clauses.append(f"event_type IN ({','.join('?' for _ in values)})")
        params.extend(values)
    if start_at is not None:
        clauses.append("event_timestamp>=?"); params.append(utc_iso(start_at))
    if end_at is not None:
        clauses.append("event_timestamp<=?"); params.append(utc_iso(end_at))
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY event_timestamp DESC,id DESC LIMIT ?"
    params.append(int(limit))
    with repository.connection() as connection:
        rows = repository._fetchall(connection, query, tuple(params))
    return [repository._decode_trade_event(row) for row in rows]


def authoritative_session_bounds(session_date, timezone_name="America/New_York"):
    """Return one local calendar session as an exclusive UTC interval."""
    value = session_date if isinstance(session_date, date) else date.fromisoformat(str(session_date))
    local = ZoneInfo(timezone_name)
    start = datetime.combine(value, datetime.min.time(), tzinfo=local)
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


def authoritative_session_event_summaries(repository, session_date):
    """Read lifecycle events for entries originating in one Eastern calendar day."""
    start_at, end_exclusive = authoritative_session_bounds(session_date)
    end_inclusive = end_exclusive - timedelta(microseconds=1)
    count = repository.count_trade_events(
        event_type="TRADE_ENTERED", start_at=start_at, end_at=end_inclusive
    )
    if not count:
        return []
    entries = projected_trade_event_summaries(
        repository, limit=count, event_type="TRADE_ENTERED",
        start_at=start_at, end_at=end_inclusive,
    )
    identities = {
        str(event.get("opportunity_id") or event.get("trade_id"))
        for event in entries
        if event.get("opportunity_id") or event.get("trade_id")
    }
    lifecycle = repository.trade_event_summaries_for_opportunity_ids(identities)
    lifecycle_ids = {str(event.get("id")) for event in lifecycle if event.get("id")}
    return [*lifecycle, *(event for event in entries if str(event.get("id")) not in lifecycle_ids)]


def authoritative_session_dates(repository, now):
    """Return today and the latest earlier ET date containing an authoritative entry."""
    current = now if isinstance(now, datetime) else datetime.fromisoformat(str(now))
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    today = current.astimezone(ZoneInfo("America/New_York")).date()
    today_start, _ = authoritative_session_bounds(today)
    previous_entry = projected_trade_event_summaries(
        repository, limit=1, event_type="TRADE_ENTERED",
        end_at=today_start - timedelta(microseconds=1),
    )
    previous = (
        parse_utc(previous_entry[0]["event_timestamp"])
        .astimezone(ZoneInfo("America/New_York")).date()
        if previous_entry else None
    )
    return {"today": today, "previous": previous}


def database_connect_timeout_seconds(value=None) -> int:
    raw = (
        os.getenv(
            "OPTIONBEACON_DB_CONNECT_TIMEOUT_SECONDS",
            str(DEFAULT_DB_CONNECT_TIMEOUT_SECONDS),
        )
        if value is None
        else value
    )
    try:
        timeout = int(raw)
    except (TypeError, ValueError) as exc:
        raise RepositoryUnavailable(
            "OPTIONBEACON_DB_CONNECT_TIMEOUT_SECONDS must be an integer "
            f"between {MIN_DB_CONNECT_TIMEOUT_SECONDS} and "
            f"{MAX_DB_CONNECT_TIMEOUT_SECONDS}."
        ) from exc
    if not MIN_DB_CONNECT_TIMEOUT_SECONDS <= timeout <= MAX_DB_CONNECT_TIMEOUT_SECONDS:
        raise RepositoryUnavailable(
            "OPTIONBEACON_DB_CONNECT_TIMEOUT_SECONDS must be an integer "
            f"between {MIN_DB_CONNECT_TIMEOUT_SECONDS} and "
            f"{MAX_DB_CONNECT_TIMEOUT_SECONDS}."
        )
    return timeout


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_iso(value: datetime | str | None = None) -> str:
    value = value or utc_now()
    if not isinstance(value, datetime):
        value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def parse_utc(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(
        str(value).replace("Z", "+00:00")
    )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def opportunity_idempotency_key(
    *,
    symbol: str,
    direction: str,
    playbook: str,
    signal_timestamp: datetime | str,
    source_version: str,
) -> str:
    identity = {
        "symbol": str(symbol).upper(),
        "direction": str(direction),
        "playbook": str(playbook),
        "signal_timestamp": utc_iso(signal_timestamp),
        "source_version": str(source_version),
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class TradeRepository:
    """SQLite locally and PostgreSQL through DATABASE_URL in production."""

    def __init__(
        self,
        db_file: str | Path = DEFAULT_REPOSITORY_FILE,
        *,
        database_url: str | None = None,
        require_durable: bool = False,
        connect_timeout_seconds: int | None = None,
        diagnostic_callback=None,
        verbose_storage_diagnostics=None,
    ):
        self.db_file = str(db_file)
        self.database_url = (
            database_url
            if database_url is not None
            else os.getenv("DATABASE_URL", "").strip()
        )
        self.backend = "postgresql" if self.database_url else "sqlite"
        self.durable = self.backend == "postgresql"
        self.require_durable = require_durable
        self.diagnostic_callback = diagnostic_callback
        self.verbose_storage_diagnostics = verbose_storage_diagnostics_enabled(
            verbose_storage_diagnostics
        )
        self._connection_ready_logged = False
        if require_durable and not self.durable:
            raise RepositoryUnavailable(
                "Durable trade storage is required but DATABASE_URL is not configured."
            )
        self.connect_timeout_seconds = (
            database_connect_timeout_seconds(connect_timeout_seconds)
            if self.durable
            else None
        )
        self._diagnostic("repository_construction_completed", backend=self.backend)
        self.initialize()

    def _diagnostic(self, event: str, **fields):
        if event == "repository_connection_ready":
            if (
                self._connection_ready_logged
                and not self.verbose_storage_diagnostics
            ):
                return
            self._connection_ready_logged = True
        if self.diagnostic_callback is not None:
            self.diagnostic_callback({"event": event, **fields})

    @contextmanager
    def connection(self):
        try:
            if self.backend == "postgresql":
                import psycopg2
                from psycopg2.extras import RealDictCursor

                kwargs = {
                    "cursor_factory": RealDictCursor,
                    "connect_timeout": self.connect_timeout_seconds,
                }
                if "sslmode=" not in self.database_url:
                    kwargs["sslmode"] = "require"
                connection = psycopg2.connect(self.database_url, **kwargs)
            else:
                Path(self.db_file).parent.mkdir(parents=True, exist_ok=True)
                connection = sqlite3.connect(
                    self.db_file,
                    timeout=30,
                    isolation_level=None,
                )
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA journal_mode=WAL")
            self._diagnostic("repository_connection_ready", backend=self.backend)
            yield connection
            connection.commit()
        except RepositoryUnavailable:
            raise
        except Exception as exc:
            raise RepositoryUnavailable(
                f"Trade repository unavailable: {type(exc).__name__}"
            ) from exc
        finally:
            if "connection" in locals():
                connection.close()

    def _sql(self, query: str) -> str:
        return query.replace("?", "%s") if self.backend == "postgresql" else query

    def _execute(self, connection, query, params=()):
        cursor = connection.cursor()
        cursor.execute(self._sql(query), params)
        return cursor

    def _fetchone(self, connection, query, params=()):
        cursor = self._execute(connection, query, params)
        row = cursor.fetchone()
        cursor.close()
        return dict(row) if row else None

    def _fetchall(self, connection, query, params=()):
        started = time.perf_counter()
        cursor = self._execute(connection, query, params)
        rows = [dict(row) for row in cursor.fetchall()]
        cursor.close()
        if query_egress_diagnostics_enabled():
            normalized = " ".join(str(query).split())
            LOGGER.info(json.dumps({
                "event": "database_read_result",
                "query_fingerprint": hashlib.sha256(normalized.encode()).hexdigest()[:12],
                "operation": normalized.split(" ", 1)[0].upper() if normalized else "UNKNOWN",
                "rows_returned": len(rows),
                "approx_result_bytes": sum(
                    len(str(key)) + len(str(value)) for row in rows for key, value in row.items()
                ),
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            }, sort_keys=True))
        return rows

    def _table_columns(self, connection, table_name):
        if self.backend == "postgresql":
            rows = self._fetchall(
                connection,
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema=current_schema() AND table_name=?",
                (table_name,),
            )
            return {row["column_name"] for row in rows}
        cursor = self._execute(connection, f"PRAGMA table_info({table_name})")
        rows = cursor.fetchall()
        cursor.close()
        return {row["name"] for row in rows}

    def initialize(self):
        self._diagnostic("repository_schema_initialization_started")
        with self.connection() as connection:
            text_id = "TEXT PRIMARY KEY"
            self._diagnostic(
                "repository_schema_operation_started", operation="opportunities"
            )
            self._execute(
                connection,
                f"""
                CREATE TABLE IF NOT EXISTS opportunities (
                    id {text_id},
                    idempotency_key TEXT NOT NULL UNIQUE,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    playbook TEXT NOT NULL,
                    signal_timestamp TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    state TEXT NOT NULL,
                    confidence REAL,
                    entry_reference REAL,
                    stop_reference REAL,
                    target_1 REAL,
                    target_2 REAL,
                    target_3 REAL,
                    evidence_json TEXT,
                    metadata_json TEXT,
                    source_version TEXT NOT NULL
                )
                """,
            ).close()
            self._diagnostic(
                "repository_schema_operation_completed", operation="opportunities"
            )
            self._diagnostic(
                "repository_schema_operation_started",
                operation="authoritative_trades",
            )
            self._execute(
                connection,
                f"""
                CREATE TABLE IF NOT EXISTS authoritative_trades (
                    id {text_id},
                    opportunity_id TEXT NOT NULL UNIQUE,
                    opened_at TEXT NOT NULL,
                    closed_at TEXT,
                    status TEXT NOT NULL,
                    entry_price REAL,
                    last_price REAL,
                    stop_price REAL,
                    target_1 REAL,
                    target_2 REAL,
                    target_3 REAL,
                    exit_price REAL,
                    exit_reason TEXT,
                    realized_result REAL,
                    metadata_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(opportunity_id) REFERENCES opportunities(id)
                )
                """,
            ).close()
            self._diagnostic(
                "repository_schema_operation_completed",
                operation="authoritative_trades",
            )
            self._execute(
                connection,
                f"""
                CREATE TABLE IF NOT EXISTS authoritative_trade_events (
                    id {text_id},
                    dedup_key TEXT NOT NULL UNIQUE,
                    trade_id TEXT,
                    opportunity_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    direction TEXT,
                    setup TEXT,
                    event_type TEXT NOT NULL,
                    event_timestamp TEXT NOT NULL,
                    underlying_price REAL,
                    entry_price REAL,
                    exit_price REAL,
                    current_return REAL,
                    realized_return REAL,
                    exit_reason TEXT,
                    rule_score REAL,
                    description TEXT NOT NULL,
                    metadata_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(opportunity_id) REFERENCES opportunities(id)
                )
                """,
            ).close()
            self._execute(
                connection,
                "CREATE INDEX IF NOT EXISTS idx_trade_events_timestamp "
                "ON authoritative_trade_events(event_timestamp DESC)",
            ).close()
            self._diagnostic(
                "repository_schema_operation_started", operation="scanner_health"
            )
            self._execute(
                connection,
                """
                CREATE TABLE IF NOT EXISTS scanner_health (
                    scanner_id TEXT PRIMARY KEY,
                    last_started_at TEXT,
                    last_completed_at TEXT,
                    last_success_at TEXT,
                    last_error_at TEXT,
                    last_error_message TEXT,
                    last_symbols_processed INTEGER,
                    scan_duration REAL,
                    code_version TEXT,
                    market_data_state TEXT,
                    current_run_number INTEGER,
                    current_symbols_attempted INTEGER,
                    current_symbol_count INTEGER,
                    current_results INTEGER,
                    current_failures INTEGER,
                    progress_updated_at TEXT,
                    current_owner_id TEXT,
                    updated_at TEXT NOT NULL
                )
                """,
            ).close()
            existing_health_columns = self._table_columns(connection, "scanner_health")
            for column, column_type in {
                "current_run_number": "INTEGER",
                "current_symbols_attempted": "INTEGER",
                "current_symbol_count": "INTEGER",
                "current_results": "INTEGER",
                "current_failures": "INTEGER",
                "progress_updated_at": "TEXT",
                "current_owner_id": "TEXT",
            }.items():
                if self.backend == "postgresql":
                    self._execute(
                        connection,
                        f"ALTER TABLE scanner_health ADD COLUMN IF NOT EXISTS {column} {column_type}",
                    ).close()
                elif column not in existing_health_columns:
                    self._execute(
                        connection,
                        f"ALTER TABLE scanner_health ADD COLUMN {column} {column_type}",
                    ).close()
            self._diagnostic(
                "repository_schema_operation_completed", operation="scanner_health"
            )
            self._diagnostic(
                "repository_schema_operation_started", operation="scanner_locks"
            )
            self._execute(
                connection,
                """
                CREATE TABLE IF NOT EXISTS scanner_locks (
                    scanner_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    acquired_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
                """,
            ).close()
            self._diagnostic(
                "repository_schema_operation_completed", operation="scanner_locks"
            )
            self._diagnostic(
                "repository_schema_operation_started", operation="legacy_imports"
            )
            self._execute(
                connection,
                """
                CREATE TABLE IF NOT EXISTS legacy_imports (
                    source_path TEXT NOT NULL,
                    source_fingerprint TEXT NOT NULL,
                    source_row TEXT NOT NULL,
                    imported_at TEXT NOT NULL,
                    opportunity_id TEXT,
                    PRIMARY KEY(source_fingerprint, source_row)
                )
                """,
            ).close()
            self._diagnostic(
                "repository_schema_operation_completed", operation="legacy_imports"
            )
            for operation, ddl in (
                (
                    "opportunity_context",
                    f"""
                    CREATE TABLE IF NOT EXISTS opportunity_context (
                        opportunity_id {text_id},
                        context_json TEXT NOT NULL,
                        schema_version INTEGER NOT NULL,
                        captured_at TEXT NOT NULL,
                        eastern_session TEXT NOT NULL,
                        experiment_scope TEXT NOT NULL,
                        FOREIGN KEY(opportunity_id) REFERENCES opportunities(id)
                    )
                    """,
                ),
                (
                    "intelligence_setup_snapshots",
                    f"""
                    CREATE TABLE IF NOT EXISTS intelligence_setup_snapshots (
                        opportunity_id {text_id},
                        snapshot_json TEXT NOT NULL,
                        schema_version INTEGER NOT NULL,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY(opportunity_id) REFERENCES opportunities(id)
                    )
                    """,
                ),
                (
                    "intelligence_outcome_labels",
                    f"""
                    CREATE TABLE IF NOT EXISTS intelligence_outcome_labels (
                        opportunity_id {text_id},
                        outcome_json TEXT NOT NULL,
                        schema_version INTEGER NOT NULL,
                        updated_at TEXT NOT NULL,
                        FOREIGN KEY(opportunity_id) REFERENCES opportunities(id)
                    )
                    """,
                ),
                (
                    "intelligence_shadow_events",
                    f"""
                    CREATE TABLE IF NOT EXISTS intelligence_shadow_events (
                        id {text_id},
                        opportunity_id TEXT,
                        event_type TEXT NOT NULL,
                        model_version TEXT,
                        payload_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY(opportunity_id) REFERENCES opportunities(id)
                    )
                    """,
                ),
            ):
                self._diagnostic("repository_schema_operation_started", operation=operation)
                self._execute(connection, ddl).close()
                self._diagnostic("repository_schema_operation_completed", operation=operation)
        self._diagnostic("repository_schema_initialization_completed")

    def create_opportunity(
        self,
        *,
        symbol,
        direction,
        playbook,
        signal_timestamp,
        source_version,
        idempotency_key=None,
        state="CANDIDATE",
        confidence=None,
        entry_reference=None,
        stop_reference=None,
        target_1=None,
        target_2=None,
        target_3=None,
        evidence=None,
        metadata=None,
        opportunity_id=None,
    ) -> dict:
        key = idempotency_key or opportunity_idempotency_key(
            symbol=symbol,
            direction=direction,
            playbook=playbook,
            signal_timestamp=signal_timestamp,
            source_version=source_version,
        )
        existing = self.get_opportunity(idempotency_key=key)
        if existing:
            return existing
        created = utc_iso()
        identifier = opportunity_id or uuid4().hex
        with self.connection() as connection:
            try:
                self._execute(
                    connection,
                    """
                    INSERT INTO opportunities (
                        id,idempotency_key,symbol,direction,playbook,
                        signal_timestamp,created_at,updated_at,state,confidence,
                        entry_reference,stop_reference,target_1,target_2,target_3,
                        evidence_json,metadata_json,source_version
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        identifier,
                        key,
                        str(symbol).upper(),
                        direction,
                        playbook,
                        utc_iso(signal_timestamp),
                        created,
                        created,
                        state,
                        confidence,
                        entry_reference,
                        stop_reference,
                        target_1,
                        target_2,
                        target_3,
                        json.dumps(evidence or {}, sort_keys=True),
                        json.dumps(metadata or {}, sort_keys=True),
                        source_version,
                    ),
                ).close()
            except Exception:
                existing = self.get_opportunity(idempotency_key=key)
                if existing:
                    return existing
                raise
        return self.get_opportunity(opportunity_id=identifier)

    def get_opportunity(
        self, opportunity_id: str | None = None, *, idempotency_key=None
    ) -> dict | None:
        if not opportunity_id and not idempotency_key:
            raise ValueError("opportunity_id or idempotency_key is required")
        column, value = (
            ("idempotency_key", idempotency_key)
            if idempotency_key
            else ("id", opportunity_id)
        )
        with self.connection() as connection:
            return self._decode(
                self._fetchone(
                    connection, f"SELECT * FROM opportunities WHERE {column}=?", (value,)
                )
            )

    def list_opportunities(self, *, state=None, limit=500) -> list[dict]:
        query = "SELECT * FROM opportunities"
        params = []
        if state:
            query += " WHERE state=?"
            params.append(state)
        query += " ORDER BY signal_timestamp DESC, id DESC LIMIT ?"
        params.append(int(limit))
        with self.connection() as connection:
            return [
                self._decode(row)
                for row in self._fetchall(connection, query, params)
            ]

    def update_opportunity(self, opportunity_id, **changes) -> dict | None:
        allowed = {
            "state",
            "confidence",
            "entry_reference",
            "stop_reference",
            "target_1",
            "target_2",
            "target_3",
            "evidence_json",
            "metadata_json",
        }
        values = {
            key: (
                json.dumps(value or {}, sort_keys=True)
                if key in {"evidence_json", "metadata_json"}
                else value
            )
            for key, value in changes.items()
            if key in allowed
        }
        if not values:
            return self.get_opportunity(opportunity_id)
        values["updated_at"] = utc_iso()
        assignments = ",".join(f"{key}=?" for key in values)
        with self.connection() as connection:
            self._execute(
                connection,
                f"UPDATE opportunities SET {assignments} WHERE id=?",
                (*values.values(), opportunity_id),
            ).close()
        return self.get_opportunity(opportunity_id)

    def open_trade(
        self,
        opportunity_id,
        *,
        opened_at,
        entry_price,
        stop_price=None,
        target_1=None,
        target_2=None,
        target_3=None,
        last_price=None,
        metadata=None,
        trade_id=None,
    ) -> dict:
        existing = self.get_trade(opportunity_id=opportunity_id)
        if existing:
            return existing
        now = utc_iso()
        identifier = trade_id or uuid4().hex
        with self.connection() as connection:
            try:
                self._execute(
                    connection,
                    """
                    INSERT INTO authoritative_trades (
                        id,opportunity_id,opened_at,status,entry_price,last_price,
                        stop_price,target_1,target_2,target_3,metadata_json,
                        created_at,updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        identifier,
                        opportunity_id,
                        utc_iso(opened_at),
                        "OPEN",
                        entry_price,
                        last_price,
                        stop_price,
                        target_1,
                        target_2,
                        target_3,
                        json.dumps(metadata or {}, sort_keys=True),
                        now,
                        now,
                    ),
                ).close()
                self._execute(
                    connection,
                    "UPDATE opportunities SET state='OPEN',updated_at=? WHERE id=?",
                    (now, opportunity_id),
                ).close()
            except Exception:
                existing = self.get_trade(opportunity_id=opportunity_id)
                if existing:
                    return existing
                raise
        self._diagnostic(
            "trade_opened",
            trade_id=identifier,
            opportunity_id=opportunity_id,
        )
        return self.get_trade(trade_id=identifier)

    def get_trade(self, trade_id=None, *, opportunity_id=None) -> dict | None:
        column, value = (
            ("opportunity_id", opportunity_id)
            if opportunity_id
            else ("id", trade_id)
        )
        if value is None:
            raise ValueError("trade_id or opportunity_id is required")
        with self.connection() as connection:
            return self._decode(
                self._fetchone(
                    connection,
                    f"SELECT * FROM authoritative_trades WHERE {column}=?",
                    (value,),
                )
            )

    def update_trade(self, trade_id, **changes) -> dict | None:
        allowed = {"last_price", "stop_price", "metadata_json"}
        values = {
            key: (
                json.dumps(value or {}, sort_keys=True)
                if key == "metadata_json"
                else value
            )
            for key, value in changes.items()
            if key in allowed
        }
        if not values:
            return self.get_trade(trade_id=trade_id)
        values["updated_at"] = utc_iso()
        with self.connection() as connection:
            self._execute(
                connection,
                "UPDATE authoritative_trades SET "
                + ",".join(f"{key}=?" for key in values)
                + " WHERE id=?",
                (*values.values(), trade_id),
            ).close()
        self._diagnostic("trade_updated", trade_id=trade_id)
        return self.get_trade(trade_id=trade_id)

    def close_trade(
        self,
        trade_id,
        *,
        closed_at,
        exit_price=None,
        exit_reason=None,
        realized_result=None,
        metadata=None,
    ) -> dict | None:
        trade = self.get_trade(trade_id=trade_id)
        if not trade or trade["status"] != "OPEN":
            return trade
        now = utc_iso()
        with self.connection() as connection:
            self._execute(
                connection,
                """
                UPDATE authoritative_trades SET
                    closed_at=?,status='CLOSED',exit_price=?,exit_reason=?,
                    realized_result=?,metadata_json=?,updated_at=?
                WHERE id=? AND status='OPEN'
                """,
                (
                    utc_iso(closed_at),
                    exit_price,
                    exit_reason,
                    realized_result,
                    json.dumps(metadata or trade.get("metadata") or {}, sort_keys=True),
                    now,
                    trade_id,
                ),
            ).close()
            self._execute(
                connection,
                "UPDATE opportunities SET state='CLOSED',updated_at=? WHERE id=?",
                (now, trade["opportunity_id"]),
            ).close()
        self._diagnostic(
            "trade_closed",
            trade_id=trade_id,
            exit_reason=exit_reason,
        )
        return self.get_trade(trade_id=trade_id)

    def list_open_trades(self) -> list[dict]:
        return self._list_trades("OPEN")

    def list_recent_trades(self, limit=100) -> list[dict]:
        with self.connection() as connection:
            return [
                self._decode(row)
                for row in self._fetchall(
                    connection,
                    """
                    SELECT * FROM authoritative_trades
                    ORDER BY opened_at DESC,id DESC LIMIT ?
                    """,
                    (int(limit),),
                )
            ]

    def record_trade_event(
        self,
        *,
        dedup_key,
        opportunity_id,
        symbol,
        event_type,
        event_timestamp,
        description,
        trade_id=None,
        direction=None,
        setup=None,
        underlying_price=None,
        entry_price=None,
        exit_price=None,
        current_return=None,
        realized_return=None,
        exit_reason=None,
        rule_score=None,
        metadata=None,
        event_id=None,
    ) -> dict:
        """Append one immutable lifecycle event, suppressing duplicate material events."""
        identifier = event_id or uuid4().hex
        with self.connection() as connection:
            self._execute(
                    connection,
                    """
                    INSERT INTO authoritative_trade_events (
                        id,dedup_key,trade_id,opportunity_id,symbol,direction,setup,
                        event_type,event_timestamp,underlying_price,entry_price,
                        exit_price,current_return,realized_return,exit_reason,
                        rule_score,description,metadata_json,created_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(dedup_key) DO NOTHING
                    """,
                    (
                        identifier, str(dedup_key), trade_id, opportunity_id,
                        str(symbol).upper(), direction, setup, event_type,
                        utc_iso(event_timestamp), underlying_price, entry_price,
                        exit_price, current_return, realized_return, exit_reason,
                        rule_score, str(description)[:500],
                        json.dumps(metadata or {}, sort_keys=True), utc_iso(),
                    ),
                ).close()
            row = self._fetchone(
                connection,
                "SELECT * FROM authoritative_trade_events WHERE dedup_key=?",
                (str(dedup_key),),
            )
        return self._decode_trade_event(row)

    def get_trade_event(self, event_id) -> dict | None:
        with self.connection() as connection:
            return self._decode_trade_event(self._fetchone(
                connection,
                "SELECT * FROM authoritative_trade_events WHERE id=?",
                (event_id,),
            ))

    def list_trade_events(self, *, limit=20, opportunity_id=None) -> list[dict]:
        query = "SELECT * FROM authoritative_trade_events"
        params = []
        if opportunity_id:
            query += " WHERE opportunity_id=?"
            params.append(opportunity_id)
        query += " ORDER BY event_timestamp DESC,created_at DESC,id DESC LIMIT ?"
        params.append(int(limit))
        with self.connection() as connection:
            return [
                self._decode_trade_event(row)
                for row in self._fetchall(connection, query, tuple(params))
            ]

    def opportunity_activity_summaries(self, opportunity_ids) -> list[dict]:
        """Project only fields required to enrich an exact set of activity events."""
        identities = sorted({str(value) for value in opportunity_ids if value})
        if not identities:
            return []
        placeholders = ",".join("?" for _ in identities)
        with self.connection() as connection:
            return self._fetchall(connection, f"""SELECT id,direction,signal_timestamp,
                state,confidence,entry_reference FROM opportunities
                WHERE id IN ({placeholders})""", tuple(identities))

    def list_outcome_payloads(self, *, limit=5000, active_only=False):
        """Project only immutable identity and lifecycle payload required for decoding."""
        query = "SELECT id,metadata_json FROM opportunities"
        params = []
        if active_only:
            query += " WHERE state IN ('CANDIDATE','OPEN')"
        query += " ORDER BY signal_timestamp DESC,id DESC LIMIT ?"
        params.append(int(limit))
        with self.connection() as connection:
            return [self._decode(row) for row in self._fetchall(connection, query, tuple(params))]

    def list_trade_event_summaries(self, *, limit=500, event_type=None,
                                   event_types=None, start_at=None, end_at=None) -> list[dict]:
        """Return projected lifecycle fields with optional server-side bounds."""
        query = """SELECT id,trade_id,opportunity_id,symbol,direction,setup,event_type,
            event_timestamp,underlying_price,entry_price,exit_price,current_return,
            realized_return,exit_reason,rule_score,description
            FROM authoritative_trade_events"""
        clauses, params = [], []
        if event_type:
            clauses.append("event_type=?"); params.append(str(event_type))
        if event_types:
            values = tuple(str(value) for value in event_types)
            clauses.append(f"event_type IN ({','.join('?' for _ in values)})")
            params.extend(values)
        if start_at is not None:
            clauses.append("event_timestamp>=?"); params.append(utc_iso(start_at))
        if end_at is not None:
            clauses.append("event_timestamp<=?"); params.append(utc_iso(end_at))
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY event_timestamp DESC,id DESC LIMIT ?"
        params.append(int(limit))
        with self.connection() as connection:
            return [self._decode_trade_event(row) for row in self._fetchall(connection, query, tuple(params))]

    def trade_event_summaries_for_opportunity_ids(self, opportunity_ids) -> list[dict]:
        """Return projected entry/close lifecycle rows for exact authoritative IDs."""
        identities = sorted({str(value) for value in opportunity_ids if value})
        if not identities:
            return []
        placeholders = ",".join("?" for _ in identities)
        query = f"""SELECT id,trade_id,opportunity_id,symbol,direction,setup,event_type,
            event_timestamp,underlying_price,entry_price,exit_price,current_return,
            realized_return,exit_reason,rule_score,description
            FROM authoritative_trade_events
            WHERE (opportunity_id IN ({placeholders}) OR trade_id IN ({placeholders}))
            AND event_type IN ('TRADE_ENTERED','TRADE_CLOSED')
            ORDER BY event_timestamp DESC,id DESC"""
        params = (*identities, *identities)
        with self.connection() as connection:
            return [self._decode_trade_event(row) for row in self._fetchall(connection, query, params)]

    def count_trade_events(self, *, event_type=None, event_types=None,
                           start_at=None, end_at=None) -> int:
        query, clauses, params = "SELECT COUNT(*) AS count FROM authoritative_trade_events", [], []
        if event_type:
            clauses.append("event_type=?"); params.append(str(event_type))
        if event_types:
            values = tuple(str(value) for value in event_types)
            clauses.append(f"event_type IN ({','.join('?' for _ in values)})")
            params.extend(values)
        if start_at is not None:
            clauses.append("event_timestamp>=?"); params.append(utc_iso(start_at))
        if end_at is not None:
            clauses.append("event_timestamp<=?"); params.append(utc_iso(end_at))
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        with self.connection() as connection:
            row = self._fetchone(connection, query, tuple(params))
        return int((row or {}).get("count") or 0)

    def _list_trades(self, status) -> list[dict]:
        with self.connection() as connection:
            return [
                self._decode(row)
                for row in self._fetchall(
                    connection,
                    """
                    SELECT * FROM authoritative_trades
                    WHERE status=? ORDER BY opened_at DESC,id DESC
                    """,
                    (status,),
                )
            ]

    def start_scan_run(
        self, scanner_id=DEFAULT_SCANNER_ID, *, run_number, owner_id,
        started_at, symbol_count=None, code_version=None,
    ):
        """Initialize current-run telemetry after the caller owns the scan lease."""
        current = self.get_scan_health(scanner_id) or {}
        now = utc_iso(started_at)
        values = {
            "last_started_at": now,
            "last_completed_at": current.get("last_completed_at"),
            "last_success_at": current.get("last_success_at"),
            "last_error_at": current.get("last_error_at"),
            "last_error_message": current.get("last_error_message"),
            "last_symbols_processed": current.get("last_symbols_processed"),
            "scan_duration": current.get("scan_duration"),
            "code_version": code_version or current.get("code_version"),
            "market_data_state": "SCANNING",
            "current_run_number": int(run_number or 0),
            "current_symbols_attempted": 0,
            "current_symbol_count": symbol_count,
            "current_results": 0,
            "current_failures": 0,
            "progress_updated_at": now,
            "current_owner_id": owner_id,
            "updated_at": utc_iso(),
        }
        self._upsert_health(scanner_id, values)
        return self.get_scan_health(scanner_id)

    def record_scan_progress(
        self, scanner_id=DEFAULT_SCANNER_ID, *, run_number, owner_id,
        symbols_attempted, symbol_count, results, failures, at=None,
    ) -> bool:
        """Persist bounded progress only for the still-authoritative run owner."""
        with self.connection() as connection:
            cursor = self._execute(
                connection,
                """
                UPDATE scanner_health SET current_symbols_attempted=?,
                    current_symbol_count=?,current_results=?,current_failures=?,
                    progress_updated_at=?,updated_at=?
                WHERE scanner_id=? AND current_run_number=? AND current_owner_id=?
                """,
                (
                    int(symbols_attempted), int(symbol_count), int(results),
                    int(failures), utc_iso(at), utc_iso(), scanner_id,
                    int(run_number or 0), owner_id,
                ),
            )
            updated = cursor.rowcount > 0
            cursor.close()
        return updated

    def finish_scan_run(
        self, scanner_id=DEFAULT_SCANNER_ID, *, run_number, owner_id,
        completed_at, symbols_attempted, symbol_count, results, failures,
        scan_duration, code_version=None, market_data_state="AVAILABLE",
        error_message=None,
    ) -> bool:
        """Finalize only the run that still owns the persisted current-run state."""
        completed = utc_iso(completed_at)
        success = error_message is None
        assignments = [
            "last_completed_at=?", "last_symbols_processed=?", "scan_duration=?",
            "code_version=?", "market_data_state=?", "current_symbols_attempted=?",
            "current_symbol_count=?", "current_results=?", "current_failures=?",
            "progress_updated_at=?", "current_owner_id=NULL", "updated_at=?",
        ]
        values = [
            completed, int(results), scan_duration, code_version,
            market_data_state, int(symbols_attempted), int(symbol_count),
            int(results), int(failures), completed, utc_iso(),
        ]
        if success:
            assignments.extend(["last_success_at=?", "last_error_message=NULL"])
            values.append(completed)
        else:
            assignments.extend(["last_error_at=?", "last_error_message=?"])
            values.extend([completed, str(error_message)[:500]])
        values.extend([scanner_id, int(run_number or 0), owner_id])
        with self.connection() as connection:
            cursor = self._execute(
                connection,
                f"UPDATE scanner_health SET {','.join(assignments)} "
                "WHERE scanner_id=? AND current_run_number=? AND current_owner_id=?",
                tuple(values),
            )
            updated = cursor.rowcount > 0
            cursor.close()
        return updated

    def record_scan_heartbeat(
        self,
        scanner_id=DEFAULT_SCANNER_ID,
        *,
        started_at=None,
        completed_at=None,
        success_at=None,
        symbols_processed=None,
        scan_duration=None,
        code_version=None,
        market_data_state=None,
    ):
        current = self.get_scan_health(scanner_id) or {}
        values = {
            "last_started_at": utc_iso(started_at)
            if started_at
            else current.get("last_started_at"),
            "last_completed_at": utc_iso(completed_at)
            if completed_at
            else current.get("last_completed_at"),
            "last_success_at": utc_iso(success_at)
            if success_at
            else current.get("last_success_at"),
            "last_error_at": current.get("last_error_at"),
            "last_error_message": current.get("last_error_message"),
            "last_symbols_processed": (
                symbols_processed
                if symbols_processed is not None
                else current.get("last_symbols_processed")
            ),
            "scan_duration": (
                scan_duration
                if scan_duration is not None
                else current.get("scan_duration")
            ),
            "code_version": code_version or current.get("code_version"),
            "market_data_state": market_data_state or current.get("market_data_state"),
            "updated_at": utc_iso(),
        }
        self._upsert_health(scanner_id, values)
        return self.get_scan_health(scanner_id)

    def record_scan_error(
        self, message, scanner_id=DEFAULT_SCANNER_ID, *, at=None, code_version=None
    ):
        current = self.get_scan_health(scanner_id) or {}
        values = {
            "last_started_at": current.get("last_started_at"),
            "last_completed_at": current.get("last_completed_at"),
            "last_success_at": current.get("last_success_at"),
            "last_error_at": utc_iso(at),
            "last_error_message": str(message)[:500],
            "last_symbols_processed": current.get("last_symbols_processed"),
            "scan_duration": current.get("scan_duration"),
            "code_version": code_version or current.get("code_version"),
            "market_data_state": "ERROR",
            "updated_at": utc_iso(),
        }
        self._upsert_health(scanner_id, values)
        return self.get_scan_health(scanner_id)

    def _upsert_health(self, scanner_id, values):
        with self.connection() as connection:
            existing = self._fetchone(
                connection,
                "SELECT scanner_id FROM scanner_health WHERE scanner_id=?",
                (scanner_id,),
            )
            if existing:
                self._execute(
                    connection,
                    "UPDATE scanner_health SET "
                    + ",".join(f"{key}=?" for key in values)
                    + " WHERE scanner_id=?",
                    (*values.values(), scanner_id),
                ).close()
            else:
                columns = ["scanner_id", *values]
                self._execute(
                    connection,
                    f"INSERT INTO scanner_health ({','.join(columns)}) VALUES "
                    f"({','.join('?' for _ in columns)})",
                    (scanner_id, *values.values()),
                ).close()

    def get_scan_health(self, scanner_id=DEFAULT_SCANNER_ID) -> dict | None:
        with self.connection() as connection:
            return self._fetchone(
                connection,
                "SELECT * FROM scanner_health WHERE scanner_id=?",
                (scanner_id,),
            )

    def get_latest_scan_health(self) -> dict | None:
        """Return the health row most recently written by any scanner worker."""
        with self.connection() as connection:
            return self._fetchone(
                connection,
                "SELECT * FROM scanner_health "
                "ORDER BY updated_at DESC,scanner_id ASC LIMIT 1",
            )

    def acquire_scan_lock(
        self, scanner_id=DEFAULT_SCANNER_ID, *, owner_id=None, ttl_seconds=120
    ) -> str | None:
        owner = owner_id or uuid4().hex
        now = utc_now()
        expires = now + timedelta(seconds=ttl_seconds)
        with self.connection() as connection:
            if self.backend == "postgresql":
                previous = self._fetchone(
                    connection,
                    "SELECT * FROM scanner_locks WHERE scanner_id=?",
                    (scanner_id,),
                )
                cursor = self._execute(
                    connection,
                    """
                    INSERT INTO scanner_locks
                    (scanner_id,owner_id,acquired_at,expires_at) VALUES (?,?,?,?)
                    ON CONFLICT (scanner_id) DO UPDATE SET
                        owner_id=EXCLUDED.owner_id,
                        acquired_at=EXCLUDED.acquired_at,
                        expires_at=EXCLUDED.expires_at
                    WHERE scanner_locks.expires_at <= ?
                    RETURNING owner_id
                    """,
                    (
                        scanner_id, owner, utc_iso(now), utc_iso(expires),
                        utc_iso(now),
                    ),
                )
                acquired = cursor.fetchone()
                cursor.close()
                if not acquired:
                    row = self._fetchone(
                        connection,
                        "SELECT * FROM scanner_locks WHERE scanner_id=?",
                        (scanner_id,),
                    )
                    self._diagnostic(
                        "scanner_lock_contention",
                        scanner_id=scanner_id,
                        requested_owner_id=owner,
                        lock_owner_id=(row or {}).get("owner_id"),
                        acquired_at=(row or {}).get("acquired_at"),
                        expires_at=(row or {}).get("expires_at"),
                    )
                    return None
                current = self._fetchone(
                    connection,
                    "SELECT * FROM scanner_locks WHERE scanner_id=?",
                    (scanner_id,),
                )
                if previous and parse_utc(previous["expires_at"]) <= now:
                    self._diagnostic(
                        "scanner_lock_expired",
                        scanner_id=scanner_id,
                        persisted_owner_id=previous["owner_id"],
                        previous_expires_at=previous["expires_at"],
                        observed_at=utc_iso(now),
                    )
                    self._diagnostic(
                        "scanner_lock_takeover",
                        scanner_id=scanner_id,
                        requested_owner_id=owner,
                        persisted_owner_id=previous["owner_id"],
                        previous_expires_at=previous["expires_at"],
                        new_expires_at=current["expires_at"],
                        lease_duration_seconds=ttl_seconds,
                        reason="expired_lease",
                    )
                self._diagnostic(
                    "scanner_lock_acquired",
                    scanner_id=scanner_id,
                    requested_owner_id=owner,
                    persisted_owner_id=current["owner_id"],
                    acquired_at=current["acquired_at"],
                    expires_at=current["expires_at"],
                    lease_duration_seconds=ttl_seconds,
                    reason="expired_lease_takeover" if previous else "new_lease",
                )
                return owner

            if self.backend == "sqlite":
                connection.execute("BEGIN IMMEDIATE")
            row = self._fetchone(
                connection,
                "SELECT * FROM scanner_locks WHERE scanner_id=?",
                (scanner_id,),
            )
            if (
                row
                and parse_utc(row["expires_at"]) > now
            ):
                self._diagnostic(
                    "scanner_lock_contention",
                    scanner_id=scanner_id,
                    requested_owner_id=owner,
                    lock_owner_id=row["owner_id"],
                    acquired_at=row["acquired_at"],
                    expires_at=row["expires_at"],
                )
                return None
            if row:
                previous_owner = row["owner_id"]
                previous_expires = row["expires_at"]
                self._execute(
                    connection,
                    """
                    UPDATE scanner_locks SET owner_id=?,acquired_at=?,expires_at=?
                    WHERE scanner_id=?
                    """,
                    (owner, utc_iso(now), utc_iso(expires), scanner_id),
                ).close()
                if parse_utc(previous_expires) <= now:
                    self._diagnostic(
                        "scanner_lock_expired", scanner_id=scanner_id,
                        persisted_owner_id=previous_owner,
                        previous_expires_at=previous_expires,
                        observed_at=utc_iso(now),
                    )
                    self._diagnostic(
                        "scanner_lock_takeover", scanner_id=scanner_id,
                        requested_owner_id=owner,
                        persisted_owner_id=previous_owner,
                        previous_expires_at=previous_expires,
                        new_expires_at=utc_iso(expires),
                        lease_duration_seconds=ttl_seconds,
                        reason="expired_lease",
                    )
            else:
                self._execute(
                    connection,
                    """
                    INSERT INTO scanner_locks
                    (scanner_id,owner_id,acquired_at,expires_at) VALUES (?,?,?,?)
                    """,
                    (scanner_id, owner, utc_iso(now), utc_iso(expires)),
                ).close()
            self._diagnostic(
                "scanner_lock_acquired",
                scanner_id=scanner_id,
                requested_owner_id=owner,
                persisted_owner_id=owner,
                acquired_at=utc_iso(now),
                expires_at=utc_iso(expires),
                lease_duration_seconds=ttl_seconds,
                reason="expired_lease_takeover" if row else "new_lease",
            )
        return owner

    def renew_scan_lock(
        self, scanner_id, owner_id, *, ttl_seconds=120
    ) -> bool:
        """Extend only an unexpired lease owned by the exact process identity."""
        now = utc_now()
        expires = now + timedelta(seconds=ttl_seconds)
        with self.connection() as connection:
            previous = self._fetchone(
                connection,
                "SELECT * FROM scanner_locks WHERE scanner_id=?",
                (scanner_id,),
            )
            cursor = self._execute(
                connection,
                """
                UPDATE scanner_locks SET expires_at=?
                WHERE scanner_id=? AND owner_id=? AND expires_at>?
                """,
                (utc_iso(expires), scanner_id, owner_id, utc_iso(now)),
            )
            renewed = cursor.rowcount > 0
            cursor.close()
            current = self._fetchone(
                connection,
                "SELECT * FROM scanner_locks WHERE scanner_id=?",
                (scanner_id,),
            )
        if renewed:
            self._diagnostic(
                "scanner_lock_renewed", scanner_id=scanner_id,
                requested_owner_id=owner_id,
                persisted_owner_id=(current or {}).get("owner_id"),
                previous_expires_at=(previous or {}).get("expires_at"),
                new_expires_at=(current or {}).get("expires_at"),
                lease_duration_seconds=ttl_seconds,
            )
        else:
            self._diagnostic(
                "scanner_lock_renewal_rejected", scanner_id=scanner_id,
                requested_owner_id=owner_id,
                persisted_owner_id=(current or {}).get("owner_id"),
                previous_expires_at=(previous or {}).get("expires_at"),
                current_expires_at=(current or {}).get("expires_at"),
                reason=(
                    "missing_lock" if current is None else
                    "owner_mismatch" if current.get("owner_id") != owner_id else
                    "lease_expired"
                ),
            )
        return renewed

    def release_scan_lock(self, scanner_id, owner_id):
        current = self.get_scan_lock(scanner_id)
        self._diagnostic(
            "scanner_lock_release_attempt", scanner_id=scanner_id,
            requested_owner_id=owner_id,
            persisted_owner_id=(current or {}).get("owner_id"),
            expires_at=(current or {}).get("expires_at"),
        )
        with self.connection() as connection:
            cursor = self._execute(
                connection,
                "DELETE FROM scanner_locks WHERE scanner_id=? AND owner_id=?",
                (scanner_id, owner_id),
            )
            released = cursor.rowcount > 0
            cursor.close()
        self._diagnostic(
            "scanner_lock_released" if released else "scanner_lock_release_rejected",
            scanner_id=scanner_id,
            requested_owner_id=owner_id,
            persisted_owner_id=(current or {}).get("owner_id"),
            reason="exact_owner" if released else "owner_mismatch_or_missing",
        )
        return released

    def get_scan_lock(self, scanner_id=DEFAULT_SCANNER_ID):
        with self.connection() as connection:
            return self._fetchone(
                connection,
                "SELECT * FROM scanner_locks WHERE scanner_id=?",
                (scanner_id,),
            )

    def record_legacy_import(
        self, source_path, source_fingerprint, source_row, opportunity_id
    ):
        with self.connection() as connection:
            try:
                self._execute(
                    connection,
                    """
                    INSERT INTO legacy_imports (
                        source_path,source_fingerprint,source_row,imported_at,
                        opportunity_id
                    ) VALUES (?,?,?,?,?)
                    """,
                    (
                        str(source_path),
                        source_fingerprint,
                        str(source_row),
                        utc_iso(),
                        opportunity_id,
                    ),
                ).close()
                return True
            except Exception:
                return False

    def legacy_imported(self, source_fingerprint, source_row) -> bool:
        with self.connection() as connection:
            return bool(
                self._fetchone(
                    connection,
                    """
                    SELECT source_row FROM legacy_imports
                    WHERE source_fingerprint=? AND source_row=?
                    """,
                    (source_fingerprint, str(source_row)),
                )
            )

    def create_opportunity_context(self, opportunity_id, context, *, schema_version=1):
        """Persist one immutable point-in-time context row per opportunity."""
        existing = self.get_opportunity_context(opportunity_id)
        if existing:
            return existing
        encoded = json.dumps(context, sort_keys=True, default=str)
        with self.connection() as connection:
            try:
                self._execute(connection, """INSERT INTO opportunity_context
                    (opportunity_id,context_json,schema_version,captured_at,eastern_session,experiment_scope)
                    VALUES (?,?,?,?,?,?) ON CONFLICT(opportunity_id) DO NOTHING""", (
                    opportunity_id, encoded, int(schema_version), context["captured_at"],
                    context["eastern_session"], context["experiment_scope"],
                )).close()
            except Exception:
                existing = self.get_opportunity_context(opportunity_id)
                if not existing:
                    raise
        return self.get_opportunity_context(opportunity_id)

    def get_opportunity_context(self, opportunity_id):
        with self.connection() as connection:
            row = self._fetchone(connection, """SELECT opportunity_id,context_json,schema_version,
                captured_at,eastern_session,experiment_scope FROM opportunity_context
                WHERE opportunity_id=?""", (opportunity_id,))
        if not row:
            return None
        row["context"] = json.loads(row.pop("context_json"))
        return row

    def enrich_opportunity_context(self, opportunity_id, patch):
        """Add known-at-stage measurements without replacing the decision snapshot."""
        existing = self.get_opportunity_context(opportunity_id)
        if not existing:
            return None
        context = existing["context"]
        for group, values in patch.items():
            if isinstance(values, dict):
                context.setdefault(group, {}).update({key: value for key, value in values.items() if value is not None})
        with self.connection() as connection:
            self._execute(connection, "UPDATE opportunity_context SET context_json=? WHERE opportunity_id=?",
                          (json.dumps(context, sort_keys=True, default=str), opportunity_id)).close()
        return self.get_opportunity_context(opportunity_id)

    def list_opportunity_contexts(self, *, start_session=None, end_session=None, limit=5000):
        query = """SELECT opportunity_id,context_json,schema_version,captured_at,eastern_session,
            experiment_scope FROM opportunity_context"""
        clauses, params = [], []
        if start_session:
            clauses.append("eastern_session>=?"); params.append(str(start_session))
        if end_session:
            clauses.append("eastern_session<=?"); params.append(str(end_session))
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY eastern_session DESC,captured_at DESC LIMIT ?"
        params.append(min(max(int(limit), 1), 10000))
        with self.connection() as connection:
            rows = self._fetchall(connection, query, tuple(params))
        result = []
        for row in rows:
            context = json.loads(row.pop("context_json")); context.update({
                "opportunity_id": row["opportunity_id"], "captured_at": row["captured_at"],
                "eastern_session": row["eastern_session"], "experiment_scope": row["experiment_scope"]})
            result.append(context)
        return result

    def create_intelligence_snapshot(self, opportunity_id, snapshot, *, schema_version=1):
        """Insert an immutable decision-time snapshot, returning the original on repeats."""
        existing = self.get_intelligence_snapshot(opportunity_id)
        if existing is not None:
            return existing
        with self.connection() as connection:
            try:
                self._execute(
                    connection,
                    "INSERT INTO intelligence_setup_snapshots "
                    "(opportunity_id,snapshot_json,schema_version,created_at) VALUES (?,?,?,?)",
                    (opportunity_id, json.dumps(snapshot, sort_keys=True), int(schema_version), utc_iso()),
                ).close()
            except Exception:
                existing = self.get_intelligence_snapshot(opportunity_id)
                if existing is not None:
                    return existing
                raise
        return self.get_intelligence_snapshot(opportunity_id)

    def get_intelligence_snapshot(self, opportunity_id):
        with self.connection() as connection:
            row = self._fetchone(connection, "SELECT * FROM intelligence_setup_snapshots WHERE opportunity_id=?", (opportunity_id,))
        return self._decode_intelligence(row, "snapshot_json", "snapshot")

    def list_intelligence_snapshots(self, *, limit=5000, start_at=None):
        with self.connection() as connection:
            query = "SELECT opportunity_id,snapshot_json,schema_version,created_at FROM intelligence_setup_snapshots"
            params = []
            if start_at is not None:
                query += " WHERE created_at>=?"; params.append(utc_iso(start_at))
            query += " ORDER BY created_at DESC,opportunity_id ASC LIMIT ?"; params.append(int(limit))
            rows = self._fetchall(connection, query, tuple(params))
        return [self._decode_intelligence(row, "snapshot_json", "snapshot") for row in rows]

    def upsert_intelligence_outcome(self, opportunity_id, outcome, *, schema_version=1):
        now, encoded = utc_iso(), json.dumps(outcome, sort_keys=True)
        with self.connection() as connection:
            existing = self._fetchone(connection, "SELECT opportunity_id FROM intelligence_outcome_labels WHERE opportunity_id=?", (opportunity_id,))
            if existing:
                self._execute(connection, "UPDATE intelligence_outcome_labels SET outcome_json=?,schema_version=?,updated_at=? WHERE opportunity_id=?", (encoded, int(schema_version), now, opportunity_id)).close()
            else:
                self._execute(connection, "INSERT INTO intelligence_outcome_labels (opportunity_id,outcome_json,schema_version,updated_at) VALUES (?,?,?,?)", (opportunity_id, encoded, int(schema_version), now)).close()
        return self.get_intelligence_outcome(opportunity_id)

    def get_intelligence_outcome(self, opportunity_id):
        with self.connection() as connection:
            row = self._fetchone(connection, "SELECT * FROM intelligence_outcome_labels WHERE opportunity_id=?", (opportunity_id,))
        return self._decode_intelligence(row, "outcome_json", "outcome")

    def list_intelligence_outcomes(self, *, limit=5000, start_at=None):
        with self.connection() as connection:
            query = "SELECT opportunity_id,outcome_json,schema_version,updated_at FROM intelligence_outcome_labels"
            params = []
            if start_at is not None:
                query += " WHERE updated_at>=?"; params.append(utc_iso(start_at))
            query += " ORDER BY updated_at DESC,opportunity_id ASC LIMIT ?"; params.append(int(limit))
            rows = self._fetchall(connection, query, tuple(params))
        return [self._decode_intelligence(row, "outcome_json", "outcome") for row in rows]

    def record_intelligence_shadow_event(self, event_type, payload, *, opportunity_id=None, model_version=None):
        identifier = uuid4().hex
        with self.connection() as connection:
            self._execute(connection, "INSERT INTO intelligence_shadow_events (id,opportunity_id,event_type,model_version,payload_json,created_at) VALUES (?,?,?,?,?,?)", (identifier, opportunity_id, event_type, model_version, json.dumps(payload, sort_keys=True), utc_iso())).close()
        return identifier

    @staticmethod
    def _decode_intelligence(row, source, target):
        if not row:
            return None
        try:
            row[target] = json.loads(row.get(source) or "{}")
        except Exception:
            row[target] = {}
        return row

    @staticmethod
    def _decode(row):
        if not row:
            return row
        for source, target in (
            ("evidence_json", "evidence"),
            ("metadata_json", "metadata"),
        ):
            if source in row:
                try:
                    row[target] = json.loads(row.get(source) or "{}")
                except Exception:
                    row[target] = {}
        return row

    @classmethod
    def _decode_trade_event(cls, row):
        row = cls._decode(row)
        if row and row.get("event_timestamp"):
            row["eastern_timestamp"] = parse_utc(
                row["event_timestamp"]
            ).astimezone(ZoneInfo("America/New_York")).isoformat()
        return row


def production_repository(*, db_file=DEFAULT_REPOSITORY_FILE) -> TradeRepository:
    require_durable = os.getenv(
        "OPTIONBEACON_REQUIRE_DURABLE_STORAGE", ""
    ).lower() in {"1", "true", "yes"}
    return TradeRepository(db_file, require_durable=require_durable)
