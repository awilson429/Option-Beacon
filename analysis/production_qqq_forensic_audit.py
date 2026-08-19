"""On-demand production orchestration for QQQ winner-DNA/exit forensics."""
from __future__ import annotations

import json
import logging
import time as monotonic_time
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from analysis.production_forensic_access import database_fingerprint, read_only_connection
from analysis.qqq_winner_dna_exit_forensics import analyze_qqq_forensics
from analysis.run_qqq_winner_dna_exit_forensics import read_qqq_snapshot

EASTERN = ZoneInfo("America/New_York")
PRIOR_CONFIRMED_PRODUCTION_FINGERPRINT = "381d634898fd6d6a"
LOGGER = logging.getLogger(__name__)


class QQQForensicAuditFailure(RuntimeError):
    def __init__(self, stage, exception_class, summary):
        self.stage, self.exception_class, self.safe_summary = stage, exception_class, summary
        super().__init__(f"QQQ forensic audit failed during {stage} ({exception_class}).")


def _failure(stage, error):
    if isinstance(error, QQQForensicAuditFailure): return error
    name = type(error).__name__
    summary = ("production schema is incompatible with an audit projection" if name in {"ProgrammingError","UndefinedColumn","UndefinedTable"}
               else "database operation unavailable" if name in {"OperationalError","InterfaceError"}
               else "persisted telemetry could not be normalized" if isinstance(error,(TypeError,ValueError))
               else "QQQ forensic audit operation unavailable")
    return QQQForensicAuditFailure(stage, name, summary)


def production_qqq_reconciliation(database_url, *, connector=None, now=None):
    kwargs = {"connector": connector} if connector else {}
    with read_only_connection(database_url, **kwargs) as connection, connection.cursor() as cursor:
        try:
            cursor.execute("SELECT table_name,column_name FROM information_schema.columns WHERE table_schema='public'")
            columns = {}
            for row in cursor.fetchall(): columns.setdefault(row["table_name"], set()).add(row["column_name"])
            def scalar(table, expression="COUNT(*)", where="", required=()):
                if table not in columns or not set(required) <= columns[table]: return None
                cursor.execute(f"SELECT {expression} AS value FROM {table}{where}")
                return dict(cursor.fetchone()).get("value")
            result = {
                "qqq_signal_count": scalar("intraday_signals","COUNT(*)"," WHERE symbol='QQQ'",("symbol",)),
                "qqq_trade_count": scalar("intraday_paper_trades","COUNT(*)"," WHERE symbol='QQQ'",("symbol",)),
                "qqq_closed_trade_count": scalar("intraday_paper_trades","COUNT(*)"," WHERE symbol='QQQ' AND status='CLOSED'",("symbol","status")),
                "qqq_open_trade_count": scalar("intraday_paper_trades","COUNT(*)"," WHERE symbol='QQQ' AND status='OPEN'",("symbol","status")),
                "qqq_mirror_count": scalar("intraday_paper_trades","COUNT(*)"," WHERE symbol='QQQ' AND variant='INTRADAY_MIRROR'",("symbol","variant")),
                "qqq_managed_count": scalar("intraday_paper_trades","COUNT(*)"," WHERE symbol='QQQ' AND variant='INTRADAY_MANAGED'",("symbol","variant")),
                "qqq_journal_count": scalar("intraday_paper_journal","COUNT(*)"," WHERE trade_id IN (SELECT trade_id FROM intraday_paper_trades WHERE symbol='QQQ')",("trade_id",)) if "trade_id" in columns.get("intraday_paper_trades",set()) else None,
                "qqq_mark_count": scalar("position_context_marks","COUNT(*)"," WHERE trade_id IN (SELECT trade_id FROM intraday_paper_trades WHERE symbol='QQQ')",("trade_id",)) if "trade_id" in columns.get("intraday_paper_trades",set()) else None,
                "earliest_qqq_trade_at": scalar("intraday_paper_trades","MIN(opened_at)"," WHERE symbol='QQQ'",("symbol","opened_at")),
                "latest_qqq_trade_at": scalar("intraday_paper_trades","MAX(opened_at)"," WHERE symbol='QQQ'",("symbol","opened_at")),
                "latest_runtime_at": scalar("intraday_runtime_state","MAX(updated_at)",required=("updated_at",)),
                "runtime_status": scalar("intraday_runtime_state","MAX(status)",required=("status",)),
            }
            if {"symbol","opened_at"} <= columns.get("intraday_paper_trades",set()):
                cursor.execute("SELECT DISTINCT (opened_at::timestamptz AT TIME ZONE 'America/New_York')::date AS session_date FROM intraday_paper_trades WHERE symbol='QQQ' AND opened_at IS NOT NULL ORDER BY session_date")
                discovered = [str(row["session_date"]) for row in cursor.fetchall()]
            else: discovered = []
        except Exception as error:
            raise _failure("RECONCILIATION", error) from None
    today = (now or datetime.now(timezone.utc)).astimezone(EASTERN).date().isoformat()
    incomplete = [day for day in discovered if day == today]
    complete = [day for day in discovered if day != today]
    result["sessions"] = {"discovered":discovered,"complete":complete,
        "incomplete_excluded":[{"session":day,"reason":"CURRENT_ET_SESSION_INCOMPLETE"} for day in incomplete]}
    return result


