"""Read-only, evidence-governed product and strategy value inventory."""
from __future__ import annotations

from datetime import datetime, timezone

from analysis.production_forensic_access import database_fingerprint, read_only_connection


INVENTORY = (
    # name, domain, table, timestamp, usage, decision/diagnostic evidence, cost notes, role
    ("QQQ Managed", "TRADING / STRATEGY", "intraday_paper_trades", "updated_at", "Normal UI + operations", "Canonical QQQ execution and management lane", "Worker quote reads and position writes", "CORE"),
    ("QQQ MIRROR Control", "TRADING / STRATEGY", "intraday_paper_trades", "updated_at", "Research only", "Full-participation control comparison", "Parallel paper rows and mark writes", "CONTROL"),
    ("QQQ FIRST_TWO", "TRADING / STRATEGY", "qqq_first_two_shadow_trades", "opened_at", "Command Card + research", "Predeclared forward selectivity experiment", "Shadow row per eligible QQQ trade", "EXPERIMENT"),
    ("SPY Intraday", "TRADING / STRATEGY", "intraday_paper_trades", "updated_at", "SPY/QQQ page + research", "Separate benchmark instrument", "Worker quote reads and paper writes", "EXPERIMENT"),
    ("BROAD", "TRADING / STRATEGY", "paper_execution_trades", "updated_at", "Paper Trading + research", "Broad-universe risk-filter benchmark", "Paper ledger and journal writes", "LEGACY"),
    ("FILTERED", "TRADING / STRATEGY", "filtered_execution_trades", "updated_at", "Research only", "Spread-gate counterfactual", "Shadow rows; shared quotes", "EXPERIMENT"),
    ("Authoritative Outcomes", "TRADING / STRATEGY", "authoritative_trade_events", "event_timestamp", "Core UI + all audits", "Ground-truth outcome and identity spine", "Event writes and indexed reads", "CORE"),
    ("QQQ Winner DNA", "RESEARCH / ANALYTICS", "intraday_paper_trades", "updated_at", "Developer Tools", "Winner/loser and exit attribution", "On-demand queries", "RESEARCH"),
    ("Strategic SPY/QQQ Audit", "RESEARCH / ANALYTICS", None, None, "Developer Tools on demand", "Cross-lane strategy evidence", "Read-only multi-table query", "RESEARCH"),
    ("Post-run Forensic Audit", "RESEARCH / ANALYTICS", None, None, "Developer Tools on demand", "Reconciliation and leak diagnosis", "Read-only multi-table query", "RESEARCH"),
    ("Opportunity Context", "RESEARCH / ANALYTICS", "opportunity_context", "captured_at", "Developer Tools + research", "Context captured at opportunity time", "One context row per opportunity", "EXPERIMENT"),
    ("Contextual Research Phase 2", "RESEARCH / ANALYTICS", "context_shadow_decisions", "created_at", "Developer Tools", "Shadow contextual decision evaluation", "Shadow decisions and mark writes", "EXPERIMENT"),
    ("Daily Experiment Scorecard", "RESEARCH / ANALYTICS", None, None, "Paper Trading", "Cross-lane daily governance", "Read-only aggregation", "RESEARCH"),
    ("Winner DNA / Setup Attribution", "RESEARCH / ANALYTICS", "authoritative_outcomes", "closed_at", "Developer Tools", "Setup and outcome attribution", "On-demand joins", "RESEARCH"),
    ("MFE / MAE Analytics", "RESEARCH / ANALYTICS", "intraday_paper_trades", "updated_at", "Command Card + audits", "Exit quality and adverse excursion", "Existing trade columns", "RESEARCH"),
    ("Mark Telemetry", "RESEARCH / ANALYTICS", "intraday_position_marks", "observed_at", "Research + audits", "Ordered open-position path evidence", "Highest-frequency research writes", "EXPERIMENT"),
    ("Sequence / Overtrading Analytics", "RESEARCH / ANALYTICS", "qqq_first_two_shadow_trades", "opened_at", "Command Card + research", "Tests trade-count selectivity", "Read-only over shadow ledger", "EXPERIMENT"),
    ("Trade Desk", "UI", None, None, "Primary UI", "Current-session decision and reconciliation surface", "Normal dashboard reads", "CORE"),
    ("QQQ Command Card", "UI", None, None, "Primary UI", "Manual QQQ replication and session intelligence", "One bounded read-only snapshot", "CORE"),
    ("Performance Page", "UI", None, None, "Normal UI", "Portfolio outcome review", "Read-only aggregates", "CORE"),
    ("SPY / QQQ Page", "UI", None, None, "Normal UI", "Intraday operational visibility", "Read-only repository access", "CORE"),
    ("Developer Tools Panels", "UI", None, None, "Advanced / on demand", "Forensics, diagnostics and research", "Queries only after explicit action", "RESEARCH"),
    ("Legacy Panels", "UI", None, None, "Advanced / deferred", "Historical provenance", "Deferred history reads", "LEGACY"),
    ("Trade Journals", "PERSISTENCE", "paper_execution_journal", "event_timestamp", "Audit + reconciliation", "Execution provenance", "Append-only rows", "CORE"),
    ("Runtime State", "PERSISTENCE", "intraday_runtime_state", "updated_at", "Operations + UI", "Worker freshness and failure diagnosis", "Small upsert table", "CORE"),
    ("Position Context Marks", "PERSISTENCE", "position_context_marks", "observed_at", "Research only", "Open-position contextual path", "Frequent telemetry rows", "EXPERIMENT"),
    ("MIRROR Ledger", "PERSISTENCE", "mirror_execution_trades", "updated_at", "Research/control only", "Full-participation benchmark", "Parallel trade and mark storage", "CONTROL"),
    ("Scanner Worker", "OPERATIONS", "scanner_runtime_state", "updated_at", "Operations", "Produces authoritative opportunities", "Provider calls and runtime complexity", "CORE"),
    ("Intraday Worker", "OPERATIONS", "intraday_runtime_state", "updated_at", "Operations", "SPY/QQQ detection and management", "Bars/chains/quotes and persistence", "CORE"),
    ("Provider Integrations", "OPERATIONS", None, None, "Operations", "Required market and option data", "External calls; caching applies", "CORE"),
    ("Runtime Diagnostics", "OPERATIONS", "scan_health", "scan_timestamp", "Advanced UI", "Provider/data failure diagnosis", "Small health records", "CORE"),
)

