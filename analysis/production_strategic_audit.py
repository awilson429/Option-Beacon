"""On-demand production orchestration for the strategic SPY/QQQ audit."""
from __future__ import annotations

import json
import logging
import time as monotonic_time
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from analysis.production_forensic_access import database_fingerprint, read_only_connection
from analysis.run_spy_qqq_strategic_audit import PROJECTIONS, read_snapshot
from strategic_spy_qqq_audit import build_strategic_audit

EASTERN = ZoneInfo("America/New_York")
PRIOR_CONFIRMED_PRODUCTION_FINGERPRINT = "381d634898fd6d6a"
LOGGER = logging.getLogger(__name__)


class StrategicAuditFailure(RuntimeError):
    """Sanitized stage information safe for server logs and the dashboard."""
    def __init__(self, stage, exception_class, summary):
        self.stage = stage
        self.exception_class = exception_class
        self.safe_summary = summary
        super().__init__(f"Strategic audit failed during {stage} ({exception_class}).")


def _safe_summary(error):
    if isinstance(error, (TypeError, ValueError)):
        return "persisted telemetry could not be normalized"
    if type(error).__name__ in {"ProgrammingError", "UndefinedColumn", "UndefinedTable"}:
        return "production schema is incompatible with an audit projection"
    if type(error).__name__ in {"OperationalError", "InterfaceError"}:
        return "database operation unavailable"
    return "strategic audit operation unavailable"


def _failure(stage, error):
    return error if isinstance(error, StrategicAuditFailure) else StrategicAuditFailure(
        stage, type(error).__name__, _safe_summary(error))