def _bounds(first, last):
    start = datetime.combine(datetime.fromisoformat(first).date(), time.min, EASTERN).astimezone(timezone.utc)
    end = datetime.combine(datetime.fromisoformat(last).date()+timedelta(days=1), time.min, EASTERN).astimezone(timezone.utc)
    return start, end


def run_production_qqq_forensic_audit(database_url, *, dashboard_fingerprint=None, connector=None,
                                      reader=read_qqq_snapshot, now=None):
    started, stage, fingerprint = monotonic_time.perf_counter(), "FINGERPRINT", None
    try:
        fingerprint = database_fingerprint(database_url)
        stage = "RECONCILIATION"
        reconciliation = production_qqq_reconciliation(database_url, connector=connector, now=now)
        reconciliation.update({"database_fingerprint":fingerprint,
            "prior_confirmed_production_fingerprint_reference":PRIOR_CONFIRMED_PRODUCTION_FINGERPRINT,
            "matches_prior_confirmed_reference":fingerprint==PRIOR_CONFIRMED_PRODUCTION_FINGERPRINT})
        database={"engine":"postgresql","schema":"public","fingerprint":fingerprint,"durability":"DURABLE"}
        if dashboard_fingerprint and dashboard_fingerprint != fingerprint:
            return {"status":"STOPPED","reason":"DATABASE_FINGERPRINT_MISMATCH","database":database,"reconciliation":reconciliation,"report":None}
        complete = reconciliation["sessions"]["complete"]
        if complete:
            start,end=_bounds(complete[0],complete[-1]); stage="DATA_LOADING"
            reader_kwargs={"start_utc":start,"end_utc":end}
            if connector: reader_kwargs["connector"]=connector
            snapshot=reader(database_url,**reader_kwargs)
        else:
            snapshot={"trades":[],"signals":[],"contexts":[],"marks":[],"journals":[],"metadata":{"read_only":True,"provider_calls":0,"database_writes":0}}
        if (reconciliation.get("qqq_trade_count") or 0) and not snapshot["trades"]:
            return {"status":"STOPPED","reason":"PRODUCTION_QQQ_LEDGER_MISMATCH","database":database,"reconciliation":reconciliation,"report":None}
        stage="QQQ_ANALYTICS"
        underlying_records={name:list(snapshot.get(name,())) for name in ("trades","signals","contexts","marks","journals")}
        report=analyze_qqq_forensics(snapshot.pop("trades"),metadata={**snapshot.pop("metadata"),"production_reconciliation":reconciliation},**snapshot)
        report["underlying_records"]=underlying_records
        return {"status":"COMPLETED","reason":None,"database":database,"reconciliation":reconciliation,"report":report}
    except Exception as error:
        failure=_failure(stage,error)
        LOGGER.error(json.dumps({"event":"production_qqq_forensic_audit_failed","stage":failure.stage,
            "exception_class":failure.exception_class,"safe_summary":failure.safe_summary,
            "database_fingerprint":fingerprint or "UNAVAILABLE","duration_ms":round((monotonic_time.perf_counter()-started)*1000)},sort_keys=True))
        raise failure from None