COMPONENT_SCOPES={
    "QQQ Managed":("intraday_paper_trades","symbol='QQQ' AND variant='INTRADAY_MANAGED'"),
    "QQQ MIRROR Control":("intraday_paper_trades","symbol='QQQ' AND variant='INTRADAY_MIRROR'"),
    "SPY Intraday":("intraday_paper_trades","symbol='SPY'"),
}


def evidence_band(count):
    if count < 10: return "INSUFFICIENT DATA"
    if count < 30: return "DESCRIPTIVE ONLY"
    if count < 50: return "UNSTABLE"
    return "EVALUABLE"


def _classification(item, *, exists, count, freshness):
    role=item[7]
    if item[2] and not exists: return "BROKEN / MISCONFIGURED — FIX BEFORE JUDGING"
    if role=="CORE": return "CORE — KEEP"
    if role=="CONTROL": return "VALUABLE CONTROL — KEEP HIDDEN / RESEARCH ONLY"
    if freshness=="STALE / DORMANT" and count>=10: return "STALE / UNUSED — CANDIDATE TO RETIRE"
    if role=="LEGACY" and count>=50: return "REDUNDANT — CANDIDATE TO HIDE / CONSOLIDATE"
    if count<10 and item[2]: return "UNPROVEN — INSUFFICIENT DATA"
    if role=="EXPERIMENT": return "PROMISING — KEEP COLLECTING DATA"
    return "CORE — KEEP" if role=="RESEARCH" else "UNPROVEN — INSUFFICIENT DATA"


