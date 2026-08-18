"""Production-safe CLI for the strategic SPY/QQQ versus broad audit."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from dashboard_storage_config import dashboard_database_url
from analysis.production_forensic_access import database_fingerprint, read_only_connection
from strategic_spy_qqq_audit import build_strategic_audit, session, timestamp


PROJECTIONS = {
    "opportunities": ("opportunities", "id,symbol,direction,playbook,signal_timestamp,created_at"),
    "authoritative": ("authoritative_trade_events", "opportunity_id,event_type,event_timestamp,symbol,direction,realized_return,exit_reason"),
    "snapshots": ("intelligence_setup_snapshots", "opportunity_id,snapshot_json,created_at"),
    "outcomes": ("intelligence_outcome_labels", "opportunity_id,outcome_json,updated_at"),
    "mirror": ("mirror_execution_trades", "mirror_trade_id,opportunity_id,symbol,direction,option_symbol,option_type,dte,open_interest,option_volume,entry_fill,spread_percent,total_debit,entry_event_at,opened_at,exit_quote_at,status,realized_pnl,realized_return_percent,mfe_pct,mae_pct,fill_model"),
    "filtered": ("filtered_execution_trades", "filtered_trade_id,opportunity_id,symbol,direction,option_type,dte,entry_fill,spread_percent,total_debit,signal_age_seconds,signal_age_bucket,authoritative_event_at,opened_at,closed_at,status,realized_pnl,realized_return_percent,mfe_pct,mae_pct,broad_decision,execution_rejection_reason"),
    "intraday_signals": ("intraday_signals", "opportunity_id,symbol,direction,setup,session_bucket,regime,detected_at,state,close_reason"),
    "intraday": ("intraday_paper_trades", "trade_id,opportunity_id,variant,symbol,direction,option_type,dte,entry_fill,spread_percent,open_interest,option_volume,total_debit,opened_at,closed_at,status,realized_pnl,realized_return_percent,mfe_pct,mae_pct,exit_reason,fill_model"),
    "context": ("opportunity_context", "opportunity_id,context_json,captured_at,eastern_session,experiment_scope"),
    "context_shadow": ("context_shadow_decisions", "opportunity_id,decision,decision_json,evaluated_at,experiment_scope"),
    "position_context": ("position_context_marks", "mark_id,trade_id,opportunity_id,lane,observed_at,setup_health,mark_json"),
    "broad_trades": ("paper_execution_trades", "trade_id,source_signal_id,status,total_debit,realized_pnl_dollars,realized_return_pct,opened_at,closed_at,contract_metadata_json"),
    "broad_journal": ("paper_execution_journal", "trade_id,accepted,reason_code,created_at,metadata_json"),
}


def read_snapshot(url, *, row_limit=20000):
    with read_only_connection(url) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT table_name,column_name FROM information_schema.columns WHERE table_schema='public'")
        columns = {}
        for row in cursor.fetchall(): columns.setdefault(row["table_name"], set()).add(row["column_name"])
        raw, status = {}, {}
        for name, (table, projection) in PROJECTIONS.items():
            requested = projection.split(",")
            selected = [column for column in requested if column in columns.get(table, set())]
            if not selected:
                raw[name], status[name] = [], "ABSENT OR INCOMPATIBLE"
                continue
            order = next((column for column in ("event_timestamp", "entry_event_at", "authoritative_event_at", "detected_at", "opened_at", "captured_at", "evaluated_at", "observed_at", "created_at") if column in selected), selected[0])
            cursor.execute(f"SELECT {','.join(selected)} FROM {table} ORDER BY {order} LIMIT %s", (int(row_limit),))
            raw[name], status[name] = [dict(row) for row in cursor.fetchall()], "PRESENT"
    return normalize(raw, status, database_fingerprint(url))


def _json(value):
    if isinstance(value, dict): return value
    try: return json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError): return {}


def normalize(raw, status, fingerprint):
    signals = {str(row.get("opportunity_id")): row for row in raw["intraday_signals"]}
    journals = {}
    for row in raw["broad_journal"]:
        meta = _json(row.get("metadata_json"))
        if str(meta.get("simulation_profile") or "").upper() == "BROAD": journals[str(row.get("trade_id"))] = row
    def row(record, lane, signal_at=None):
        opened, closed = record.get("opened_at"), record.get("closed_at") or record.get("exit_quote_at")
        signal_at = signal_at or record.get("entry_event_at") or record.get("authoritative_event_at") or opened
        sig = signals.get(str(record.get("opportunity_id")), {})
        meta = _json(record.get("contract_metadata_json"))
        return {"lane": lane, "trade_id": record.get("trade_id") or record.get("mirror_trade_id") or record.get("filtered_trade_id"),
            "opportunity_id": record.get("opportunity_id") or record.get("source_signal_id"), "symbol": record.get("symbol") or sig.get("symbol"),
            "direction": record.get("direction") or sig.get("direction"), "setup": sig.get("setup"), "regime": sig.get("regime"),
            "time_bucket": sig.get("session_bucket"), "signal_at": signal_at, "session": session(signal_at or opened),
            "opened_at": opened, "closed_at": closed, "pnl": record.get("realized_pnl", record.get("realized_pnl_dollars")),
            "return_pct": record.get("realized_return_percent", record.get("realized_return_pct")), "mfe": record.get("mfe_pct"), "mae": record.get("mae_pct"),
            "spread_percent": record.get("spread_percent", meta.get("spread_percent")), "signal_age_seconds": record.get("signal_age_seconds"),
            "signal_age_bucket": record.get("signal_age_bucket"), "entry_fill": record.get("entry_fill"), "debit": record.get("total_debit"),
            "dte": record.get("dte"), "option_volume": record.get("option_volume"), "open_interest": record.get("open_interest"),
            "fill_model": record.get("fill_model"), "status": record.get("status"), "rejection_reason": record.get("execution_rejection_reason")}
    mirror = [row(item, "MIRROR") for item in raw["mirror"]]
    filtered = [row(item, "FILTERED") for item in raw["filtered"]]
    broad = [row(item, "BROAD") for item in raw["broad_trades"] if str(item.get("trade_id")) in journals]
    intraday = [row(item, item.get("symbol") or "INTRADAY", signals.get(str(item.get("opportunity_id")), {}).get("detected_at")) for item in raw["intraday"]]
    authoritative = [{"opportunity_id": item.get("opportunity_id"), "signal_at": item.get("event_timestamp"),
        "closed_at": item.get("event_timestamp") if item.get("event_type") == "TRADE_CLOSED" else None} for item in raw["authoritative"]]
    authoritative += [{"opportunity_id": item.get("id"), "signal_at": item.get("signal_timestamp")} for item in raw["opportunities"]]
    contexts = [{**item, "context_json": _json(item.get("context_json"))} for item in raw["context"]]
    marks = [{**item, "mark_json": _json(item.get("mark_json"))} for item in raw["position_context"]]
    return {"metadata": {"database_fingerprint": fingerprint, "generated_at": datetime.now(timezone.utc).isoformat(), "table_status": status},
        "lanes": {"BROAD": broad, "MIRROR": mirror, "FILTERED": filtered,
                  "SPY": [item for item in intraday if item.get("symbol") == "SPY"],
                  "QQQ": [item for item in intraday if item.get("symbol") == "QQQ"]},
        "AUTHORITATIVE": authoritative, "OPPORTUNITY_CONTEXT": contexts, "CONTEXT_SHADOW": raw["context_shadow"],
        "POSITION_CONTEXT": marks, "DAILY_SCORECARD_ANALYTICS": mirror + broad + filtered,
        "context_coverage": {"opportunity_contexts": len(contexts), "context_shadow_decisions": len(raw["context_shadow"]), "position_context_marks": len(marks)},
        "complexity": {"BROAD": {"symbols_observed": len({r.get('symbol') for r in mirror if r.get('symbol')}), "company_specific_risk": True, "sector_dependencies": True},
                       "SPY_QQQ": {"symbols_observed": 2, "company_specific_risk": False, "sector_dependencies": False},
                       "note": "Static architectural traits plus observed symbol count; provider-request totals are not persisted."},
        "limitations": ["Complete exchange session calendar is not persisted in these ledgers.", "Underlying directional outcome classes are unavailable unless persisted by the dedicated strategy.",
                        "Historical option Greeks, quote age, and execution latency components are not reconstructed."],
        "underlying_records": {"opportunities": raw["opportunities"], "authoritative": raw["authoritative"],
            "intelligence_setup_snapshots": raw["snapshots"], "intelligence_outcome_labels": raw["outcomes"],
            "mirror": raw["mirror"], "filtered": raw["filtered"],
            "intraday_signals": raw["intraday_signals"], "intraday_trades": raw["intraday"], "broad_trades": raw["broad_trades"],
            "broad_journal": raw["broad_journal"], "opportunity_context": contexts, "context_shadow": raw["context_shadow"], "position_context_marks": marks}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--row-limit", type=int, default=20000)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    report = build_strategic_audit(read_snapshot(dashboard_database_url(), row_limit=args.row_limit))
    encoded = json.dumps(report, indent=2, default=str, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    if not args.quiet: print(encoded)


if __name__ == "__main__": main()