def production_reconciliation(database_url, *, connector=None, now=None):
    """Use SQL aggregates only; return safe counts and discovered ET sessions."""
    kwargs = {"connector": connector} if connector else {}
    with read_only_connection(database_url, **kwargs) as connection, connection.cursor() as cursor:
        try:
            cursor.execute("SELECT table_name,column_name FROM information_schema.columns WHERE table_schema='public'")
            columns = {}
            for row in cursor.fetchall(): columns.setdefault(row["table_name"], set()).add(row["column_name"])
            tables = set(columns)
        except Exception as error:
            raise _failure("SCHEMA_INSPECTION", error) from None

        def scalar(table, expression="COUNT(*)", where="", required=()):
            if table not in tables or not set(required) <= columns.get(table, set()): return None
            cursor.execute(f"SELECT {expression} AS value FROM {table}{where}")
            return dict(cursor.fetchone()).get("value")

        try:
            result = {
            "latest_authoritative_event_timestamp": scalar("authoritative_trade_events", "MAX(event_timestamp)", required=("event_timestamp",)),
            "mirror_total_trades": scalar("mirror_execution_trades"),
            "mirror_closed_trades": scalar("mirror_execution_trades", "COUNT(*)", " WHERE status='CLOSED'", ("status",)),
            "mirror_marks": scalar("mirror_execution_marks"),
            "broad_paper_trades": scalar("paper_execution_trades", "COUNT(*)", " WHERE EXISTS (SELECT 1 FROM paper_execution_journal j WHERE j.trade_id=paper_execution_trades.trade_id AND UPPER(COALESCE(j.metadata_json::jsonb->>'simulation_profile',''))='BROAD')",
                ("trade_id",)) if {"trade_id", "metadata_json"} <= columns.get("paper_execution_journal", set()) else None,
            "filtered_records": scalar("filtered_execution_trades"),
            "spy_intraday_signals": scalar("intraday_signals", "COUNT(*)", " WHERE symbol='SPY'", ("symbol",)),
            "spy_intraday_trades": scalar("intraday_paper_trades", "COUNT(*)", " WHERE symbol='SPY'", ("symbol",)),
            "spy_intraday_closed": scalar("intraday_paper_trades", "COUNT(*)", " WHERE symbol='SPY' AND status='CLOSED'", ("symbol","status")),
            "spy_intraday_mirror": scalar("intraday_paper_trades", "COUNT(*)", " WHERE symbol='SPY' AND variant='INTRADAY_MIRROR'", ("symbol","variant")),
            "spy_intraday_managed": scalar("intraday_paper_trades", "COUNT(*)", " WHERE symbol='SPY' AND variant='INTRADAY_MANAGED'", ("symbol","variant")),
            "spy_realized_pnl": scalar("intraday_paper_trades", "COALESCE(SUM(realized_pnl),0)", " WHERE symbol='SPY' AND status='CLOSED'", ("symbol","status","realized_pnl")),
            "qqq_intraday_signals": scalar("intraday_signals", "COUNT(*)", " WHERE symbol='QQQ'", ("symbol",)),
            "qqq_intraday_trades": scalar("intraday_paper_trades", "COUNT(*)", " WHERE symbol='QQQ'", ("symbol",)),
            "qqq_intraday_closed": scalar("intraday_paper_trades", "COUNT(*)", " WHERE symbol='QQQ' AND status='CLOSED'", ("symbol","status")),
            "qqq_intraday_mirror": scalar("intraday_paper_trades", "COUNT(*)", " WHERE symbol='QQQ' AND variant='INTRADAY_MIRROR'", ("symbol","variant")),
            "qqq_intraday_managed": scalar("intraday_paper_trades", "COUNT(*)", " WHERE symbol='QQQ' AND variant='INTRADAY_MANAGED'", ("symbol","variant")),
            "qqq_realized_pnl": scalar("intraday_paper_trades", "COALESCE(SUM(realized_pnl),0)", " WHERE symbol='QQQ' AND status='CLOSED'", ("symbol","status","realized_pnl")),
            "opportunity_context_count": scalar("opportunity_context"),
            "context_shadow_count": scalar("context_shadow_decisions"),
            "position_context_marks_count": scalar("position_context_marks"),
            "intraday_journal_count": scalar("intraday_paper_journal"),
            "latest_intraday_runtime": scalar("intraday_runtime_state", "MAX(updated_at)", required=("updated_at",)),
            "intraday_runtime_status": scalar("intraday_runtime_state", "MAX(status)", required=("status",)),
            "earliest_broad_universe_timestamp": scalar("mirror_execution_trades", "MIN(entry_event_at)", required=("entry_event_at",)),
            "earliest_spy_qqq_timestamp": scalar("intraday_signals", "MIN(detected_at)", required=("detected_at",)),
        }
        except Exception as error:
            raise _failure("RECONCILIATION", error) from None
        session_queries = []
        if "entry_event_at" in columns.get("mirror_execution_trades", set()):
            session_queries.append("SELECT (entry_event_at::timestamptz AT TIME ZONE 'America/New_York')::date AS session_date FROM mirror_execution_trades WHERE entry_event_at IS NOT NULL")
        if "opened_at" in columns.get("paper_execution_trades", set()):
            session_queries.append("SELECT (opened_at::timestamptz AT TIME ZONE 'America/New_York')::date AS session_date FROM paper_execution_trades WHERE opened_at IS NOT NULL")
        if "detected_at" in columns.get("intraday_signals", set()):
            session_queries.append("SELECT (detected_at::timestamptz AT TIME ZONE 'America/New_York')::date AS session_date FROM intraday_signals WHERE detected_at IS NOT NULL")
        try:
            if session_queries:
                cursor.execute("SELECT DISTINCT session_date FROM (" + " UNION ".join(session_queries) + ") s WHERE session_date IS NOT NULL ORDER BY session_date")
                discovered = [str(row["session_date"]) for row in cursor.fetchall()]
            else: discovered = []
        except Exception as error:
            raise _failure("SESSION_DISCOVERY", error) from None
    local_now = (now or datetime.now(timezone.utc)).astimezone(EASTERN)
    incomplete = [day for day in discovered if day == local_now.date().isoformat() and local_now.time() < time(16)]
    complete = [day for day in discovered if day not in incomplete]
    result["sessions"] = {"discovered": discovered, "complete": complete,
        "incomplete_excluded": [{"session": day, "reason": "CURRENT_ET_SESSION_NOT_CLOSED"} for day in incomplete],
        "earliest_broad_universe_session": _et_day(result.get("earliest_broad_universe_timestamp")),
        "earliest_spy_qqq_session": _et_day(result.get("earliest_spy_qqq_timestamp")),
        "latest_session": discovered[-1] if discovered else None}
    result["table_presence"] = {name: table in tables for name, (table, _) in PROJECTIONS.items()}
    runtime_seen = bool(result.get("latest_intraday_runtime"))
    for symbol in ("spy", "qqq"):
        signals, trades = result.get(f"{symbol}_intraday_signals") or 0, result.get(f"{symbol}_intraday_trades") or 0
        result[f"{symbol}_ledger_assessment"] = ("TRADES_PRESENT" if trades else
            "NO_QUALIFYING_SETUPS" if runtime_seen and not signals else "WORKER_DATA_FAILURE")
    return result


