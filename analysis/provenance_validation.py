"""Read-only validation and evidence reporting for canonical decision provenance."""
from __future__ import annotations

import argparse, csv, json
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from trade_repository import TradeRepository, parse_utc

EASTERN = ZoneInfo("America/New_York")
LANES = {"OB", "BROAD"}
STATES = ("QUALIFIED", "NO_SETUP", "REJECTED", "SESSION_BLOCKED", "DATA_UNSAFE")
WEIGHTS = {"CRITICAL": 35, "HIGH": 12, "MEDIUM": 4, "LOW": 1}


def _bounds(day, days):
    start = datetime.combine(day - timedelta(days=days - 1), time.min, EASTERN)
    end = datetime.combine(day + timedelta(days=1), time.min, EASTERN)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _read(repo, table, column, start, end):
    try:
        with repo.connection() as connection:
            return repo._fetchall(connection, f"SELECT * FROM {table} WHERE {column}>=? AND {column}<? ORDER BY {column}", (start.isoformat(), end.isoformat()))
    except Exception as exc:
        if repo._provenance_table_unavailable(exc): return []
        raise


def _pct(a, b): return round(a * 100 / b, 2) if b else None
def _dt(value): return parse_utc(value) if value else None
def _valid(value): return bool(value) and len(str(value)) <= 256 and not any(c.isspace() for c in str(value))


def _issue(severity, code, explanation, row=None, **identities):
    row = row or {}
    ids = {k: v for k, v in identities.items() if v}
    for key in ("scan_cycle_id", "observation_id", "opportunity_id", "decision_id", "trade_id"):
        if row.get(key): ids.setdefault(key, row[key])
    return {"severity": severity, "issue_code": code, "relevant_ids": ids,
            "symbol": row.get("symbol"), "lane": row.get("lane"),
            "timestamp": row.get("observed_at") or row.get("decided_at") or row.get("started_at"),
            "explanation": explanation, "recommended_investigation": "Inspect the persisted provenance chain; do not repair automatically."}


