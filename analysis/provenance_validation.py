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
        current=exc; unavailable=False
        while current is not None:
            detail=f"{type(current).__name__}: {current}".lower()
            unavailable=unavailable or "no such table" in detail or "undefinedtable" in detail
            current=current.__cause__ or current.__context__
        if repo._provenance_table_unavailable(exc) or unavailable: return []
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
    authoritative_trades = _read(repo, "authoritative_trades", "opened_at", start, end)
    capital_positions = _read(repo, "capital_positions", "opened_at", start, end)
    capital_decisions = _read(repo, "capital_decisions", "decided_at", start, end)
    # Live OB/BROAD decision links use capital position IDs. Authoritative trades
    # remain included for legacy/qualification chains, with exact identities.
    trades = [dict(r, id=r.get("position_id"), realized_result=r.get("realistic_pnl")) for r in capital_positions]
    trades.extend(r for r in authoritative_trades if r.get("id") not in {t.get("id") for t in trades})
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
        if not cycle.get("completed_at") or cycle.get("cycle_status") == "SCANNING": issues.append(_issue("MEDIUM","INCOMPLETE_CYCLE","Cycle has no genuine completion record and remains explicitly incomplete.",cycle))
        if _dt(cycle.get("completed_at")) and _dt(cycle["completed_at"]) < _dt(cycle.get("started_at")): issues.append(_issue("HIGH","IMPOSSIBLE_CYCLE_ORDER","Cycle completion precedes start.",cycle))
        cycle_symbols = {r.get("symbol") for r in observations if r.get("scan_cycle_id") == cycle.get("scan_cycle_id")}
        if not cycle_symbols: issues.append(_issue("MEDIUM","CYCLE_WITHOUT_OBSERVATIONS","Cycle contains no SPY/QQQ observations.",cycle))
        elif not symbols.issubset(cycle_symbols): issues.append(_issue("MEDIUM","INCOMPLETE_SYMBOL_COVERAGE",f"Cycle is missing {sorted(symbols-cycle_symbols)}.",cycle))
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
    rejected_decisions=[r for r in capital_decisions if str(r.get("decision_state") or "").upper() != "TAKE"]
    counterfactual_available=sum(r.get("hypothetical_realistic_pnl") is not None and bool(r.get("hypothetical_outcome")) for r in rejected_decisions)
    counterfactual={"eligible_decisions":len(rejected_decisions),"available":counterfactual_available,
                    "unavailable":len(rejected_decisions)-counterfactual_available,
                    "coverage_pct":_pct(counterfactual_available,len(rejected_decisions)),
                    "unavailable_label":"UNAVAILABLE_COUNTERFACTUAL_OUTCOME"}
    total_rows=len(cycles)+len(observations)+len(links)+len(capital_decisions)+len(trades)+len(management)
    approximate_bytes=sum(len(json.dumps(row,default=str,separators=(",",":"))) for rows in (cycles,observations,links,capital_decisions,trades,management) for row in rows)
    return {"report_version":1,"generated_at":datetime.now(timezone.utc).isoformat(),"window":{"session_date":day.isoformat(),"days":days,"start_utc":start.isoformat(),"end_utc_exclusive":end.isoformat()},
            "data_status":"NO_PROVENANCE_DATA" if not cycles or not observations else "PARTIAL" if degraded else "AVAILABLE","session_summary":summary,
            "provenance_health":{"score":score,"state":health_state,"dimensions":dimensions,"formula":"Mean of seven 0-100 observability dimensions; CRITICAL caps score at 49 and forces UNRELIABLE."},
            "qualification_distribution":distribution,"rejection_reasons":reason_rows,"symbol_breakdown":breakdown,"chain_completeness":chain,
            "exploratory_metrics":{"qualified_to_trade_conversion_pct":_pct(len(linked_ids),counts.get("QUALIFIED",0)),"OB_take_rate_pct":_pct(sum(r.get("lane")=="OB" and r.get("decision_state")=="TAKE" for r in links),sum(r.get("lane")=="OB" for r in links)),"BROAD_take_rate_pct":_pct(sum(r.get("lane")=="BROAD" and r.get("decision_state")=="TAKE" for r in links),sum(r.get("lane")=="BROAD" for r in links)),"observed_trade_outcomes":outcomes,"counterfactual_outcomes":counterfactual,"interpretation":"Exploratory observed evidence only; no statistical significance claimed."},
            "integrity_issues":sorted(issues,key=lambda i:(list(WEIGHTS).index(i["severity"]),i["issue_code"])),
            "storage_growth":{"scan_cycles":len(cycles),"observations":len(observations),"decision_links":len(links),"average_cycles_per_session":round(len(cycles)/days,2),"average_observations_per_session":round(len(observations)/days,2),"projected_monthly_rows":round(total_rows/days*21),"projected_yearly_rows":round(total_rows/days*252),"original_estimate":{"cycles_per_session":78,"observations_per_session":156},"runaway_growth":len(cycles)>156*days or len(observations)>312*days,"approximate_bytes":approximate_bytes,"estimated_bytes_per_session":round(approximate_bytes/days),"size_targets_bytes":{str(target):round(approximate_bytes/days*target) for target in (20,40,60,250,1000)}},
            "research_eligible":bool(cycles and observations and completed==len(cycles) and health_state=="HEALTHY" and dimensions["observation_coverage"]>=95 and degraded==0),
            "limitations":["Rejected observations have no canonical counterfactual outcome.","Low historical volume is not itself an integrity failure."]}