def _et_day(value):
    if not value: return None
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None: parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(EASTERN).date().isoformat()


def _bounds(first, last):
    start = datetime.combine(datetime.fromisoformat(first).date(), time.min, EASTERN).astimezone(timezone.utc)
    end = datetime.combine(datetime.fromisoformat(last).date() + timedelta(days=1), time.min, EASTERN).astimezone(timezone.utc)
    return start, end


def run_production_strategic_audit(database_url, *, dashboard_fingerprint=None, connector=None,
                                   reader=read_snapshot, now=None):
    started = monotonic_time.perf_counter()
    fingerprint, stage, window = None, "FINGERPRINT", None
    try:
        fingerprint = database_fingerprint(database_url)
        stage = "RECONCILIATION"
        reconciliation = production_reconciliation(database_url, connector=connector, now=now)
        reconciliation["database_fingerprint"] = fingerprint
        reconciliation["prior_confirmed_production_fingerprint_reference"] = PRIOR_CONFIRMED_PRODUCTION_FINGERPRINT
        reconciliation["matches_prior_confirmed_reference"] = fingerprint == PRIOR_CONFIRMED_PRODUCTION_FINGERPRINT
        complete = reconciliation["sessions"]["complete"]
        core_missing = any(reconciliation["table_presence"].get(name) is False for name in ("mirror", "broad_trades", "broad_journal"))
        visible_ledger_mismatch = bool(reconciliation["latest_authoritative_event_timestamp"] and
            not (reconciliation["mirror_total_trades"] or 0) and not (reconciliation["broad_paper_trades"] or 0))
        reason = None
        if dashboard_fingerprint and dashboard_fingerprint != fingerprint: reason = "DATABASE_FINGERPRINT_MISMATCH"
        elif core_missing or visible_ledger_mismatch: reason = "PRODUCTION_LEDGER_MISMATCH"
        database = {"engine": "postgresql", "schema": "public", "fingerprint": fingerprint, "durability": "DURABLE"}
        if reason:
            return {"status": "STOPPED", "reason": reason, "database": database,
                "reconciliation": reconciliation, "sessions": reconciliation["sessions"], "report": None}
        if complete:
            stage = "SESSION_WINDOW"
            start, end = _bounds(complete[0], complete[-1]); window = {"start": start, "end_exclusive": end}
            stage = "DATA_LOADING"
            snapshot = reader(database_url, start_utc=start, end_utc=end)
        else:
            snapshot = _empty_snapshot(fingerprint)
        reconciliation["sessions"]["earliest_spy_qqq_session"] = min(
            (row.get("session") for lane in ("SPY", "QQQ")
             for row in snapshot.get("lanes", {}).get(lane, ()) if row.get("session")), default=None)
        stage = "STRATEGIC_ANALYTICS"
        report = build_strategic_audit(snapshot)
        report["audit_metadata"].update({"database_fingerprint": fingerprint,
            "production_reconciliation": reconciliation, "session_bounds_utc": window,
            "operational_status": "INSUFFICIENT DATA" if not complete else "COMPLETED"})
        return {"status": "COMPLETED", "reason": None, "database": database,
            "reconciliation": reconciliation, "sessions": reconciliation["sessions"], "report": report}
    except Exception as error:
        analytics_diagnostics = getattr(error, "analytics_diagnostics", {})
        failure = _failure(getattr(error, "stage", stage), error)
        log_record = {"event":"production_strategic_audit_failed","stage":failure.stage,
            "exception_class":failure.exception_class,"safe_summary":failure.safe_summary,
            "database_fingerprint":fingerprint or "UNAVAILABLE","session_window":window,
            "duration_ms":round((monotonic_time.perf_counter()-started)*1000)}
        log_record.update(analytics_diagnostics)
        LOGGER.error(json.dumps(log_record, default=str, sort_keys=True))
        raise failure from None


def _empty_snapshot(fingerprint):
    return {"metadata":{"database_fingerprint":fingerprint},"lanes":{},"AUTHORITATIVE":[],
        "OPPORTUNITY_CONTEXT":[],"CONTEXT_SHADOW":[],"POSITION_CONTEXT":[],
        "DAILY_SCORECARD_ANALYTICS":[],"underlying_records":{},
        "limitations":["No complete Eastern trading sessions were available."]}