def run_whole_app_audit(database_url, *, connector=None, now=None):
    """Inspect configured persistence through one Neon-safe read-only transaction."""
    observed_at=now or datetime.now(timezone.utc); kwargs={"connector":connector} if connector else {}
    table_evidence={};component_evidence={}
    with read_only_connection(database_url, **kwargs) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT table_name,column_name FROM information_schema.columns WHERE table_schema='public'")
        columns={}
        for row in cursor.fetchall(): columns.setdefault(row["table_name"],set()).add(row["column_name"])
        for table,timestamp in sorted({(item[2],item[3]) for item in INVENTORY if item[2]}):
            if table not in columns:
                table_evidence[table]={"exists":False,"records":0,"first_observation":None,"last_observation":None,"approx_storage_bytes":None}
                continue
            time_sql=(f",MIN({timestamp}) AS first_observation,MAX({timestamp}) AS last_observation,"
                f"COUNT(DISTINCT ({timestamp}::timestamptz AT TIME ZONE 'America/New_York')::date) AS sessions"
                if timestamp in columns[table] else ",NULL AS first_observation,NULL AS last_observation,0 AS sessions")
            cursor.execute(f"SELECT COUNT(*) AS records{time_sql} FROM {table}")
            values=dict(cursor.fetchone())
            performance=None
            if "realized_pnl" in columns[table]:
                cursor.execute(f"SELECT COUNT(realized_pnl) AS resolved,COALESCE(SUM(realized_pnl),0) AS pnl,"
                    f"AVG(realized_pnl) AS expectancy,SUM(CASE WHEN realized_pnl>0 THEN realized_pnl ELSE 0 END) AS gross_wins,"
                    f"SUM(CASE WHEN realized_pnl<0 THEN realized_pnl ELSE 0 END) AS gross_losses FROM {table}")
                perf=dict(cursor.fetchone()); losses=abs(float(perf.get("gross_losses") or 0))
                performance={"resolved":int(perf.get("resolved") or 0),"pnl":perf.get("pnl"),
                    "expectancy":perf.get("expectancy"),"profit_factor":float(perf.get("gross_wins") or 0)/losses if losses else None}
            try:
                cursor.execute("SELECT pg_total_relation_size(%s) AS bytes",(f"public.{table}",)); size=dict(cursor.fetchone()).get("bytes")
            except Exception: size=None
            table_evidence[table]={"exists":True,"records":int(values.get("records") or 0),
                "sessions":int(values.get("sessions") or 0),"first_observation":values.get("first_observation"),
                "last_observation":values.get("last_observation"),"approx_storage_bytes":size,"performance":performance}
        for name,(table,where) in COMPONENT_SCOPES.items():
            if table not in columns: continue
            item=next(value for value in INVENTORY if value[0]==name);timestamp=item[3]
            time_sql=(f",MIN({timestamp}) AS first_observation,MAX({timestamp}) AS last_observation,"
                f"COUNT(DISTINCT ({timestamp}::timestamptz AT TIME ZONE 'America/New_York')::date) AS sessions")
            performance_sql=(",COUNT(realized_pnl) AS resolved,COALESCE(SUM(realized_pnl),0) AS pnl,AVG(realized_pnl) AS expectancy,"
                "SUM(CASE WHEN realized_pnl>0 THEN realized_pnl ELSE 0 END) AS gross_wins,"
                "SUM(CASE WHEN realized_pnl<0 THEN realized_pnl ELSE 0 END) AS gross_losses" if "realized_pnl" in columns[table] else "")
            cursor.execute(f"SELECT COUNT(*) AS records{time_sql}{performance_sql} FROM {table} WHERE {where}")
            values=dict(cursor.fetchone());losses=abs(float(values.get("gross_losses") or 0))
            performance=({"resolved":int(values.get("resolved") or 0),"pnl":values.get("pnl"),
                "expectancy":values.get("expectancy"),"profit_factor":float(values.get("gross_wins") or 0)/losses if losses else None}
                if performance_sql else None)
            component_evidence[name]={"exists":True,"records":int(values.get("records") or 0),
                "sessions":int(values.get("sessions") or 0),"first_observation":values.get("first_observation"),
                "last_observation":values.get("last_observation"),"approx_storage_bytes":table_evidence[table]["approx_storage_bytes"],
                "performance":performance}
    components=[]
    for item in INVENTORY:
        name,domain,table,_,usage,value,cost,role=item
        evidence=component_evidence.get(name,table_evidence.get(table,{"exists":True,"records":0,"first_observation":None,"last_observation":None,"approx_storage_bytes":None}))
        last=evidence.get("last_observation"); age_days=None
        if last:
            parsed=last if isinstance(last,datetime) else datetime.fromisoformat(str(last).replace("Z","+00:00"))
            if parsed.tzinfo is None: parsed=parsed.replace(tzinfo=timezone.utc)
            age_days=max(0,(observed_at.astimezone(timezone.utc)-parsed.astimezone(timezone.utc)).days)
        freshness="STALE / DORMANT" if age_days is not None and age_days>30 else "ACTIVE / RECENT" if last else "NOT MEASURABLE"
        count=evidence["records"]
        components.append({"component":name,"domain":domain,"role":role,"source_table":table,
            "data_volume":{"records":count,"sessions":evidence.get("sessions",0),"first_observation":evidence.get("first_observation"),"last_observation":last,
                "approx_storage_bytes":evidence.get("approx_storage_bytes"),"evidence_band":evidence_band(count)},
            "usage":usage,"decision_or_diagnostic_value":value,"performance_value":evidence.get("performance"),"cost":cost,"freshness":freshness,
            "redundancy_assessment":"Review overlap in audit summary; no automatic deletion recommended.",
            "classification":_classification(item,exists=evidence["exists"],count=count,freshness=freshness)})
    counts={}
    for component in components: counts[component["classification"]]=counts.get(component["classification"],0)+1
    return {"status":"COMPLETED","metadata":{"generated_at":observed_at,"mode":"READ ONLY","database_fingerprint":database_fingerprint(database_url),
        "provider_calls":0,"database_writes":0,"automatic_retirements":0},"governance":{"minimum_evidence":{"0-9":"INSUFFICIENT DATA","10-29":"DESCRIPTIVE ONLY","30-49":"UNSTABLE","50+":"EVALUABLE"},
        "warning":"Classification is evidence-gated and recommendation-only."},"classification_counts":counts,
        "components":components,"table_evidence":table_evidence,"component_scopes":COMPONENT_SCOPES,
        "recommendations":{"keep_primary":[c["component"] for c in components if c["classification"]=="CORE — KEEP"],
            "keep_hidden_control":[c["component"] for c in components if c["classification"].startswith("VALUABLE CONTROL")],
            "collect_more_evidence":[c["component"] for c in components if c["classification"].startswith(("PROMISING","UNPROVEN"))],
            "review_for_consolidation":[c["component"] for c in components if "CANDIDATE" in c["classification"]],
            "fix_before_judging":[c["component"] for c in components if c["classification"].startswith("BROKEN")]}}
