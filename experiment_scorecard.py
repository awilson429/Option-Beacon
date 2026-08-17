"""Read-only daily MIRROR/BROAD/FILTERED experiment accounting."""
from __future__ import annotations

import json
import logging
import math
from collections import defaultdict
from datetime import date, datetime, timezone
from statistics import mean, median
from zoneinfo import ZoneInfo

EASTERN=ZoneInfo("America/New_York")
LOGGER=logging.getLogger(__name__)


def experiment_period(value):
    day=value if isinstance(value,date) else date.fromisoformat(str(value))
    if date(2026,8,10)<=day<=date(2026,8,13): return "DEVELOPMENT"
    if day>=date(2026,8,17): return "FORWARD TEST"
    return "OUTSIDE BOUNDARY"


def age_bucket(seconds):
    value=_number(seconds)
    if value is None:return "DATA UNAVAILABLE"
    if value<=60:return "LE_60"
    if value<=120:return "61_120"
    if value<=180:return "121_180"
    if value<=300:return "181_300"
    return "GT_300"


def governance(closed):
    return "INSUFFICIENT DATA" if closed<30 else "DESCRIPTIVE ONLY" if closed<50 else "ELIGIBLE FOR CHRONOLOGICAL VALIDATION"


def lane_summary(rows,authoritative_n=None):
    opened=[r for r in rows if r.get("opened_at")]
    closed=[r for r in rows if r.get("closed_at") and _number(r.get("pnl")) is not None]
    returns=[_number(r.get("return_pct")) for r in closed]; returns=[v for v in returns if v is not None]
    pnl=[_number(r.get("pnl")) for r in closed]; pnl=[v for v in pnl if v is not None]
    wins=[v for v in pnl if v>0]; losses=[v for v in pnl if v<0]; flats=[v for v in pnl if v==0]
    spreads=[_number(r.get("spread_percent")) for r in opened];spreads=[v for v in spreads if v is not None]
    ages=[_number(r.get("signal_age_seconds")) for r in rows];ages=[v for v in ages if v is not None]
    debits=[_number(r.get("debit")) for r in opened];debits=[v for v in debits if v is not None]
    peak=_peak_capital(opened)
    unrealized=[_number(r.get("unrealized_pnl")) for r in rows if not r.get("closed_at")];unrealized=[v for v in unrealized if v is not None]
    return {"authoritative_opportunities":authoritative_n,"evaluated":len(rows),"opened":len(opened),"closed":len(closed),
        "participation_rate":len(opened)/authoritative_n*100 if authoritative_n else None,"wins":len(wins),"losses":len(losses),
        "flat_noise":len(flats),"win_rate":len(wins)/len(closed)*100 if closed else None,"realized_pnl":sum(pnl) if pnl else None,
        "unrealized_pnl":sum(unrealized) if unrealized else None,"average_return":mean(returns) if returns else None,
        "median_return":median(returns) if returns else None,"average_winner":mean(wins) if wins else None,
        "average_loser":mean(losses) if losses else None,"expectancy":mean(pnl) if pnl else None,
        "profit_factor":sum(wins)/abs(sum(losses)) if losses else math.inf if wins else None,
        "average_spread":mean(spreads) if spreads else None,"median_spread":median(spreads) if spreads else None,
        "average_signal_age":mean(ages) if ages else None,"median_signal_age":median(ages) if ages else None,
        "peak_capital":peak,"cumulative_debit":sum(debits) if debits else None,
        "return_on_peak_capital":sum(pnl)/peak*100 if pnl and peak else None,
        "return_on_cumulative_debit":sum(pnl)/sum(debits)*100 if pnl and debits and sum(debits) else None}


