"""Bounded, production-safe CLI for QQQ winner/loser DNA research."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from analysis.production_forensic_access import database_fingerprint, read_only_connection
from analysis.qqq_winner_dna_exit_forensics import analyze_qqq_forensics
from dashboard_storage_config import dashboard_database_url

START = datetime(2026, 8, 10, tzinfo=timezone.utc)


def _json(value):
    if isinstance(value, dict): return value
    try: return json.loads(value or "{}")
    except (TypeError, ValueError): return {}


def read_qqq_snapshot(url, *, start_utc=START, end_utc=None, row_limit=10000, mark_limit=20000, connector=None):
    end_utc = end_utc or datetime.now(timezone.utc) + timedelta(days=1)
    kwargs = {"connector":connector} if connector else {}
    with read_only_connection(url, **kwargs) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT table_name,column_name FROM information_schema.columns WHERE table_schema='public'")
        columns = defaultdict(set)
        for row in cursor.fetchall(): columns[row["table_name"]].add(row["column_name"])
        def fetch(table, wanted, where, params, order, limit):
            selected = [name for name in wanted if name in columns.get(table,set())]
            if not selected: return []
            cursor.execute(f"SELECT {','.join(selected)} FROM {table} WHERE {where} ORDER BY {order} LIMIT %s", (*params,int(limit)))
            return [dict(row) for row in cursor.fetchall()]
        trades = fetch("intraday_paper_trades", ("trade_id","opportunity_id","variant","symbol","direction","option_symbol","option_type","expiration","dte","strike","delta","underlying_entry_price","entry_bid","entry_ask","entry_fill","spread_percent","open_interest","option_volume","total_debit","status","management_state","opened_at","closed_at","exit_fill","exit_reason","realized_pnl","realized_return_percent","mfe_pct","mae_pct","profit_giveback_pct","fill_model"),
            "symbol='QQQ' AND opened_at::timestamptz >= %s AND opened_at::timestamptz < %s",(start_utc,end_utc),"opened_at",row_limit)
        trade_ids=[str(r.get("trade_id")) for r in trades if r.get("trade_id")]; opportunity_ids=[str(r.get("opportunity_id")) for r in trades if r.get("opportunity_id")]
        signals = fetch("intraday_signals",("opportunity_id","symbol","direction","setup","session_bucket","regime","reasons_json","cross_market_json","detected_at"),
            "opportunity_id = ANY(%s)",(opportunity_ids,),"detected_at",row_limit) if opportunity_ids else []
        contexts = fetch("opportunity_context",("opportunity_id","context_json","captured_at","eastern_session","experiment_scope"),
            "opportunity_id = ANY(%s)",(opportunity_ids,),"captured_at",row_limit) if opportunity_ids else []
        marks = fetch("position_context_marks",("mark_id","trade_id","opportunity_id","lane","observed_at","setup_health","mark_json"),
            "trade_id = ANY(%s) AND observed_at::timestamptz >= %s AND observed_at::timestamptz < %s",
            (trade_ids,start_utc,end_utc),"observed_at",mark_limit) if trade_ids else []
        journals = fetch("intraday_paper_journal",("journal_id","trade_id","opportunity_id","event_type","event_at","payload_json"),
            "(trade_id = ANY(%s) OR opportunity_id = ANY(%s)) AND event_at::timestamptz >= %s AND event_at::timestamptz < %s",
            (trade_ids,opportunity_ids,start_utc,end_utc),"event_at",row_limit) if trade_ids and opportunity_ids else []
    normalized_trades=[{**row,"pnl":row.get("realized_pnl"),"return_pct":row.get("realized_return_percent"),"mfe":row.get("mfe_pct"),"mae":row.get("mae_pct"),"signal_age_seconds":None} for row in trades]
    normalized_contexts=[{**row,**_json(row.get("context_json"))} for row in contexts]
    normalized_marks=[{**row,**_json(row.get("mark_json"))} for row in marks]
    return {"trades":normalized_trades,"signals":signals,"contexts":normalized_contexts,"marks":normalized_marks,"journals":journals,
        "metadata":{"database_fingerprint":database_fingerprint(url),"start_utc":start_utc,"end_utc_exclusive":end_utc,
            "row_limit":row_limit,"mark_limit":mark_limit,"read_only":True,"provider_calls":0,"database_writes":0}}


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--output",type=Path);parser.add_argument("--row-limit",type=int,default=10000);parser.add_argument("--mark-limit",type=int,default=20000)
    args=parser.parse_args();url=dashboard_database_url();snapshot=read_qqq_snapshot(url,row_limit=args.row_limit,mark_limit=args.mark_limit)
    report=analyze_qqq_forensics(snapshot.pop("trades"),metadata=snapshot.pop("metadata"),**snapshot)
    encoded=json.dumps(report,indent=2,sort_keys=True,default=str,allow_nan=False)
    if args.output: args.output.write_text(encoded+"\n",encoding="utf-8")
    else: print(encoded)


if __name__ == "__main__": main()
