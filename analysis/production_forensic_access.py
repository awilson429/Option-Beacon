"""Production-safe access and reconciliation for the post-run forensic audit."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from contextlib import contextmanager
from datetime import date
from urllib.parse import urlsplit

from psycopg2 import connect
from psycopg2.extras import RealDictCursor

from analysis.run_post_run_forensic_audit import read_sessions
from post_run_forensic_audit import build_forensic_report


LOGGER = logging.getLogger(__name__)


class ReadOnlyTransactionError(RuntimeError):
    """Sanitized failure to establish the forensic read-only transaction."""


def sanitize_database_error(error):
    text = str(error or "").lower()
    if "read only" in text or "read-only" in text:
        return "read-only transaction unavailable"
    if "timeout" in text:
        return "database connection timed out"
    return "database operation unavailable"
REQUIRED_TABLE_COLUMNS = {
    "authoritative_trade_events": {"opportunity_id", "event_type", "event_timestamp"},
    "opportunities": {"id", "signal_timestamp"},
    "intelligence_setup_snapshots": {"opportunity_id", "snapshot_json", "created_at"},
    "intelligence_outcome_labels": {"opportunity_id", "outcome_json", "updated_at"},
    "paper_execution_trades": {"trade_id", "source_signal_id", "status"},
    "paper_execution_positions": {"trade_id", "status"},
    "paper_execution_journal": {"trade_id", "accepted", "created_at", "metadata_json"},
    "mirror_execution_trades": {"mirror_trade_id", "opportunity_id", "status", "entry_event_at"},
    "mirror_execution_marks": {"mirror_trade_id", "observed_at", "return_pct"},
    "mirror_execution_runtime_state": {"scanner_id", "updated_at"},
    "intraday_signals": {"opportunity_id", "detected_at"},
    "intraday_paper_trades": {"trade_id", "status", "opened_at"},
    "intraday_paper_journal": {"journal_id", "event_at"},
    "intraday_runtime_state": {"scanner_id", "updated_at"},
}


def database_fingerprint(database_url):
    """Return a non-reversible logical-target fingerprint without credentials."""
    parsed = urlsplit(str(database_url or ""))
    target = f"{parsed.scheme.lower()}|{(parsed.hostname or '').lower()}|{parsed.path.lstrip('/')}"
    return hashlib.sha256(target.encode("utf-8")).hexdigest()[:16] if parsed.hostname else "UNAVAILABLE"


@contextmanager
def read_only_connection(database_url, connector=connect):
    if not database_url:
        raise RuntimeError("Production DATABASE_URL is not configured")
    connection = connector(database_url, cursor_factory=RealDictCursor, sslmode="require")
    try:
        connection.autocommit = False
        try:
            with connection.cursor() as cursor:
                cursor.execute("BEGIN")
                cursor.execute("SET TRANSACTION READ ONLY")
        except Exception as error:
            connection.rollback()
            LOGGER.error(json.dumps({
                "event": "post_run_forensic_audit_failed",
                "failure_stage": "read_only_transaction",
                "exception_class": type(error).__name__,
                "message": sanitize_database_error(error),
                "database_fingerprint": database_fingerprint(database_url),
            }, sort_keys=True))
            raise ReadOnlyTransactionError("Could not establish a read-only database transaction.") from None
        yield connection
    finally:
        connection.rollback()
        connection.close()


def table_presence(database_url, connector=connect):
    with read_only_connection(database_url, connector) as connection, connection.cursor() as cursor:
        cursor.execute("""SELECT table_name,column_name FROM information_schema.columns
            WHERE table_schema='public' AND table_name=ANY(%s) ORDER BY table_name,column_name""",
                       (list(REQUIRED_TABLE_COLUMNS),))
        actual = {}
        for row in cursor.fetchall():
            actual.setdefault(row["table_name"], set()).add(row["column_name"])
    result = {}
    for table, required in REQUIRED_TABLE_COLUMNS.items():
        columns = actual.get(table)
        result[table] = {
            "status": "ABSENT" if columns is None else "PRESENT" if required <= columns else "INCOMPATIBLE",
            "missing_columns": sorted(required - (columns or set())),
        }
    return result


def reconciliation_snapshot(database_url, presence=None, connector=connect):
    presence = presence or table_presence(database_url, connector)
    usable = lambda table: presence.get(table, {}).get("status") == "PRESENT"
    result = {}
    with read_only_connection(database_url, connector) as connection, connection.cursor() as cursor:
        if usable("paper_execution_positions"):
            result["paper_open_positions"] = _scalar(cursor, "SELECT COUNT(*) AS value FROM paper_execution_positions WHERE status='OPEN'")
        if usable("mirror_execution_trades"):
            cursor.execute("""SELECT COUNT(*) AS total,
                COUNT(*) FILTER (WHERE status IN ('OPEN','EXIT_PENDING')) AS open,
                COUNT(*) FILTER (WHERE status='CLOSED') AS closed,
                COUNT(*) FILTER (WHERE disposition_code='MIRROR_ENTRY_UNEXECUTABLE') AS unexecutable,
                MIN(entry_event_at) AS earliest_trade,MAX(entry_event_at) AS latest_trade
                FROM mirror_execution_trades""")
            result.update({f"mirror_{key}": value for key, value in dict(cursor.fetchone()).items()})
        if usable("mirror_execution_marks"):
            cursor.execute("""SELECT COUNT(*) AS total,MIN(observed_at) AS earliest_mark,MAX(observed_at) AS latest_mark,
                COUNT(DISTINCT mirror_trade_id) AS trades_with_telemetry FROM mirror_execution_marks""")
            result.update({f"marks_{key}": value for key, value in dict(cursor.fetchone()).items()})
        if usable("mirror_execution_trades") and usable("mirror_execution_marks"):
            result["mirror_trades_without_telemetry"] = _scalar(cursor, """SELECT COUNT(*) AS value FROM mirror_execution_trades t
                WHERE NOT EXISTS (SELECT 1 FROM mirror_execution_marks m WHERE m.mirror_trade_id=t.mirror_trade_id)""")
        if usable("authoritative_trade_events"):
            result["latest_authoritative_entry"] = _scalar(cursor, "SELECT MAX(event_timestamp) AS value FROM authoritative_trade_events WHERE event_type='TRADE_ENTERED'")
        if usable("paper_execution_journal"):
            result["latest_broad_journal"] = _scalar(cursor, """SELECT MAX(created_at) AS value FROM paper_execution_journal
                WHERE UPPER(COALESCE(metadata_json::jsonb->>'simulation_profile',''))='BROAD'""")
        if usable("intraday_runtime_state"):
            result["latest_intraday_runtime"] = _scalar(cursor, "SELECT MAX(updated_at) AS value FROM intraday_runtime_state")
    return result


def discover_sessions(database_url, presence=None, connector=connect):
    presence = presence or table_presence(database_url, connector)
    required = ("mirror_execution_trades", "intelligence_outcome_labels")
    if any(presence.get(table, {}).get("status") != "PRESENT" for table in required):
        return {"discovered": [], "analyzable": [], "excluded": [], "first": None, "last": None}
    marks_present = presence.get("mirror_execution_marks", {}).get("status") == "PRESENT"
    marks_join = "LEFT JOIN mirror_execution_marks k ON k.mirror_trade_id=m.mirror_trade_id" if marks_present else ""
    marks_count = "COUNT(DISTINCT k.mirror_trade_id)" if marks_present else "0"
    query = f"""SELECT (m.entry_event_at::timestamptz AT TIME ZONE 'America/New_York')::date AS session_date,
        COUNT(DISTINCT m.mirror_trade_id) AS mirror_n,COUNT(DISTINCT o.opportunity_id) AS outcome_n,
        {marks_count} AS telemetry_n FROM mirror_execution_trades m
        LEFT JOIN intelligence_outcome_labels o ON o.opportunity_id=m.opportunity_id {marks_join}
        WHERE m.entry_event_at IS NOT NULL GROUP BY session_date ORDER BY session_date"""
    with read_only_connection(database_url, connector) as connection, connection.cursor() as cursor:
        cursor.execute(query)
        rows = [dict(row) for row in cursor.fetchall()]
    analyzable, excluded = [], []
    for row in rows:
        value = str(row["session_date"])
        reasons = []
        if int(row.get("outcome_n") or 0) == 0: reasons.append("NO_AUTHORITATIVE_OUTCOMES")
        if int(row.get("telemetry_n") or 0) == 0: reasons.append("NO_MIRROR_TELEMETRY")
        (excluded if reasons else analyzable).append({"session": value, "reason": ", ".join(reasons)} if reasons else value)
    return {"discovered": [str(row["session_date"]) for row in rows], "analyzable": analyzable,
            "excluded": excluded, "first": analyzable[0] if analyzable else None,
            "last": analyzable[-1] if analyzable else None}


def pairing_summary(report, paper_trades, paper_journal):
    rows = report.get("translation_matrix") or []
    mirror_matches = sum(int(row.get("n") or 0) for row in rows)
    authoritative = int(report.get("analysis_window", {}).get("authoritative_opportunities") or 0)
    broad_sources = {str(row.get("source_signal_id")) for row in paper_trades if row.get("source_signal_id")}
    broad_decisions = []
    for row in paper_journal:
        metadata = _json(row.get("metadata_json"))
        if str(metadata.get("simulation_profile") or "").upper() == "BROAD": broad_decisions.append(row)
    accepted = sum(bool(row.get("accepted")) for row in broad_decisions)
    return {"authoritative_opportunities": authoritative, "mirror_matches": mirror_matches,
            "unmatched_authoritative": max(0, authoritative - mirror_matches),
            "unmatched_mirror": len(report.get("data_integrity", {}).get("orphaned_records", {}).get("mirror_without_authoritative", [])),
            "paired_percent": mirror_matches / authoritative * 100 if authoritative else None,
            "broad_sources": len(broad_sources), "broad_evaluated": len(broad_decisions),
            "broad_accepted": accepted, "broad_rejected": len(broad_decisions) - accepted}


def run_production_audit(database_url, *, dashboard_fingerprint=None, connector=connect, reader=read_sessions):
    started = time.perf_counter()
    fingerprint = database_fingerprint(database_url)
    LOGGER.info(json.dumps({"event": "post_run_forensic_audit_started", "database_fingerprint": fingerprint}))
    try:
        presence = table_presence(database_url, connector)
        reconciliation = reconciliation_snapshot(database_url, presence, connector)
        mismatch = bool(dashboard_fingerprint and dashboard_fingerprint != fingerprint)
        sessions = discover_sessions(database_url, presence, connector)
        required = ("mirror_execution_trades", "mirror_execution_marks")
        mirror_missing = any(presence[table]["status"] != "PRESENT" for table in required)
        if mismatch or mirror_missing or not sessions["analyzable"]:
            reason = "DATABASE_FINGERPRINT_MISMATCH" if mismatch else "MIRROR_LEDGER_MISMATCH" if mirror_missing else "NO_COMPLETE_SESSIONS"
            result = {"status": "STOPPED", "reason": reason, "database": _database_identity(fingerprint, presence),
                      "reconciliation": reconciliation, "sessions": sessions, "report": None}
        else:
            values = reader(database_url, start_date=date.fromisoformat(sessions["first"]), end_date=date.fromisoformat(sessions["last"]))
            report = build_forensic_report(*values[:6])
            report["source_status"] = values[6]
            result = {"status": "COMPLETED", "reason": None, "database": _database_identity(fingerprint, presence),
                      "reconciliation": reconciliation, "sessions": sessions,
                      "pairing": pairing_summary(report, values[4], values[5]), "report": report,
                      "source_records": {
                          "authoritative_snapshots": values[0], "authoritative_outcomes": values[1],
                          "mirror_trades": values[2], "mirror_marks": values[3],
                          "paper_trades": values[4], "broad_journal": values[5],
                      }}
        duration = round((time.perf_counter() - started) * 1000)
        LOGGER.info(json.dumps({"event": "post_run_forensic_audit_completed", "database_fingerprint": fingerprint,
            "sessions_analyzed": len(sessions["analyzable"]), "authoritative_n": (result.get("pairing") or {}).get("authoritative_opportunities", 0),
            "mirror_n": reconciliation.get("mirror_total", 0), "telemetry_coverage": reconciliation.get("marks_trades_with_telemetry", 0), "duration_ms": duration}))
        result["duration_ms"] = duration
        return result
    except Exception as error:
        LOGGER.error(json.dumps({"event": "post_run_forensic_audit_failed", "database_fingerprint": fingerprint,
                                 "failure_stage": "read_only_transaction" if isinstance(error, ReadOnlyTransactionError) else "audit_query",
                                 "exception_class": type(error).__name__, "message": sanitize_database_error(error),
                                 "duration_ms": round((time.perf_counter() - started) * 1000)}, sort_keys=True))
        raise


def _database_identity(fingerprint, presence):
    return {"engine": "postgresql", "schema": "public", "fingerprint": fingerprint,
            "durability": "DURABLE", "table_presence": presence}


def _scalar(cursor, query):
    cursor.execute(query)
    return dict(cursor.fetchone()).get("value")


def _json(value):
    if isinstance(value, dict): return value
    try: return json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError): return {}
