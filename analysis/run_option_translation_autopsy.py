"""Production-safe read-only CLI for Option Translation Autopsy."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone

from psycopg2 import connect
from psycopg2.extras import RealDictCursor

from analysis.run_mirror_pnl_attribution import database_url
from option_translation_autopsy import analyze_option_translation
from trade_repository import utc_iso


def read_bounded(url, *, days=30, limit=500, mark_limit=50000):
    if not url:
        raise RuntimeError("DATABASE_URL is not configured")
    start = datetime.now(timezone.utc) - timedelta(days=int(days))
    start_value = utc_iso(start)
    connection = connect(url, cursor_factory=RealDictCursor, sslmode="require",
                         options="-c default_transaction_read_only=on")
    try:
        connection.set_session(readonly=True, autocommit=False)
        with connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass('public.mirror_execution_trades') AS trades, "
                           "to_regclass('public.mirror_execution_marks') AS marks")
            inventory = dict(cursor.fetchone())
            cursor.execute("""SELECT opportunity_id,snapshot_json,schema_version,created_at
                FROM intelligence_setup_snapshots WHERE created_at>=%s
                ORDER BY created_at DESC,opportunity_id LIMIT %s""", (start_value, int(limit)))
            snapshots = [_decode(dict(row), "snapshot_json", "snapshot") for row in cursor.fetchall()]
            cursor.execute("""SELECT opportunity_id,outcome_json,schema_version,updated_at
                FROM intelligence_outcome_labels WHERE updated_at>=%s
                ORDER BY updated_at DESC,opportunity_id LIMIT %s""", (start_value, int(limit)))
            outcomes = [_decode(dict(row), "outcome_json", "outcome") for row in cursor.fetchall()]
            opportunity_ids = sorted(
                {str(row["snapshot"].get("opportunity_id")) for row in snapshots if row["snapshot"].get("opportunity_id")} |
                {str(row["outcome"].get("opportunity_id")) for row in outcomes if row["outcome"].get("opportunity_id")})
            mirrors = []
            if opportunity_ids and inventory["trades"] is not None:
                cursor.execute("""SELECT mirror_trade_id,opportunity_id,symbol,direction,option_symbol,
                    option_type,strike,expiration,dte,quantity,contract_multiplier,underlying_entry_price,
                    entry_bid,entry_ask,entry_mid,entry_fill,spread_dollars,spread_percent,total_debit,
                    entry_event_at,opened_at,status,disposition_code,exit_quote_at,exit_bid,exit_ask,
                    exit_mid,exit_fill,realized_pnl,realized_return_percent,authoritative_exit_reason,
                    mfe_pct,mae_pct,peak_return_pct,peak_unrealized_pnl,metadata_json
                    FROM mirror_execution_trades WHERE opportunity_id=ANY(%s)
                    ORDER BY entry_event_at,opportunity_id LIMIT %s""", (opportunity_ids, int(limit)))
                mirrors = [dict(row) for row in cursor.fetchall()]
            trade_ids = sorted({str(row["mirror_trade_id"]) for row in mirrors if row.get("mirror_trade_id")})
            marks = []
            if trade_ids and inventory["marks"] is not None:
                cursor.execute("""SELECT mark_id,mirror_trade_id,opportunity_id,observed_at,
                    conservative_mark,return_pct,unrealized_pnl,mfe_pct,mae_pct,peak_return_pct,
                    peak_unrealized_pnl,time_since_entry_seconds,update_status
                    FROM mirror_execution_marks WHERE mirror_trade_id=ANY(%s) AND observed_at>=%s
                    ORDER BY observed_at,mark_id LIMIT %s""", (trade_ids, start_value, int(mark_limit)))
                marks = [dict(row) for row in cursor.fetchall()]
            connection.rollback()
            return snapshots, outcomes, mirrors, marks, {
                "mirror_execution_trades": "AVAILABLE" if inventory["trades"] is not None else "MISSING",
                "mirror_execution_marks": "AVAILABLE" if inventory["marks"] is not None else "MISSING",
            }
    finally:
        connection.close()


def _decode(row, source, target):
    value = row.pop(source, {})
    if isinstance(value, str): value = json.loads(value)
    row[target] = value or {}
    return row


def report_summary(report, source_status=None):
    return {"sample": report["sample"], "excluded": report["excluded"],
            "outcome_matrix": report["outcome_matrix"], "entry_timing": report["entry_timing"],
            "exit_efficiency": report["exit_efficiency"], "magnitude": report["magnitude"],
            "spread": report["spread"], "dte": report["dte"], "contract": report["contract"], "capital": report["capital"],
            "feature_attribution": report["feature_attribution"],
            "selective_what_if": report["selective_what_if"], "exit_what_if": report["exit_what_if"],
            "coverage": report["coverage"], "source_status": source_status or {}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args()
    snapshots, outcomes, mirrors, marks, source_status = read_bounded(
        database_url(), days=args.days, limit=args.limit)
    report = analyze_option_translation(snapshots, outcomes, mirrors, marks)
    print(json.dumps(report_summary(report, source_status), indent=2, default=str))


if __name__ == "__main__":
    main()
