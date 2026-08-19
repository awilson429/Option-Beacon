"""Pure analytics for the prospective QQQ first-two participation experiment."""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime
from statistics import median, pstdev
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")


def eastern_session(value):
    parsed=value if isinstance(value,datetime) else datetime.fromisoformat(str(value).replace("Z","+00:00"))
    return parsed.astimezone(EASTERN).date().isoformat()


def sequence_bucket(number):
    number=int(number)
    return "1st" if number==1 else "2nd" if number==2 else "3rd–5th" if number<=5 else "6th–10th" if number<=10 else "11th+"


def governance(accepted, sessions):
    if accepted < 10: return "INSUFFICIENT DATA"
    if accepted < 30: return "DESCRIPTIVE ONLY"
    if accepted < 50 or sessions < 20: return "UNSTABLE"
    return "ELIGIBLE FOR FORWARD EVALUATION"


def _metrics(rows):
    pnl=[float(r["realized_pnl"]) for r in rows if r.get("realized_pnl") is not None]
    returns=[float(r["realized_return_percent"]) for r in rows if r.get("realized_return_percent") is not None]
    wins=[v for v in pnl if v>0]; losses=[v for v in pnl if v<0]
    daily=defaultdict(float)
    for row in rows:
        if row.get("realized_pnl") is not None: daily[row["eastern_session"]]+=float(row["realized_pnl"])
    days=list(daily.values()); equity=peak=drawdown=0.0; consecutive=maximum_losses=0
    for value in pnl:
        equity+=value; peak=max(peak,equity); drawdown=min(drawdown,equity-peak)
        consecutive=consecutive+1 if value<0 else 0; maximum_losses=max(maximum_losses,consecutive)
    return {"sessions":len(daily),"trades":len(pnl),"wins":len(wins),"losses":len(losses),
        "win_rate":len(wins)/len(pnl)*100 if pnl else None,"total_pnl":sum(pnl),
        "expectancy":sum(pnl)/len(pnl) if pnl else None,"average_winner":sum(wins)/len(wins) if wins else None,
        "average_loser":sum(losses)/len(losses) if losses else None,
        "payoff_ratio":(sum(wins)/len(wins))/abs(sum(losses)/len(losses)) if wins and losses else None,
        "profit_factor":sum(wins)/abs(sum(losses)) if losses else None,"median_pnl":median(pnl) if pnl else None,
        "average_return":sum(returns)/len(returns) if returns else None,"median_return":median(returns) if returns else None,
        "profitable_session_percentage":sum(v>0 for v in days)/len(days)*100 if days else None,
        "losing_session_percentage":sum(v<0 for v in days)/len(days)*100 if days else None,
        "average_daily_pnl":sum(days)/len(days) if days else None,"median_daily_pnl":median(days) if days else None,
        "daily_pnl_standard_deviation":pstdev(days) if len(days)>1 else None,
        "max_observed_winner":max(pnl,default=None),"max_observed_loser":min(pnl,default=None),
        "maximum_consecutive_losses":maximum_losses,"worst_5_trade_sequence":min((sum(pnl[i:i+5]) for i in range(len(pnl)-4)),default=None),
        "worst_10_trade_sequence":min((sum(pnl[i:i+10]) for i in range(len(pnl)-9)),default=None),"realized_drawdown":drawdown}


def compare_first_two(rows, *, experiment_start_timestamp, now):
    today=now.astimezone(EASTERN).date().isoformat()
    forward=[dict(r) for r in rows if str(r.get("opened_at")) >= str(experiment_start_timestamp) and r.get("eastern_session") != today and r.get("closed_at")]
    baseline=_metrics(forward); accepted=[r for r in forward if r.get("shadow_status")=="SHADOW_ACCEPTED"]
    first_two=_metrics(accepted)
    difference={name:(first_two[name]-baseline[name] if first_two[name] is not None and baseline[name] is not None else None)
        for name in ("expectancy","profit_factor","profitable_session_percentage","daily_pnl_standard_deviation","realized_drawdown")}
    sessions=[]
    for day in sorted({r["eastern_session"] for r in forward}):
        base=[r for r in forward if r["eastern_session"]==day]; shadow=[r for r in accepted if r["eastern_session"]==day]
        bm,sm=_metrics(base),_metrics(shadow)
        sessions.append({"session":day,"baseline_trades":bm["trades"],"first_two_trades":sm["trades"],"baseline_pnl":bm["total_pnl"],"first_two_pnl":sm["total_pnl"],"baseline_win_rate":bm["win_rate"],"first_two_win_rate":sm["win_rate"],"difference":sm["total_pnl"]-bm["total_pnl"]})
    buckets={bucket:_metrics([r for r in forward if sequence_bucket(r["session_trade_number"])==bucket]) for bucket in ("1st","2nd","3rd–5th","6th–10th","11th+")}
    status=governance(len(accepted),first_two["sessions"]); decision="NOT YET ELIGIBLE"
    if status=="ELIGIBLE FOR FORWARD EVALUATION":
        decision=("SUCCESS" if first_two["expectancy"]>baseline["expectancy"] and first_two["profit_factor"]>=baseline["profit_factor"] else "FAILURE")
    return {"baseline":baseline,"first_two_shadow":{**first_two,"eligible_trades":len(forward),"accepted_trades":len(accepted),"rejected_trades":len(forward)-len(accepted),"participation_rate":len(accepted)/len(forward)*100 if forward else None},
        "difference":difference,"governance":status,"predeclared_decision":decision,"session_comparison":sessions,
        "sequence_buckets":buckets,"experiment_start_timestamp":experiment_start_timestamp,"current_session_excluded":today}