def build_readiness(repo, *, as_of=None, lookback_days=365):
    """Summarize per-ET-session collection readiness using validator reports."""
    as_of = as_of or datetime.now(EASTERN).date()
    lookback_days=max(1,int(lookback_days))
    start,_=_bounds(as_of,lookback_days)
    _,end=_bounds(as_of,1)
    cycle_rows=_read(repo,"provenance_scan_cycles","started_at",start,end)
    session_dates=sorted({_dt(row.get("started_at")).astimezone(EASTERN).date() for row in cycle_rows if _dt(row.get("started_at"))},reverse=True)
    session_reports=[build_report(repo,session_date=session_date) for session_date in session_dates]
    sessions=[]
    for report in session_reports:
        summary=report["session_summary"]; health=report["provenance_health"]
        symbols=[symbol for symbol,values in report["symbol_breakdown"].items() if values["observations"]]
        incomplete=summary["completed_cycles"] != summary["scan_cycles"]
        reasons=[]
        if incomplete: reasons.append("INCOMPLETE_SESSION")
        if summary["SPY_observations"] == 0: reasons.append("MISSING_SPY")
        if summary["QQQ_observations"] == 0: reasons.append("MISSING_QQQ")
        if summary["observation_coverage_pct"] is None or summary["observation_coverage_pct"] < 95: reasons.append("OBSERVATION_COVERAGE_BELOW_95")
        if health["state"] != "HEALTHY": reasons.append(f"HEALTH_{health['state']}")
        if not report["research_eligible"] and not reasons: reasons.append("VALIDATOR_NOT_RESEARCH_ELIGIBLE")
        states={row["state"]:row["count"] for row in report["qualification_distribution"]}
        counterfactual=report["exploratory_metrics"]["counterfactual_outcomes"]
        sessions.append({"session_id":summary["date"],"date":summary["date"],"symbols":symbols,
                         "start_end_state":"INCOMPLETE" if incomplete else "COMPLETE",
                         "record_counts":{"scan_cycles":summary["scan_cycles"],"observations":summary["actual_observations"],"capital_decisions":report["chain_completeness"]["capital_decisions"],"trade_links":report["chain_completeness"]["trade_links"]},
                         "required_chain_completeness":report["chain_completeness"],"qualified_count":states.get("QUALIFIED",0),
                         "rejected_count":states.get("REJECTED",0)+states.get("NO_SETUP",0),"counterfactual":counterfactual,
                         "identity_integrity_state":"FAIL" if any(i["severity"]=="CRITICAL" for i in report["integrity_issues"]) else "PASS",
                         "validator_health_score":health["score"],"validator_health_state":health["state"],
                         "research_eligible":report["research_eligible"],"not_eligible_reasons":reasons})
    eligible=sum(s["research_eligible"] for s in sessions); complete=sum(s["start_end_state"]=="COMPLETE" for s in sessions)
    incomplete=len(sessions)-complete; critical=sum(s["identity_integrity_state"]=="FAIL" for s in sessions)
    total_observations=sum(s["record_counts"]["observations"] for s in sessions)
    qualified=sum(s["qualified_count"] for s in sessions); rejected=sum(s["rejected_count"] for s in sessions)
    cf_eligible=sum(s["counterfactual"]["eligible_decisions"] for s in sessions); cf_available=sum(s["counterfactual"]["available"] for s in sessions)
    latest=sessions[0] if sessions else None; last_complete=next((s for s in sessions if s["start_end_state"]=="COMPLETE"),None)
    missing=[]
    if not sessions: missing.append("NO_PROVENANCE_SESSIONS")
    if complete<20: missing.append("FEWER_THAN_20_COMPLETE_SESSIONS")
    if critical: missing.append("CRITICAL_IDENTITY_FAILURES")
    if incomplete: missing.append("INCOMPLETE_SESSIONS_PRESENT")
    status="NO_DATA" if not sessions else "INTEGRITY_FAILURE" if critical else "INCOMPLETE_DATA" if incomplete and not complete else "RESEARCH_ELIGIBLE" if eligible>=20 and complete>=20 else "HEALTHY_BUT_INSUFFICIENT_SAMPLE" if all(s["validator_health_state"]=="HEALTHY" for s in sessions) else "COLLECTING"
    return {"as_of":as_of.isoformat(),"collection_status":status,"current_or_most_recent_session":latest,"last_complete_session":last_complete,
            "sessions_collected":len(sessions),"complete_sessions":complete,"research_eligible_sessions":eligible,"incomplete_sessions":incomplete,
            "integrity_failures":critical,"SPY_session_count":sum("SPY" in s["symbols"] for s in sessions),"QQQ_session_count":sum("QQQ" in s["symbols"] for s in sessions),
            "qualified_observations":qualified,"rejected_observations":rejected,"observations":total_observations,
            "counterfactual_coverage":{"eligible":cf_eligible,"available":cf_available,"coverage_pct":_pct(cf_available,cf_eligible),"unavailable_label":"UNAVAILABLE_COUNTERFACTUAL_OUTCOME"},
            "health_score":latest["validator_health_score"] if latest else 0.0,"health_state":latest["validator_health_state"] if latest else "UNRELIABLE",
            "missing_requirements":missing,"evidence_targets":{"minimum_20":{"complete":complete,"remaining":max(0,20-complete),"progress_pct":min(100,_pct(complete,20) or 0)},"preferred_40":{"complete":complete,"remaining":max(0,40-complete),"progress_pct":min(100,_pct(complete,40) or 0)},"stronger_60":{"complete":complete,"remaining":max(0,60-complete),"progress_pct":min(100,_pct(complete,60) or 0)}},
            "sessions":sessions,"interpretation":"20/40/60 are evidence-collection targets, not statistical guarantees."}


