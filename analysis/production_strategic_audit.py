"""On-demand production orchestration for the strategic SPY/QQQ audit."""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from analysis.production_forensic_access import database_fingerprint, read_only_connection
from analysis.run_spy_qqq_strategic_audit import PROJECTIONS, read_snapshot
from strategic_spy_qqq_audit import build_strategic_audit

EASTERN = ZoneInfo("America/New_York")
PRIOR_CONFIRMED_PRODUCTION_FINGERPRINT = "381d634898fd6d6a"


def production_reconciliation(database_url, *, connector=None, now=None):
    """Use SQL aggregates only; return safe counts and discovered ET sessions."""
    kwargs = {"connector": connector} if connector else {}
    with read_only_connection(database_url, **kwargs) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
        tables = {row["table_name"] for row in cursor.fetchall()}

        def scalar(table, expression="COUNT(*)", where=""):
            if table not in tables: return None
            cursor.execute(f"SELECT {expression} AS value FROM {table}{where}")
            return dict(cursor.fetchone()).get("value")

        result = {
            "latest_authoritative_event_timestamp": scalar("authoritative_trade_events", "MAX(event_timestamp)"),
            "mirror_total_trades": scalar("mirror_execution_trades"),
            "mirror_closed_trades": scalar("mirror_execution_trades", "COUNT(*)", " WHERE status='CLOSED'"),
            "mirror_marks": scalar("mirror_execution_marks"),
            "broad_paper_trades": scalar("paper_execution_trades", "COUNT(*)", " WHERE EXISTS (SELECT 1 FROM paper_execution_journal j WHERE j.trade_id=paper_execution_trades.trade_id AND UPPER(COALESCE(j.metadata_json::jsonb->>'simulation_profile',''))='BROAD')"),
            "filtered_records": scalar("filtered_execution_trades"),
            "spy_intraday_signals": scalar("intraday_signals", "COUNT(*)", " WHERE symbol='SPY'"),
            "spy_intraday_trades": scalar("intraday_paper_trades", "COUNT(*)", " WHERE symbol='SPY'"),
            "spy_intraday_closed": scalar("intraday_paper_trades", "COUNT(*)", " WHERE symbol='SPY' AND status='CLOSED'"),
            "spy_intraday_mirror": scalar("intraday_paper_trades", "COUNT(*)", " WHERE symbol='SPY' AND variant='INTRADAY_MIRROR'"),
            "spy_intraday_managed": scalar("intraday_paper_trades", "COUNT(*)", " WHERE symbol='SPY' AND variant='INTRADAY_MANAGED'"),
            "spy_realized_pnl": scalar("intraday_paper_trades", "COALESCE(SUM(realized_pnl),0)", " WHERE symbol='SPY' AND status='CLOSED'"),
            "qqq_intraday_signals": scalar("intraday_signals", "COUNT(*)", " WHERE symbol='QQQ'"),
            "qqq_intraday_trades": scalar("intraday_paper_trades", "COUNT(*)", " WHERE symbol='QQQ'"),
            "qqq_intraday_closed": scalar("intraday_paper_trades", "COUNT(*)", " WHERE symbol='QQQ' AND status='CLOSED'"),
            "qqq_intraday_mirror": scalar("intraday_paper_trades", "COUNT(*)", " WHERE symbol='QQQ' AND variant='INTRADAY_MIRROR'"),
            "qqq_intraday_managed": scalar("intraday_paper_trades", "COUNT(*)", " WHERE symbol='QQQ' AND variant='INTRADAY_MANAGED'"),
            "qqq_realized_pnl": scalar("intraday_paper_trades", "COALESCE(SUM(realized_pnl),0)", " WHERE symbol='QQQ' AND status='CLOSED'"),
            "opportunity_context_count": scalar("opportunity_context"),
            "context_shadow_count": scalar("context_shadow_decisions"),
            "position_context_marks_count": scalar("position_context_marks"),
            "intraday_journal_count": scalar("intraday_paper_journal"),
            "latest_intraday_runtime": scalar("intraday_runtime_state", "MAX(updated_at)"),
            "intraday_runtime_status": scalar("intraday_runtime_state", "MAX(status)"),
            "earliest_broad_universe_timestamp": scalar("mirror_execution_trades", "MIN(entry_event_at)"),
            "earliest_spy_qqq_timestamp": scalar("intraday_signals", "MIN(detected_at)"),
        }
        session_queries = []
        if "mirror_execution_trades" in tables:
            session_queries.append("SELECT (entry_event_at::timestamptz AT TIME ZONE 'America/New_York')::date AS session_date FROM mirror_execution_trades WHERE entry_event_at IS NOT NULL")
        if "paper_execution_trades" in tables:
            session_queries.append("SELECT (opened_at::timestamptz AT TIME ZONE 'America/New_York')::date FROM paper_execution_trades WHERE opened_at IS NOT NULL")
        if "intraday_signals" in tables:
            session_queries.append("SELECT (detected_at::timestamptz AT TIME ZONE 'America/New_York')::date FROM intraday_signals WHERE detected_at IS NOT NULL")
        if session_queries:
            cursor.execute("SELECT DISTINCT session_date FROM (" + " UNION ".join(session_queries) + ") s WHERE session_date IS NOT NULL ORDER BY session_date")
            discovered = [str(row["session_date"]) for row in cursor.fetchall()]
        else: discovered = []
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
    fingerprint = database_fingerprint(database_url)
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
    elif not complete: reason = "NO_COMPLETE_SESSIONS"
    database = {"engine": "postgresql", "schema": "public", "fingerprint": fingerprint, "durability": "DURABLE"}
    if reason:
        return {"status": "STOPPED", "reason": reason, "database": database,
                "reconciliation": reconciliation, "sessions": reconciliation["sessions"], "report": None}
    start, end = _bounds(complete[0], complete[-1])
    snapshot = reader(database_url, start_utc=start, end_utc=end)
    reconciliation["sessions"]["earliest_spy_qqq_session"] = min(
        (row.get("session") for lane in ("SPY", "QQQ") for row in snapshot.get("lanes", {}).get(lane, ()) if row.get("session")), default=None)
    report = build_strategic_audit(snapshot)
    report["audit_metadata"].update({"database_fingerprint": fingerprint,
        "production_reconciliation": reconciliation, "session_bounds_utc": {"start": start, "end_exclusive": end}})
    return {"status": "COMPLETED", "reason": None, "database": database,
            "reconciliation": reconciliation, "sessions": reconciliation["sessions"], "report": report}
