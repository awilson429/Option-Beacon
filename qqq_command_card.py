"""Read-only presentation model and compact markup for the Trade Desk QQQ card."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from html import escape
from statistics import median
from zoneinfo import ZoneInfo

from qqq_forward_research import compare_first_two
from qqq_forward_research_dashboard import mark_coverage

EASTERN=ZoneInfo("America/New_York")


def _value(row,key,default=None):
    if isinstance(row,dict): return row.get(key,default)
    return getattr(row,key,default)


def _number(value):
    try: return float(value)
    except (TypeError,ValueError): return None


def _fmt(value,kind="text"):
    if value is None or value=="": return "—"
    if kind=="money": return f"${float(value):+,.2f}"
    if kind=="percent": return f"{float(value):.1f}%"
    if kind=="price": return f"{float(value):,.2f}"
    return str(value)


def load_qqq_command_data(repository, *, limit=500):
    """One bounded, explicit, read-only snapshot; never initializes schema."""
    with repository.connection() as connection:
        trades=repository._fetchall(connection,"""SELECT trade_id,opportunity_id,variant,symbol,direction,option_symbol,
            expiration,dte,strike,entry_bid,entry_ask,entry_fill,spread_percent,status,management_state,opened_at,closed_at,
            exit_fill,exit_reason,realized_pnl,realized_return_percent,mfe_pct,mae_pct,last_quote_at,updated_at
            FROM intraday_paper_trades WHERE symbol='QQQ' ORDER BY opened_at DESC,trade_id LIMIT ?""",(int(limit),))
        signals=repository._fetchall(connection,"""SELECT opportunity_id,direction,setup,underlying_price,trigger_price,state,
            session_bucket,regime,cross_market_json,detected_at,updated_at FROM intraday_signals
            WHERE symbol='QQQ' ORDER BY updated_at DESC LIMIT 10""")
        shadow=repository._fetchall(connection,"""SELECT source_trade_id,eastern_session,session_trade_number,shadow_status,
            rejection_reason,opened_at,closed_at,realized_pnl,realized_return_percent,variant
            FROM qqq_first_two_shadow_trades ORDER BY opened_at,source_trade_id LIMIT ?""",(int(limit),))
        experiment=repository._fetchone(connection,"""SELECT experiment_start_timestamp,experiment_start_session,rule_version
            FROM qqq_first_two_experiment WHERE experiment_id='QQQ_FIRST_TWO_SHADOW'""")
        marks=repository._fetchall(connection,"""SELECT trade_id,variant,eastern_session,observed_at,sequence_number
            FROM intraday_position_marks WHERE symbol='QQQ' ORDER BY observed_at DESC,trade_id LIMIT ?""",(int(limit),))
    return {"trades":trades,"signals":signals,"shadow":shadow,"experiment":experiment,"marks":marks}


def context_quality(evidence, *, stale=False):
    if stale: return {"label":"INSUFFICIENT CONTEXT","score":None}
    values=[]
    for key in ("vwap_aligned","ema_aligned","trend_aligned","orb_aligned","cross_confirmed","spread_tight","regime_available"):
        if evidence.get(key) is not None: values.append(bool(evidence[key]))
    if len(values)<3: return {"label":"INSUFFICIENT CONTEXT","score":None}
    score=round(sum(values)/len(values)*100)
    return {"label":"STRONG" if score>=75 else "MODERATE" if score>=45 else "LOW","score":score}


def _performance(rows):
    closed=[r for r in rows if _number(r.get("realized_pnl")) is not None]
    pnl=[float(r["realized_pnl"]) for r in closed]; wins=[v for v in pnl if v>0]; losses=[v for v in pnl if v<0]
    days=defaultdict(float)
    for row in closed: days[str(row.get("opened_at"))[:10]]+=float(row["realized_pnl"])
    return {"closed_trades":len(closed),"wins":len(wins),"losses":len(losses),"win_rate":len(wins)/len(pnl)*100 if pnl else None,
        "total_pnl":sum(pnl),"expectancy":sum(pnl)/len(pnl) if pnl else None,"average_winner":sum(wins)/len(wins) if wins else None,
        "average_loser":sum(losses)/len(losses) if losses else None,"payoff_ratio":(sum(wins)/len(wins))/abs(sum(losses)/len(losses)) if wins and losses else None,
        "profit_factor":sum(wins)/abs(sum(losses)) if losses else None,"profitable_session_percentage":sum(v>0 for v in days.values())/len(days)*100 if days else None,
        "best_trade":max(pnl,default=None),"worst_trade":min(pnl,default=None),"average_trade":sum(pnl)/len(pnl) if pnl else None}


def build_qqq_command_card_model(latest_qqq, data, *, now, market_open, stale=False, active_setup=False):
    now_et=now.astimezone(EASTERN); trades=list(data.get("trades") or []); signals=list(data.get("signals") or [])
    signal=signals[0] if signals else {}; live=latest_qqq or {}; plan=live.get("trade_plan") or {}; today=now_et.date().isoformat()
    def session(row):
        try: return datetime.fromisoformat(str(row.get("opened_at")).replace("Z","+00:00")).astimezone(EASTERN).date().isoformat()
        except (TypeError,ValueError): return None
    today_rows=[row for row in trades if session(row)==today]
    completed=[row for row in trades if session(row)!=today]
    pulse=_performance(today_rows); edge=_performance(completed)
    latest_trade=trades[0] if trades else {}; stamp=signal.get("updated_at") or live.get("timestamp") or latest_trade.get("updated_at")
    try:
        parsed=datetime.fromisoformat(str(stamp).replace("Z","+00:00")); age=(now-parsed.astimezone(timezone.utc)).total_seconds(); stale=stale or age>300
    except (TypeError,ValueError): age=None
    if not market_open: status="MARKET CLOSED"
    elif stale: status="DATA STALE"
    elif active_setup: status="ACTIVE SETUP"
    elif signal: status="WATCHING" if signal.get("state") in {"ARMED","SETUP_DETECTED","TRIGGERED"} else "NO QUALIFYING SETUP"
    else: status="DATA UNAVAILABLE" if not live and not trades else "NO QUALIFYING SETUP"
    direction=plan.get("direction") or signal.get("direction") or live.get("bias") or latest_trade.get("direction") or "NEUTRAL"
    direction="CALL" if str(direction).upper() in {"BULLISH","CALL"} else "PUT" if str(direction).upper() in {"BEARISH","PUT"} else "NEUTRAL"
    spread=_number(latest_trade.get("spread_percent")); sequence=max((int(r.get("session_trade_number") or 0) for r in data.get("shadow") or [] if r.get("eastern_session")==today),default=0)
    evidence={"vwap_aligned":live.get("price_vs_vwap") is not None,"ema_aligned":live.get("ema_aligned"),
        "trend_aligned":live.get("multi_timeframe_alignment") is not None,"orb_aligned":live.get("opening_range_state") is not None,
        "cross_confirmed":bool(live.get("cross_market") or signal.get("cross_market_json")),"spread_tight":None if spread is None else spread<=15,
        "regime_available":bool(signal.get("regime") or live.get("regime"))}
    chips=[]
    if live.get("price_vs_vwap"): chips.append(f'VWAP {str(live["price_vs_vwap"]).upper()}')
    if live.get("ema_aligned") is not None: chips.append("EMA ALIGNED" if live["ema_aligned"] else "EMA CONFLICT")
    if live.get("opening_range_state"): chips.append(str(live["opening_range_state"]).upper())
    if evidence["cross_confirmed"]: chips.append("CROSS CONFIRMED")
    if spread is not None: chips.append("SPREAD TIGHT" if spread<=15 else "SPREAD WIDE")
    if sequence: chips.append(f"TRADE #{sequence}")
    first_two=None
    if data.get("experiment"):
        first_two=compare_first_two(data.get("shadow") or [],experiment_start_timestamp=data["experiment"]["experiment_start_timestamp"],now=now)
    dna={"direction":{key:_performance([r for r in completed if str(r.get("direction")).upper()==key]) for key in ("CALL","PUT")},
        "dte":{str(key):_performance([r for r in completed if r.get("dte")==key]) for key in (0,1)},
        "average_mfe":sum(float(r["mfe_pct"]) for r in completed if r.get("mfe_pct") is not None)/sum(r.get("mfe_pct") is not None for r in completed) if any(r.get("mfe_pct") is not None for r in completed) else None,
        "average_mae":sum(float(r["mae_pct"]) for r in completed if r.get("mae_pct") is not None)/sum(r.get("mae_pct") is not None for r in completed) if any(r.get("mae_pct") is not None for r in completed) else None}
    return {"status":status,"price":live.get("price") or signal.get("underlying_price"),"bias":direction,
        "regime":signal.get("regime") or live.get("regime"),"setup":plan.get("setup_type") or plan.get("setup") or signal.get("setup"),
        "tradeability":signal.get("state"),"trigger":plan.get("trigger_price") or signal.get("trigger_price"),
        "contract":latest_trade.get("option_symbol"),"strike":latest_trade.get("strike"),"expiration":latest_trade.get("expiration"),
        "dte":latest_trade.get("dte"),"bid":latest_trade.get("entry_bid"),"ask":latest_trade.get("entry_ask"),
        "midpoint":((_number(latest_trade.get("entry_bid"))+_number(latest_trade.get("entry_ask")))/2 if _number(latest_trade.get("entry_bid")) is not None and _number(latest_trade.get("entry_ask")) is not None else None),
        "spread":spread,"updated_at":stamp,"chips":chips,"context_quality":context_quality(evidence,stale=stale),
        "session_pulse":pulse,"session_trade_number":sequence,"first_two":first_two,"edge_snapshot":edge,
        "mark_coverage":mark_coverage(data.get("shadow") or [],data.get("marks") or []),"dna_summary":dna,"market_open":market_open}


def qqq_command_card_markup(model):
    metric=lambda label,value:f'<div class="ob-qqq-metric"><span>{escape(label)}</span><strong>{escape(str(value))}</strong></div>'
    quality=model["context_quality"]; pulse=model["session_pulse"]; edge=model["edge_snapshot"]; ft=model.get("first_two"); coverage=model["mark_coverage"]
    live="".join(metric(label,value) for label,value in (("Price",_fmt(model["price"],"price")),("Bias",model["bias"]),("Regime",_fmt(model["regime"])),("Setup",_fmt(model["setup"])),("Trigger",_fmt(model["trigger"],"price")),("Contract",_fmt(model["contract"])),("DTE",_fmt(model["dte"])),("Spread",_fmt(model["spread"],"percent"))))
    chips="".join(f'<span class="ob-qqq-chip">{escape(chip)}</span>' for chip in model["chips"]) or '<span class="ob-qqq-muted">Context evidence unavailable</span>'
    first_two=('Forward experiment begins with post-deployment QQQ trades.' if not ft else f'{ft["first_two_shadow"]["accepted_trades"]} / 50 accepted · {ft["first_two_shadow"]["sessions"]} / 20 sessions · {ft["governance"]}<br>Expectancy {_fmt(ft["baseline"]["expectancy"],"money")} → {_fmt(ft["first_two_shadow"]["expectancy"],"money")} · PF {_fmt(ft["baseline"]["profit_factor"])} → {_fmt(ft["first_two_shadow"]["profit_factor"])}')
    pulse_html="".join(metric(a,b) for a,b in (("Trades",pulse["closed_trades"]),("W / L",f'{pulse["wins"]} / {pulse["losses"]}'),("Win rate",_fmt(pulse["win_rate"],"percent")),("P&L",_fmt(pulse["total_pnl"],"money")),("Average",_fmt(pulse["average_trade"],"money")),("Best / Worst",f'{_fmt(pulse["best_trade"],"money")} / {_fmt(pulse["worst_trade"],"money")}')))
    edge_html="".join(metric(a,b) for a,b in (("Closed",edge["closed_trades"]),("Expectancy",_fmt(edge["expectancy"],"money")),("Profit factor",_fmt(edge["profit_factor"])),("Win rate",_fmt(edge["win_rate"],"percent")),("Avg winner",_fmt(edge["average_winner"],"money")),("Avg loser",_fmt(edge["average_loser"],"money")),("Payoff",_fmt(edge["payoff_ratio"])),("Profitable sessions",_fmt(edge["profitable_session_percentage"],"percent"))))
    dna=model["dna_summary"]
    dna_text=(f'CALL: {dna["direction"]["CALL"]["closed_trades"]} trades, {_fmt(dna["direction"]["CALL"]["expectancy"],"money")} expectancy · '
        f'PUT: {dna["direction"]["PUT"]["closed_trades"]} trades, {_fmt(dna["direction"]["PUT"]["expectancy"],"money")} expectancy<br>'
        f'0DTE: {_fmt(dna["dte"]["0"]["expectancy"],"money")} · 1DTE: {_fmt(dna["dte"]["1"]["expectancy"],"money")} · '
        f'Average MFE/MAE: {_fmt(dna["average_mfe"],"percent")} / {_fmt(dna["average_mae"],"percent")}')
    return f'''<style>.ob-qqq{{border:1px solid #273344;border-radius:14px;background:#101722;padding:16px;color:#e8edf3}}.ob-qqq-head{{display:flex;justify-content:space-between;gap:12px;align-items:center}}.ob-qqq-head h3{{margin:0;font-size:1.25rem}}.ob-qqq-status{{border:1px solid #3b526b;border-radius:999px;padding:4px 9px;font-size:.72rem;font-weight:750}}.ob-qqq-grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-top:12px}}.ob-qqq-metric{{border-left:2px solid #29394c;padding:4px 8px;min-width:0}}.ob-qqq-metric span{{display:block;color:#8f9cab;font-size:.68rem;text-transform:uppercase}}.ob-qqq-metric strong{{font-size:.88rem;overflow-wrap:anywhere}}.ob-qqq-chips{{display:flex;gap:6px;flex-wrap:wrap;margin:12px 0}}.ob-qqq-chip{{background:#1b2735;border-radius:999px;padding:4px 8px;font-size:.7rem}}.ob-qqq-section{{border-top:1px solid #263241;padding-top:10px;margin-top:10px}}.ob-qqq-section h4{{font-size:.72rem;letter-spacing:.08em;margin:0 0 7px;color:#9aa7b5}}.ob-qqq-note,.ob-qqq-muted{{color:#8f9cab;font-size:.75rem}}.ob-qqq details summary{{cursor:pointer;font-size:.78rem;font-weight:700}}@media(max-width:700px){{.ob-qqq-grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}</style><section class="ob-qqq"><div class="ob-qqq-head"><div><h3>QQQ COMMAND CARD</h3><span class="ob-qqq-note">{escape(_fmt(model["updated_at"]))}</span></div><span class="ob-qqq-status">{escape(model["status"])}</span></div><div class="ob-qqq-grid">{live}</div><div class="ob-qqq-chips">{chips}</div><div class="ob-qqq-section"><h4>CONTEXT QUALITY</h4><strong>{escape(quality["label"])}{f' · {quality["score"]}/100' if quality["score"] is not None else ''}</strong></div><div class="ob-qqq-section"><h4>SESSION PULSE · {'IN PROGRESS' if model['market_open'] else 'SESSION COMPLETE'}</h4><div class="ob-qqq-grid">{pulse_html}</div></div><div class="ob-qqq-section"><h4>FIRST_TWO FORWARD TEST</h4><span>{first_two}</span></div><div class="ob-qqq-section"><h4>QQQ EDGE SNAPSHOT</h4><div class="ob-qqq-grid">{edge_html}</div><span class="ob-qqq-note">Historical / forward research metrics only</span></div><div class="ob-qqq-section"><h4>MARK COVERAGE</h4><span>{coverage['positions_with_1_or_more_marks']} trades with marks · {_fmt(coverage['average_marks_per_trade'])} average marks/trade · {len(coverage['missing_mark_trades'])} missing</span></div><div class="ob-qqq-section"><details><summary>QQQ DNA</summary><p class="ob-qqq-note">CALL/PUT, DTE, sequence, MIRROR/MANAGED, session and mark attribution remain descriptive research only. Open Developer Tools for the complete forensic detail.</p></details></div></section>'''
