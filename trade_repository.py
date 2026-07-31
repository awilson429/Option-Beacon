"""Authoritative, transactional opportunity/trade/scanner-health repository."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4


DEFAULT_REPOSITORY_FILE = "optionbeacon_state.db"
DEFAULT_SCANNER_ID = "optionbeacon-scanner"
DEFAULT_DB_CONNECT_TIMEOUT_SECONDS = 10
MIN_DB_CONNECT_TIMEOUT_SECONDS = 1
MAX_DB_CONNECT_TIMEOUT_SECONDS = 60
UTC = timezone.utc


class RepositoryUnavailable(RuntimeError):
    """Raised when authoritative storage cannot be reached."""


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
        cursor = self._execute(connection, query, params)
        rows = [dict(row) for row in cursor.fetchall()]
        cursor.close()
        return rows

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
                    updated_at TEXT NOT NULL
                )
                """,
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

    def acquire_scan_lock(
        self, scanner_id=DEFAULT_SCANNER_ID, *, owner_id=None, ttl_seconds=900
    ) -> str | None:
        owner = owner_id or uuid4().hex
        now = utc_now()
        expires = now + timedelta(seconds=ttl_seconds)
        with self.connection() as connection:
            if self.backend == "sqlite":
                connection.execute("BEGIN IMMEDIATE")
            row = self._fetchone(
                connection,
                "SELECT * FROM scanner_locks WHERE scanner_id=?",
                (scanner_id,),
            )
            if row and parse_utc(row["expires_at"]) > now:
                return None
            if row:
                self._execute(
                    connection,
                    """
                    UPDATE scanner_locks SET owner_id=?,acquired_at=?,expires_at=?
                    WHERE scanner_id=?
                    """,
                    (owner, utc_iso(now), utc_iso(expires), scanner_id),
                ).close()
            else:
                self._execute(
                    connection,
                    """
                    INSERT INTO scanner_locks
                    (scanner_id,owner_id,acquired_at,expires_at) VALUES (?,?,?,?)
                    """,
                    (scanner_id, owner, utc_iso(now), utc_iso(expires)),
                ).close()
        return owner

    def release_scan_lock(self, scanner_id, owner_id):
        with self.connection() as connection:
            self._execute(
                connection,
                "DELETE FROM scanner_locks WHERE scanner_id=? AND owner_id=?",
                (scanner_id, owner_id),
            ).close()

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


def production_repository(*, db_file=DEFAULT_REPOSITORY_FILE) -> TradeRepository:
    require_durable = os.getenv(
        "OPTIONBEACON_REQUIRE_DURABLE_STORAGE", ""
    ).lower() in {"1", "true", "yes"}
    return TradeRepository(db_file, require_durable=require_durable)
