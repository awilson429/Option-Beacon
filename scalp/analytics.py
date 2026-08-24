from __future__ import annotations

from statistics import mean, median


def performance(rows, *, grouped=True):
    rows=list(rows); closed=[r for r in rows if r.get("realistic_pnl") is not None]; pnl=[float(r["realistic_pnl"]) for r in closed]
    wins=[v for v in pnl if v>0]; losses=[v for v in pnl if v<0]; equity=peak=drawdown=0
    for value in pnl: equity+=value; peak=max(peak,equity); drawdown=max(drawdown,peak-equity)
    gross_win=sum(wins); gross_loss=abs(sum(losses))
    result={"opportunities":len(rows),"triggered_trades":len(closed),"win_rate":len(wins)/len(closed)*100 if closed else None,
      "average_winner":mean(wins) if wins else None,"average_loser":mean(losses) if losses else None,
      "expectancy":mean(pnl) if pnl else None,"profit_factor":gross_win/gross_loss if gross_loss else None,"net_simulated_pnl":sum(pnl),
      "maximum_drawdown":drawdown,"average_hold_minutes":mean([r["hold_minutes"] for r in closed if r.get("hold_minutes") is not None]) if any(r.get("hold_minutes") is not None for r in closed) else None,
      "median_hold_minutes":median([r["hold_minutes"] for r in closed if r.get("hold_minutes") is not None]) if any(r.get("hold_minutes") is not None for r in closed) else None,
      "average_mfe":mean([r["mfe"] for r in closed if r.get("mfe") is not None]) if any(r.get("mfe") is not None for r in closed) else None,
      "average_mae":mean([r["mae"] for r in closed if r.get("mae") is not None]) if any(r.get("mae") is not None for r in closed) else None,
      "ideal_pnl":sum(float(r.get("ideal_pnl") or 0) for r in closed)}
    result["evidence"]="INSUFFICIENT" if len(closed)<30 else "PRELIMINARY" if len(closed)<100 else "ESTABLISHED"
    if grouped:
        for dimension in ("setup_family","time_bucket","regime","direction","term"):
            result[f"by_{dimension}"]={key:performance([r for r in rows if r.get(dimension)==key], grouped=False) for key in sorted({r.get(dimension) for r in rows if r.get(dimension) is not None})}
    return result


def compare(spy_rows, qqq_rows):
    return {"SPY":performance(spy_rows),"QQQ":performance(qqq_rows),"normalization":"per triggered contract; realistic P&L primary"}
