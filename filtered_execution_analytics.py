"""Read-only FILTERED/MIRROR experiment comparisons."""
from collections import defaultdict
import math
from statistics import mean


def filtered_comparison(filtered_rows, mirror_rows):
    mirrors={str(row.get("opportunity_id")):row for row in mirror_rows}
    rejected=[row for row in filtered_rows if row.get("execution_rejection_reason")=="SPREAD_TOO_WIDE"]
    retained=[row for row in filtered_rows if row.get("execution_eligible")]
    def mirror_pnl(rows): return sum(float(mirrors.get(str(r.get("opportunity_id")),{}).get("realized_pnl") or 0) for r in rows)
    buckets=defaultdict(list)
    for row in filtered_rows: buckets[str(row.get("signal_age_bucket") or "DATA UNAVAILABLE")].append(row)
    age=[]
    for label,rows in sorted(buckets.items()):
        returns=[float(r["realized_return_percent"]) for r in rows if r.get("realized_return_percent") is not None]
        pnl=[float(r["realized_pnl"]) for r in rows if r.get("realized_pnl") is not None]
        wins=[v for v in pnl if v>0]; losses=[v for v in pnl if v<0]
        age.append({"bucket":label,"n":len(returns),"win_rate":sum(v>0 for v in returns)/len(returns)*100 if returns else None,
                    "average_return":mean(returns) if returns else None,"pnl":sum(pnl),
                    "profit_factor":sum(wins)/abs(sum(losses)) if losses else math.inf if wins else None})
    loss_caps=[]
    for label,rkey,pkey in (("BASELINE","realized_return_percent","realized_pnl"),("SHADOW_-30%","shadow_30_return","shadow_30_pnl"),("SHADOW_-45%","shadow_45_return","shadow_45_pnl")):
        returns=[float(r[rkey]) for r in retained if r.get(rkey) is not None]; pnl=[float(r[pkey]) for r in retained if r.get(pkey) is not None]
        loss_caps.append({"variant":label,"n":len(returns),"average_return":mean(returns) if returns else None,"pnl":sum(pnl)})
    return {"spread_gate":{"rejected":len(rejected),"rejected_winners":sum(float(mirrors.get(str(r.get("opportunity_id")),{}).get("realized_pnl") or 0)>0 for r in rejected),
        "rejected_losers":sum(float(mirrors.get(str(r.get("opportunity_id")),{}).get("realized_pnl") or 0)<0 for r in rejected),
        "rejected_mirror_pnl":mirror_pnl(rejected),"retained_mirror_pnl":mirror_pnl(retained)},"signal_age":age,"loss_caps":loss_caps}
