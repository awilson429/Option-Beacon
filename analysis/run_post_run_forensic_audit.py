"""Explicit-session, transaction-read-only production forensic audit CLI."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, time, timedelta, timezone

from psycopg2 import connect
from psycopg2.extras import RealDictCursor

from dashboard_storage_config import dashboard_database_url
from post_run_forensic_audit import EASTERN, build_forensic_report


TABLES = ("intelligence_setup_snapshots", "intelligence_outcome_labels", "mirror_execution_trades",
          "mirror_execution_marks", "paper_execution_trades", "paper_execution_journal")


def session_bounds(start_date, end_date):
    """Inclusive ET dates converted to a half-open UTC interval."""
    start = datetime.combine(start_date, time.min, EASTERN).astimezone(timezone.utc)
    end = datetime.combine(end_date + timedelta(days=1), time.min, EASTERN).astimezone(timezone.utc)
    return start, end


def read_sessions(url, *, start_date, end_date, trade_limit=10000, mark_limit=250000):
    """Read projected rows for explicit sessions; predicates precede all limits."""
    if not url:
        raise RuntimeError("DATABASE_URL is not configured")
    start, end = session_bounds(start_date, end_date)
    start_value, end_value = start.isoformat(), end.isoformat()
    connection = connect(url, cursor_factory=RealDictCursor, sslmode="require",
                         options="-c default_transaction_read_only=on")
    try:
        connection.set_session(readonly=True, autocommit=False)
        with connection.cursor() as cursor:
            cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name=ANY(%s)", (list(TABLES),))
            available = {row["table_name"] for row in cursor.fetchall()}
            missing = sorted(set(TABLES) - available)
            if "intelligence_setup_snapshots" not in available or "intelligence_outcome_labels" not in available:
                connection.rollback()
                return ([], [], [], [], [], [], {"missing_tables": missing, "query": "READ_ONLY_EXPLICIT_ET_SESSIONS"})
            cursor.execute("""SELECT opportunity_id,snapshot_json,schema_version,created_at FROM intelligence_setup_snapshots
                WHERE created_at >= %s AND created_at < %s ORDER BY created_at,opportunity_id LIMIT %s""", (start_value, end_value, trade_limit))
            snapshots = [_decode(dict(row), "snapshot_json", "snapshot") for row in cursor.fetchall()]
            cursor.execute("""SELECT opportunity_id,outcome_json,schema_version,updated_at FROM intelligence_outcome_labels
                WHERE (outcome_json::jsonb->>'entry_timestamp')::timestamptz >= %s
                  AND (outcome_json::jsonb->>'entry_timestamp')::timestamptz < %s
                ORDER BY (outcome_json::jsonb->>'entry_timestamp')::timestamptz,opportunity_id LIMIT %s""", (start, end, trade_limit))
            outcomes = [_decode(dict(row), "outcome_json", "outcome") for row in cursor.fetchall()]
            ids = sorted({str((row.get("snapshot") or row).get("opportunity_id")) for row in snapshots if (row.get("snapshot") or row).get("opportunity_id")} |
                         {str((row.get("outcome") or row).get("opportunity_id")) for row in outcomes if (row.get("outcome") or row).get("opportunity_id")})
            mirrors = _fetch(cursor, available, "mirror_execution_trades", """SELECT mirror_trade_id,opportunity_id,symbol,direction,option_symbol,option_type,strike,expiration,dte,
                quantity,contract_multiplier,underlying_entry_price,entry_bid,entry_ask,entry_mid,entry_fill,spread_dollars,spread_percent,total_debit,
                entry_event_at,opened_at,status,disposition_code,exit_quote_at,exit_bid,exit_ask,exit_mid,exit_fill,realized_pnl,realized_return_percent,
                authoritative_exit_reason,mfe_pct,mae_pct,peak_return_pct,peak_unrealized_pnl FROM mirror_execution_trades
                WHERE opportunity_id=ANY(%s) AND entry_event_at >= %s AND entry_event_at < %s ORDER BY entry_event_at,opportunity_id LIMIT %s""", (ids, start_value, end_value, trade_limit)) if ids else []
            trade_ids = [row["mirror_trade_id"] for row in mirrors if row.get("mirror_trade_id")]
            marks = _fetch(cursor, available, "mirror_execution_marks", """SELECT mark_id,mirror_trade_id,opportunity_id,observed_at,conservative_mark,return_pct,unrealized_pnl,
                mfe_pct,mae_pct,peak_return_pct,peak_unrealized_pnl,time_since_entry_seconds,update_status FROM mirror_execution_marks
                WHERE mirror_trade_id=ANY(%s) AND observed_at >= %s AND observed_at < %s ORDER BY observed_at,mark_id LIMIT %s""", (trade_ids, start_value, (end + timedelta(days=1)).isoformat(), mark_limit)) if trade_ids else []
            paper = _fetch(cursor, available, "paper_execution_trades", "SELECT trade_id,source_signal_id,opportunity_id,status,total_debit,realized_pnl_dollars,realized_return_pct,opened_at,closed_at FROM paper_execution_trades WHERE source_signal_id=ANY(%s) ORDER BY opened_at,trade_id LIMIT %s", (ids, trade_limit)) if ids else []
            trade_ids = [row["trade_id"] for row in paper if row.get("trade_id")]
            journal = _fetch(cursor, available, "paper_execution_journal", "SELECT trade_id,accepted,reason_code,created_at,metadata_json FROM paper_execution_journal WHERE trade_id=ANY(%s) ORDER BY created_at,trade_id LIMIT %s", (trade_ids, trade_limit)) if trade_ids else []
            connection.rollback()
            return snapshots, outcomes, mirrors, marks, paper, journal, {"missing_tables": missing, "query": "READ_ONLY_EXPLICIT_ET_SESSIONS", "start_utc": start, "end_utc_exclusive": end}
    finally:
        connection.close()


def _fetch(cursor, available, table, query, params):
    if table not in available:
        return []
    cursor.execute(query, params)
    return [dict(row) for row in cursor.fetchall()]


def _decode(row, source, target):
    value = row.pop(source, {})
    row[target] = json.loads(value) if isinstance(value, str) else value or {}
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True, type=date.fromisoformat, help="First ET session date")
    parser.add_argument("--end", required=True, type=date.fromisoformat, help="Last ET session date, inclusive")
    parser.add_argument("--trade-limit", type=int, default=10000)
    parser.add_argument("--mark-limit", type=int, default=250000)
    args = parser.parse_args()
    if args.end < args.start:
        parser.error("--end must be on or after --start")
    values = read_sessions(dashboard_database_url(), start_date=args.start, end_date=args.end,
                           trade_limit=args.trade_limit, mark_limit=args.mark_limit)
    report = build_forensic_report(*values[:6])
    report["source_status"] = values[6]
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