def write_json(report,path): Path(path).write_text(json.dumps(report,indent=2,default=str)+"\n",encoding="utf-8")
def write_csv(report,directory):
    target=Path(directory); target.mkdir(parents=True,exist_ok=True)
    for name,rows in {"session-summary.csv":[report["session_summary"]],"qualification-rejection-summary.csv":report["qualification_distribution"]+report["rejection_reasons"],"integrity-issues.csv":report["integrity_issues"]}.items():
        fields=sorted({k for row in rows for k in row}) if rows else ["empty"]
        with (target/name).open("w",newline="",encoding="utf-8") as handle: writer=csv.DictWriter(handle,fieldnames=fields,extrasaction="ignore"); writer.writeheader(); writer.writerows(rows)
def human_report(report):
    s=report["session_summary"]; h=report["provenance_health"]
    return f"Provenance validation: {s['date']}\nHealth: {h['score']}/100 {h['state']}\nCycles: {s['scan_cycles']} ({s['degraded_error_cycles']} degraded/error)\nObservations: {s['actual_observations']}/{s['expected_observations']} expected\nIntegrity issues: {len(report['integrity_issues'])}\nResearch eligible: {'YES' if report['research_eligible'] else 'NO'}"
def human_readiness(report):
    target=report["evidence_targets"]["minimum_20"]
    return f"Provenance collection readiness: {report['collection_status']}\nSessions: {report['sessions_collected']} ({report['complete_sessions']} complete, {report['research_eligible_sessions']} research eligible)\nIntegrity failures: {report['integrity_failures']}\nSPY / QQQ sessions: {report['SPY_session_count']} / {report['QQQ_session_count']}\nCounterfactual coverage: {report['counterfactual_coverage']['coverage_pct']}\n20-session target: {target['complete']}/20 ({target['remaining']} remaining)"
def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("--date",type=date.fromisoformat,default=datetime.now(EASTERN).date()); p.add_argument("--days",type=int,default=1); p.add_argument("--symbol",action="append",choices=("SPY","QQQ")); p.add_argument("--lane",action="append",choices=("OB","BROAD")); p.add_argument("--database"); p.add_argument("--json-output"); p.add_argument("--csv-output"); p.add_argument("--readiness",action="store_true"); p.add_argument("--lookback-days",type=int,default=365); a=p.parse_args(argv)
    repo=TradeRepository(a.database) if a.database else TradeRepository()
    report=build_readiness(repo,as_of=a.date,lookback_days=a.lookback_days) if a.readiness else build_report(repo,session_date=a.date,days=a.days,symbols=a.symbol,lanes=a.lane)
    if a.json_output: write_json(report,a.json_output)
    if a.csv_output and not a.readiness: write_csv(report,a.csv_output)
    print(human_readiness(report) if a.readiness else human_report(report)); return report
if __name__ == "__main__": main()