def build_report(repo, *, session_date=None, days=1, symbols=None, lanes=None):
    """Return a JSON-safe report without changing persisted state."""
    day = session_date or datetime.now(EASTERN).date(); days = max(1, int(days))
    symbols = {str(x).upper() for x in (symbols or ("SPY", "QQQ"))}
    selected_lanes = {str(x).upper() for x in (lanes or LANES)}
    start, end = _bounds(day, days)
    cycles = _read(repo, "provenance_scan_cycles", "started_at", start, end)
    observations = [r for r in _read(repo, "provenance_observations", "observed_at", start, end) if r.get("symbol") in symbols]
    # Keep invalid lanes visible even when valid-lane filters are requested.
    links = [r for r in _read(repo, "provenance_decision_trade_links", "decided_at", start, end) if r.get("lane") in selected_lanes or r.get("lane") not in LANES]
    opportunities = _read(repo, "opportunities", "created_at", start, end)
    trades = _read(repo, "authoritative_trades", "opened_at", start, end)
    management = _read(repo, "trade_management_snapshots", "captured_at", start, end)
    cycle_map = {r.get("scan_cycle_id"): r for r in cycles}; obs_map = {r.get("observation_id"): r for r in observations}
    opp_map = {r.get("id"): r for r in opportunities}; trade_map = {r.get("id"): r for r in trades}
    issues = []
    for rows, key, code in ((cycles,"scan_cycle_id","DUPLICATE_SCAN_CYCLE"),(observations,"observation_id","DUPLICATE_OBSERVATION"),(links,"decision_id","DUPLICATE_DECISION_LINK")):
        for identity, count in Counter(r.get(key) for r in rows).items():
            if identity and count > 1: issues.append(_issue("CRITICAL", code, f"Identity occurs {count} times.", **{key: identity}))
    for cycle in cycles:
        if not _valid(cycle.get("scan_cycle_id")): issues.append(_issue("HIGH","MALFORMED_SCAN_CYCLE_ID","Scan-cycle identity is malformed.",cycle))
        if cycle.get("provenance_status") == "DEGRADED" or cycle.get("cycle_status") in {"ERROR","FAILED"}: issues.append(_issue("MEDIUM","DEGRADED_CYCLE","Cycle is degraded or failed.",cycle))
        if _dt(cycle.get("completed_at")) and _dt(cycle["completed_at"]) < _dt(cycle.get("started_at")): issues.append(_issue("HIGH","IMPOSSIBLE_CYCLE_ORDER","Cycle completion precedes start.",cycle))
    for obs in observations:
        cycle = cycle_map.get(obs.get("scan_cycle_id"))
        if not _valid(obs.get("observation_id")): issues.append(_issue("HIGH","MALFORMED_OBSERVATION_ID","Observation identity is malformed.",obs))
        if not cycle: issues.append(_issue("HIGH","OBSERVATION_MISSING_CYCLE","Observation has no cycle in the evidence window.",obs))
        elif _dt(obs.get("observed_at")) < _dt(cycle.get("started_at")): issues.append(_issue("HIGH","OBSERVATION_BEFORE_CYCLE","Observation precedes cycle start.",obs))
        if obs.get("opportunity_id") and obs["opportunity_id"] not in opp_map: issues.append(_issue("CRITICAL","OPPORTUNITY_NOT_FOUND","Observation points to a nonexistent opportunity.",obs))
        if obs.get("qualification_state") == "QUALIFIED" and not obs.get("opportunity_id"): issues.append(_issue("HIGH","QUALIFIED_WITHOUT_OPPORTUNITY","Qualified observation lacks opportunity linkage.",obs))
        if obs.get("qualification_state") != "QUALIFIED" and not str(obs.get("reason_code") or "").strip(): issues.append(_issue("MEDIUM","MISSING_REJECTION_REASON","Non-qualified observation lacks a structured reason.",obs))
        if not str(obs.get("explanation") or "").strip(): issues.append(_issue("LOW","MISSING_EXPLANATION","Observation lacks explanation.",obs))
        if obs.get("stale") or obs.get("qualification_state") == "DATA_UNSAFE": issues.append(_issue("MEDIUM","UNSAFE_OR_STALE_DATA","Observation is stale or data-unsafe.",obs))
    trades_by_opp = defaultdict(list)
    for trade in trades:
        trades_by_opp[trade.get("opportunity_id")].append(trade)
        if trade.get("opportunity_id") not in opp_map: issues.append(_issue("CRITICAL","TRADE_OPPORTUNITY_NOT_FOUND","Trade opportunity does not exist.",trade_id=trade.get("id"),opportunity_id=trade.get("opportunity_id")))
        if _dt(trade.get("closed_at")) and _dt(trade["closed_at"]) < _dt(trade.get("opened_at")): issues.append(_issue("HIGH","CLOSE_BEFORE_ENTRY","Trade closes before entry.",trade_id=trade.get("id")))
    trade_lanes = defaultdict(set)
    for link in links:
        lane = str(link.get("lane") or "").upper(); obs = obs_map.get(link.get("observation_id")); opp = opp_map.get(link.get("opportunity_id"))
        if lane not in LANES: issues.append(_issue("CRITICAL","NON_DEPLOYABLE_LANE_CONTAMINATION","MIRROR/control or invalid lane appears in deployable evidence.",link))
        if link.get("observation_id") and not obs: issues.append(_issue("HIGH","DECISION_OBSERVATION_NOT_FOUND","Decision observation is missing.",link))
        if not opp: issues.append(_issue("CRITICAL","DECISION_OPPORTUNITY_NOT_FOUND","Decision opportunity is missing.",link))
        if obs and obs.get("opportunity_id") != link.get("opportunity_id"): issues.append(_issue("CRITICAL","DECISION_OPPORTUNITY_MISMATCH","Decision and observation opportunity differ.",link))
        if obs and opp and obs.get("symbol") != opp.get("symbol"): issues.append(_issue("CRITICAL","SYMBOL_MISMATCH","Observation and opportunity symbols differ.",link))
        if opp and _dt(link.get("decided_at")) < _dt(opp.get("created_at")): issues.append(_issue("HIGH","DECISION_BEFORE_OPPORTUNITY","Decision precedes opportunity.",link))
        if link.get("decision_state") == "TAKE" and trades_by_opp.get(link.get("opportunity_id")) and not link.get("trade_id"): issues.append(_issue("HIGH","TAKE_MISSING_TRADE_LINK","TAKE created a trade without exact linkage.",link))
        if link.get("trade_id"):
            trade_lanes[link["trade_id"]].add(lane)
            if link["trade_id"] not in trade_map: issues.append(_issue("CRITICAL","TRADE_NOT_FOUND","Decision-linked trade does not exist.",link))
    for trade_id, values in trade_lanes.items():
        if len(values & LANES) > 1: issues.append(_issue("CRITICAL","OB_BROAD_TRADE_COLLISION","Trade has conflicting deployable lanes.",trade_id=trade_id))
    management_ids = set()
    for snapshot in management:
        management_ids.add(snapshot.get("trade_id")); expected = trade_lanes.get(snapshot.get("trade_id"), set())
        if snapshot.get("lane") not in LANES or expected and snapshot.get("lane") not in expected: issues.append(_issue("CRITICAL","MANAGEMENT_LANE_MISMATCH","Management snapshot violates exact trade/lane identity.",snapshot))
        if snapshot.get("entry_timestamp") and _dt(snapshot.get("captured_at")) < _dt(snapshot.get("entry_timestamp")): issues.append(_issue("HIGH","MANAGEMENT_BEFORE_ENTRY","Management snapshot precedes entry.",snapshot))
    counts = Counter(str(r.get("qualification_state") or "OTHER") for r in observations)
    distribution = [{"state": state,"count":counts.get(state,0),"percentage":_pct(counts.get(state,0),len(observations))} for state in (*STATES,*sorted(set(counts)-set(STATES)))]
    reasons = Counter(str(r.get("reason_code") or "MISSING") for r in observations if r.get("qualification_state") != "QUALIFIED")
    reason_rows = [{"reason_code":reason,"count":count} for reason,count in reasons.most_common()]
    completed = sum(bool(r.get("completed_at")) and r.get("cycle_status") not in {"ERROR","FAILED"} for r in cycles)
    degraded = sum(r.get("provenance_status") == "DEGRADED" or r.get("cycle_status") in {"ERROR","FAILED"} for r in cycles)
    expected = len(cycles)*len(symbols); opp_linked = sum(bool(r.get("opportunity_id")) for r in observations)
    linked_ids = {r.get("trade_id") for r in links if r.get("trade_id")}; closed = [r for r in trades if r.get("closed_at")]
    outcomes = sum(r.get("realized_result") is not None for r in closed)
    chain = {"observations":len(observations),"opportunity_linked_observations":opp_linked,"opportunity_linkage_pct":_pct(opp_linked,len(observations)),
             "capital_decisions":len(links),"trade_links":len(linked_ids),"trade_linkage_pct":_pct(len(linked_ids),sum(r.get("decision_state")=="TAKE" for r in links)),
             "management_linked_trades":len(management_ids&linked_ids),"management_linkage_pct":_pct(len(management_ids&linked_ids),len(linked_ids)),
             "closed_outcomes":outcomes,"outcome_linkage_pct":_pct(outcomes,len(closed))}
    dimensions = {"cycle_coverage":_pct(completed,len(cycles)) or 0.0,"observation_coverage":_pct(len(observations),expected) or 0.0,
                  "chain_completeness":chain["opportunity_linkage_pct"] or 0.0,"identity_integrity":max(0,100-sum(WEIGHTS[i["severity"]] for i in issues if i["severity"] in {"CRITICAL","HIGH"})),
                  "temporal_integrity":max(0,100-12*sum("BEFORE" in i["issue_code"] or "ORDER" in i["issue_code"] for i in issues)),
                  "data_quality":_pct(sum(not r.get("stale") and r.get("qualification_state")!="DATA_UNSAFE" for r in observations),len(observations)) or 0.0,
                  "outcome_linkage":chain["outcome_linkage_pct"] if closed else 100.0}
    score=round(sum(dimensions.values())/len(dimensions),1); critical=any(i["severity"]=="CRITICAL" for i in issues)
    if critical: score=min(score,49.0)
    health_state="UNRELIABLE" if critical or score<60 else "DEGRADED" if score<85 else "HEALTHY"
    summary={"date":day.isoformat(),"scan_cycles":len(cycles),"completed_cycles":completed,"degraded_error_cycles":degraded,
             "SPY_observations":sum(r.get("symbol")=="SPY" for r in observations),"QQQ_observations":sum(r.get("symbol")=="QQQ" for r in observations),
             "expected_observations":expected,"actual_observations":len(observations),"observation_coverage_pct":_pct(len(observations),expected)}
    breakdown={}
    for symbol in sorted(symbols):
        obs=[r for r in observations if r.get("symbol")==symbol]; opp_ids={r.get("opportunity_id") for r in obs if r.get("opportunity_id")}; sl=[r for r in links if r.get("opportunity_id") in opp_ids]; st=[r for r in trades if r.get("opportunity_id") in opp_ids]
        breakdown[symbol]={"observations":len(obs),"qualified":sum(r.get("qualification_state")=="QUALIFIED" for r in obs),"rejected_or_no_setup":sum(r.get("qualification_state") in {"REJECTED","NO_SETUP"} for r in obs),"opportunities":len(opp_ids),
                           "OB_TAKE":sum(r.get("lane")=="OB" and r.get("decision_state")=="TAKE" for r in sl),"OB_PASS_BLOCK":sum(r.get("lane")=="OB" and r.get("decision_state")!="TAKE" for r in sl),
                           "BROAD_TAKE":sum(r.get("lane")=="BROAD" and r.get("decision_state")=="TAKE" for r in sl),"BROAD_PASS_BLOCK":sum(r.get("lane")=="BROAD" and r.get("decision_state")!="TAKE" for r in sl),
                           "trades_created":len(st),"closed_outcomes":sum(bool(r.get("closed_at")) and r.get("realized_result") is not None for r in st),"realized_pnl":round(sum(float(r.get("realized_result") or 0) for r in st),2)}
    total_rows=len(cycles)+len(observations)+len(links)
    return {"report_version":1,"generated_at":datetime.now(timezone.utc).isoformat(),"window":{"session_date":day.isoformat(),"days":days,"start_utc":start.isoformat(),"end_utc_exclusive":end.isoformat()},
            "data_status":"NO_PROVENANCE_DATA" if not cycles or not observations else "PARTIAL" if degraded else "AVAILABLE","session_summary":summary,
            "provenance_health":{"score":score,"state":health_state,"dimensions":dimensions,"formula":"Mean of seven 0-100 observability dimensions; CRITICAL caps score at 49 and forces UNRELIABLE."},
            "qualification_distribution":distribution,"rejection_reasons":reason_rows,"symbol_breakdown":breakdown,"chain_completeness":chain,
            "exploratory_metrics":{"qualified_to_trade_conversion_pct":_pct(len(linked_ids),counts.get("QUALIFIED",0)),"OB_take_rate_pct":_pct(sum(r.get("lane")=="OB" and r.get("decision_state")=="TAKE" for r in links),sum(r.get("lane")=="OB" for r in links)),"BROAD_take_rate_pct":_pct(sum(r.get("lane")=="BROAD" and r.get("decision_state")=="TAKE" for r in links),sum(r.get("lane")=="BROAD" for r in links)),"observed_trade_outcomes":outcomes,"counterfactual_outcomes":"UNAVAILABLE_COUNTERFACTUAL_OUTCOME","interpretation":"Exploratory observed evidence only; no statistical significance claimed."},
            "integrity_issues":sorted(issues,key=lambda i:(list(WEIGHTS).index(i["severity"]),i["issue_code"])),
            "storage_growth":{"scan_cycles":len(cycles),"observations":len(observations),"decision_links":len(links),"average_cycles_per_session":round(len(cycles)/days,2),"average_observations_per_session":round(len(observations)/days,2),"projected_monthly_rows":round(total_rows/days*21),"projected_yearly_rows":round(total_rows/days*252),"original_estimate":{"cycles_per_session":78,"observations_per_session":156},"runaway_growth":len(cycles)>156*days or len(observations)>312*days,"approximate_database_size":None},
            "research_eligible":bool(cycles and observations and health_state=="HEALTHY" and dimensions["observation_coverage"]>=95 and degraded==0),
            "limitations":["Rejected observations have no canonical counterfactual outcome.","Low historical volume is not itself an integrity failure."]}