def spread_gate_effectiveness(filtered,mirror):
    mirrors={str(r.get("opportunity_id")):r for r in mirror}
    eligible=[r for r in filtered if r.get("broad_decision")=="ACCEPTED"]
    rejected=[r for r in eligible if r.get("rejection_reason")=="SPREAD_TOO_WIDE"]
    retained=[r for r in eligible if r.get("opened_at")]
    matched=[];unknown=0
    for row in rejected:
        item=mirrors.get(str(row.get("opportunity_id")))
        if item is None or _number(item.get("pnl")) is None:unknown+=1
        else:matched.append(item)
    winner_pnl=sum(_number(r.get("pnl")) for r in matched if _number(r.get("pnl"))>0)
    loser_pnl=sum(_number(r.get("pnl")) for r in matched if _number(r.get("pnl"))<0)
    rej_spreads=[_number(r.get("spread_percent")) for r in rejected];rej_spreads=[v for v in rej_spreads if v is not None]
    ret_spreads=[_number(r.get("spread_percent")) for r in retained];ret_spreads=[v for v in ret_spreads if v is not None]
    return {"label":"SHADOW / COUNTERFACTUAL","broad_eligible":len(eligible),"filtered_opened":len(retained),
        "spread_rejected":len(rejected),"participation_rate":len(retained)/len(eligible)*100 if eligible else None,
        "rejected_mirror_winners":sum(_number(r.get("pnl"))>0 for r in matched),
        "rejected_mirror_losers":sum(_number(r.get("pnl"))<0 for r in matched),
        "rejected_mirror_flats":sum(_number(r.get("pnl"))==0 for r in matched),"unknown_shadow_outcomes":unknown,
        "pnl_avoided_from_losers":abs(loser_pnl),"pnl_sacrificed_from_winners":winner_pnl,
        "net_pnl_effect":-(winner_pnl+loser_pnl),"average_rejected_spread":mean(rej_spreads) if rej_spreads else None,
        "median_rejected_spread":median(rej_spreads) if rej_spreads else None,"average_retained_spread":mean(ret_spreads) if ret_spreads else None,
        "median_retained_spread":median(ret_spreads) if ret_spreads else None,"shadow_matches":len(matched)}


def signal_age_summary(lanes):
    result=[]
    for lane,rows in lanes.items():
        groups=defaultdict(list)
        for row in rows:groups[age_bucket(row.get("signal_age_seconds"))].append(row)
        for bucket,items in sorted(groups.items()):
            summary=lane_summary(items)
            result.append({"lane":lane,"bucket":bucket,"n":summary["closed"],"wins":summary["wins"],"losses":summary["losses"],
                "win_rate":summary["win_rate"],"average_return":summary["average_return"],"median_return":summary["median_return"],
                "total_pnl":summary["realized_pnl"],"expectancy":summary["expectancy"],"profit_factor":summary["profit_factor"],
                "average_spread":summary["average_spread"],"average_debit":_mean(items,"debit")})
    return result


def build_scorecard(authoritative,mirror,broad,filtered):
    sessions=sorted(set(r["session"] for rows in (mirror,broad,filtered) for r in rows if r.get("session")))
    auth_counts=defaultdict(int)
    for row in authoritative:auth_counts[row["session"]]+=1
    daily=[]
    for session in sessions:
        lanes={"MIRROR":[r for r in mirror if r.get("session")==session],"BROAD":[r for r in broad if r.get("session")==session],"FILTERED":[r for r in filtered if r.get("session")==session]}
        metrics={lane:lane_summary(rows,auth_counts.get(session)) for lane,rows in lanes.items()}
        shadow=spread_gate_effectiveness(lanes["FILTERED"],lanes["MIRROR"])
        daily.append({"session":session,"period":experiment_period(session),"lanes":metrics,"spread_gate":shadow})
        LOGGER.info(json.dumps({"event":"experiment_scorecard_reconciliation","session":session,
            "mirror_opened":metrics["MIRROR"]["opened"],"broad_opened":metrics["BROAD"]["opened"],
            "filtered_opened":metrics["FILTERED"]["opened"],"filtered_spread_rejected":shadow["spread_rejected"],
            "mirror_shadow_matches":shadow["shadow_matches"],"unknown_shadow_outcomes":shadow["unknown_shadow_outcomes"]},sort_keys=True))
    return {"sessions":sessions,"daily":daily,"cumulative":{lane:lane_summary(rows,sum(auth_counts.values())) for lane,rows in
        (("MIRROR",mirror),("BROAD",broad),("FILTERED",filtered))},"spread_gate":spread_gate_effectiveness(filtered,mirror),
        "signal_age":signal_age_summary({"MIRROR":mirror,"BROAD":broad,"FILTERED":filtered}),
        "governance":governance(sum(r.get("closed_at") is not None for r in filtered))}