def write_json(report,path): Path(path).write_text(json.dumps(report,indent=2,default=str)+"\n",encoding="utf-8")
def write_csv(report,directory):
    target=Path(directory); target.mkdir(parents=True,exist_ok=True)
    for name,rows in {"session-summary.csv":[report["session_summary"]],"qualification-rejection-summary.csv":report["qualification_distribution"]+report["rejection_reasons"],"integrity-issues.csv":report["integrity_issues"]}.items():
        fields=sorted({k for row in rows for k in row}) if rows else ["empty"]
        with (target/name).open("w",newline="",encoding="utf-8") as handle: writer=csv.DictWriter(handle,fieldnames=fields,extrasaction="ignore"); writer.writeheader(); writer.writerows(rows)
def human_report(report):
    s=report["session_summary"]; h=report["provenance_health"]
    return f"Provenance validation: {s['date']}\nHealth: {h['score']}/100 {h['state']}\nCycles: {s['scan_cycles']} ({s['degraded_error_cycles']} degraded/error)\nObservations: {s['actual_observations']}/{s['expected_observations']} expected\nIntegrity issues: {len(report['integrity_issues'])}\nResearch eligible: {'YES' if report['research_eligible'] else 'NO'}"
def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("--date",type=date.fromisoformat,default=datetime.now(EASTERN).date()); p.add_argument("--days",type=int,default=1); p.add_argument("--symbol",action="append",choices=("SPY","QQQ")); p.add_argument("--lane",action="append",choices=("OB","BROAD")); p.add_argument("--database"); p.add_argument("--json-output"); p.add_argument("--csv-output"); a=p.parse_args(argv)
    report=build_report(TradeRepository(a.database) if a.database else TradeRepository(),session_date=a.date,days=a.days,symbols=a.symbol,lanes=a.lane)
    if a.json_output: write_json(report,a.json_output)
    if a.csv_output: write_csv(report,a.csv_output)
    print(human_report(report)); return report
if __name__ == "__main__": main()