class ExperimentScorecardRepository:
    """Projected, bounded reads; never initializes or mutates schema."""
    def __init__(self,repository):self.repository=repository
    def load(self,*,session_limit=10,period="ALL"):
        limit=10000 if session_limit is None else int(session_limit)
        with self.repository.connection() as connection:
            session_query="""SELECT session_date FROM (
                SELECT DISTINCT (entry_event_at::timestamptz AT TIME ZONE 'America/New_York')::date AS session_date FROM mirror_execution_trades
                UNION SELECT DISTINCT (authoritative_event_at::timestamptz AT TIME ZONE 'America/New_York')::date FROM filtered_execution_trades
                UNION SELECT DISTINCT (event_timestamp::timestamptz AT TIME ZONE 'America/New_York')::date FROM authoritative_trade_events WHERE event_type='TRADE_ENTERED'
                ) s WHERE session_date IS NOT NULL"""
            params=[]
            if period=="DEVELOPMENT":session_query+=" AND session_date>=? AND session_date<=?";params += ["2026-08-10","2026-08-13"]
            elif period=="FORWARD TEST":session_query+=" AND session_date>=?";params += ["2026-08-17"]
            session_query+=" ORDER BY session_date DESC LIMIT ?";params.append(limit)
            sessions=self.repository._fetchall(connection,session_query,tuple(params))
            dates=[str(r["session_date"]) for r in sessions]
            if not dates:return build_scorecard([],[],[],[])
            start,end=min(dates),max(dates)
            auth=self.repository._fetchall(connection,"""SELECT opportunity_id,event_timestamp FROM authoritative_trade_events
                WHERE event_type='TRADE_ENTERED' AND event_timestamp>=? AND event_timestamp<(?::date+INTERVAL '1 day')::text ORDER BY event_timestamp""",(start,end))
            mirror=self.repository._fetchall(connection,"""SELECT opportunity_id,entry_event_at AS signal_at,opened_at,exit_quote_at AS closed_at,
                realized_pnl AS pnl,unrealized_pnl,realized_return_percent AS return_pct,spread_percent,total_debit AS debit
                FROM mirror_execution_trades WHERE entry_event_at>=? AND entry_event_at<(?::date+INTERVAL '1 day')::text ORDER BY entry_event_at""",(start,end))
            broad=self.repository._fetchall(connection,"""SELECT t.source_signal_id AS opportunity_id,e.event_timestamp AS signal_at,t.opened_at,t.closed_at,
                t.realized_pnl_dollars AS pnl,p.unrealized_pnl_dollars AS unrealized_pnl,t.realized_return_pct AS return_pct,
                NULLIF(t.contract_metadata_json::jsonb->>'spread_percent','')::float AS spread_percent,t.total_debit AS debit
                FROM paper_execution_trades t JOIN authoritative_trade_events e ON e.opportunity_id=t.source_signal_id AND e.event_type='TRADE_ENTERED'
                LEFT JOIN paper_execution_positions p ON p.trade_id=t.trade_id
                WHERE e.event_timestamp>=? AND e.event_timestamp<(?::date+INTERVAL '1 day')::text AND EXISTS (SELECT 1 FROM paper_execution_journal j
                WHERE j.trade_id=t.trade_id AND UPPER(COALESCE(j.metadata_json::jsonb->>'simulation_profile',''))='BROAD') ORDER BY e.event_timestamp""",(start,end))
            filtered=self.repository._fetchall(connection,"""SELECT f.opportunity_id,f.authoritative_event_at AS signal_at,f.opened_at,f.closed_at,
                f.realized_pnl AS pnl,m.unrealized_pnl,f.realized_return_percent AS return_pct,f.spread_percent,f.total_debit AS debit,
                f.broad_decision,f.execution_rejection_reason AS rejection_reason,f.signal_age_seconds FROM filtered_execution_trades f
                LEFT JOIN mirror_execution_trades m ON m.opportunity_id=f.opportunity_id
                WHERE f.authoritative_event_at>=? AND f.authoritative_event_at<(?::date+INTERVAL '1 day')::text ORDER BY f.authoritative_event_at""",(start,end))
        normalized=[]
        for rows in (auth,mirror,broad,filtered):
            for row in rows:
                at=row.get("signal_at") or row.get("event_timestamp") or row.get("opened_at")
                row["session"]=_session(at)
                if "signal_age_seconds" not in row:row["signal_age_seconds"]=_seconds(row.get("signal_at"),row.get("opened_at"))
        return build_scorecard(auth,mirror,broad,filtered)


def _peak_capital(rows):
    points=[]
    for r in rows:
        debit=_number(r.get("debit"));start=_dt(r.get("opened_at"));end=_dt(r.get("closed_at"))
        if debit is not None and start:points.append((start,1,debit))
        if debit is not None and end:points.append((end,-1,debit))
    capital=peak=0
    for _,kind,debit in sorted(points,key=lambda x:(x[0],x[1])):capital+=kind*debit;peak=max(peak,capital)
    return peak
def _session(v):return _dt(v).astimezone(EASTERN).date().isoformat() if _dt(v) else None
def _seconds(a,b):return (_dt(b)-_dt(a)).total_seconds() if _dt(a) and _dt(b) else None
def _dt(v):
    if not v:return None
    x=v if isinstance(v,datetime) else datetime.fromisoformat(str(v).replace("Z","+00:00"));return x if x.tzinfo else x.replace(tzinfo=timezone.utc)
def _number(v):
    try:x=float(v);return x if math.isfinite(x) else None
    except (TypeError,ValueError):return None
def _mean(rows,key):
    values=[_number(r.get(key)) for r in rows];values=[v for v in values if v is not None];return mean(values) if values else None
