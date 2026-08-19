"""Read-only presentation model and compact markup for the Trade Desk QQQ card."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from html import escape
from statistics import median
from zoneinfo import ZoneInfo
import re

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


def _compact_qqq_command_card_markup(model):
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


def format_contract_label(contract, *, strike=None, expiration=None, bias=None):
    match=re.fullmatch(r"([A-Z]+)(\d{6})([CP])(\d{8})",str(contract or "").upper())
    if match:
        symbol,date_value,kind,strike_value=match.groups(); parsed=datetime.strptime(date_value,"%y%m%d")
        return f'{symbol} ${int(strike_value)/1000:g} {"Call" if kind=="C" else "Put"} · {parsed.strftime("%b")} {parsed.day}'
    if strike is not None and expiration:
        try: parsed=datetime.fromisoformat(str(expiration)); date_label=f'{parsed.strftime("%b")} {parsed.day}'
        except ValueError: date_label=str(expiration)
        kind="Call" if str(bias).upper()=="CALL" else "Put" if str(bias).upper()=="PUT" else "Option"
        return f'QQQ ${float(strike):g} {kind} · {date_label}'
    return "No active contract"


def format_card_timestamp(value):
    if not value: return "Update time unavailable"
    try:
        parsed=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        if parsed.tzinfo is None: parsed=parsed.replace(tzinfo=timezone.utc)
        return f'Updated {parsed.astimezone(EASTERN).strftime("%I:%M %p").lstrip("0")} ET'
    except (TypeError,ValueError): return "Update time unavailable"


def _ratio(value, suffix=""):
    number=_number(value)
    return "—" if number is None else f"{number:.2f}{suffix}"


def qqq_command_card_markup(model):
    """One cohesive card with client-side pills; switching views performs no rerun."""
    pulse=model["session_pulse"];edge=model["edge_snapshot"];ft=model.get("first_two");quality=model["context_quality"];coverage=model["mark_coverage"]
    def metric(label,value,priority=""):
        return f'<div class="ob-qpill-metric {priority}"><span>{escape(label)}</span><strong>{escape(str(value))}</strong></div>'
    contract=format_contract_label(model.get("contract"),strike=model.get("strike"),expiration=model.get("expiration"),bias=model.get("bias"))
    sequence=f'Trade #{model["session_trade_number"]}' if (model.get("session_trade_number") or 0)>0 else "No active trade"
    chips="".join(f'<span class="ob-qpill-chip">{escape(chip)}</span>' for chip in model["chips"] if chip and "TRADE #0" not in chip) or '<span class="ob-qpill-muted">Context confirmations unavailable</span>'
    overview="".join(metric(*item) for item in (("Setup State","CURRENT SETUP" if model["market_open"] else "LAST SESSION SETUP"),("Trigger",_fmt(model["trigger"],"price")),("Contract",contract),("Strike",_fmt(model["strike"],"price")),("Expiration",_fmt(model["expiration"])),("DTE",_fmt(model["dte"])),("Spread",_fmt(model["spread"],"percent")),("Trade State",sequence)))
    session="".join(metric(label,value,"is-primary" if label=="P&L" else "") for label,value in (("Trades",pulse["closed_trades"]),("W/L",f'{pulse["wins"]}/{pulse["losses"]}'),("Win Rate",_fmt(pulse["win_rate"],"percent")),("P&L",_fmt(pulse["total_pnl"],"money")),("Average",_fmt(pulse["average_trade"],"money")),("Best",_fmt(pulse["best_trade"],"money")),("Worst",_fmt(pulse["worst_trade"],"money"))))
    edge_markup="".join(metric(*item) for item in (("Closed Trades",edge["closed_trades"]),("Expectancy",_fmt(edge["expectancy"],"money")),("Profit Factor",_ratio(edge["profit_factor"])),("Win Rate",_fmt(edge["win_rate"],"percent")),("Avg Winner",_fmt(edge["average_winner"],"money")),("Avg Loser",_fmt(edge["average_loser"],"money")),("Payoff",_ratio(edge["payoff_ratio"],"x")),("Profitable Sessions",_fmt(edge["profitable_session_percentage"],"percent"))))
    if ft:
        shadow=ft["first_two_shadow"]
        first_two=f'<strong>{escape(ft["governance"])}</strong><span>{shadow["accepted_trades"]}/50 accepted · {shadow["sessions"]}/20 sessions · {_fmt(shadow["total_pnl"],"money")} P&L · {_fmt(shadow["expectancy"],"money")} expectancy</span>'
    else:first_two='<strong>AWAITING SAMPLE</strong><span>Awaiting post-deployment sample</span>'
    marks=(f'<strong>{coverage["positions_with_1_or_more_marks"]} trades marked</strong><span>{_ratio(coverage["average_marks_per_trade"])} average marks/trade · {len(coverage["missing_mark_trades"])} missing</span>' if coverage.get("positions_with_1_or_more_marks") else '<strong>MARK TELEMETRY</strong><span>Awaiting observations</span>')
    default="overview" if model["market_open"] else "session"
    checked=lambda name:' checked' if name==default else ''
    return f'''<style>.ob-qpill{{background:#101722;border:1px solid #273344;border-radius:14px;color:#e8edf3;padding:13px}}.ob-qpill-head{{align-items:center;display:flex;gap:12px;justify-content:space-between}}.ob-qpill-identity{{align-items:baseline;display:flex;flex-wrap:wrap;gap:7px 14px}}.ob-qpill-symbol{{font-size:1.08rem;font-weight:850}}.ob-qpill-price{{font-size:1.48rem;font-weight:850}}.ob-qpill-bias{{font-size:.8rem;font-weight:800}}.ob-qpill-context{{color:#a8b3bf;font-size:.73rem}}.ob-qpill-status{{border:1px solid #3b526b;border-radius:999px;font-size:.67rem;font-weight:800;padding:4px 9px;white-space:nowrap}}.ob-qpill-update,.ob-qpill-muted{{color:#82909f;font-size:.62rem}}.ob-qpill>input{{height:0;opacity:0;position:absolute;width:0}}.ob-qpill-nav{{background:#151f2b;border-radius:999px;display:flex;gap:3px;margin-top:9px;padding:3px;width:max-content;max-width:100%}}.ob-qpill-nav label{{border-radius:999px;color:#8d9aa8;cursor:pointer;font-size:.62rem;font-weight:800;padding:5px 11px}}#qqq-view-overview:checked~.ob-qpill-nav label[for=qqq-view-overview],#qqq-view-session:checked~.ob-qpill-nav label[for=qqq-view-session],#qqq-view-edge:checked~.ob-qpill-nav label[for=qqq-view-edge],#qqq-view-research:checked~.ob-qpill-nav label[for=qqq-view-research]{{background:#263548;color:#f0f3f6}}.ob-qpill-pane{{display:none;min-height:72px;padding-top:10px}}#qqq-view-overview:checked~.ob-qpill-panes .is-overview,#qqq-view-session:checked~.ob-qpill-panes .is-session,#qqq-view-edge:checked~.ob-qpill-panes .is-edge,#qqq-view-research:checked~.ob-qpill-panes .is-research{{display:block}}.ob-qpill-metrics{{display:grid;gap:8px;grid-template-columns:repeat(4,minmax(0,1fr))}}.ob-qpill-metric{{min-width:0}}.ob-qpill-metric span{{color:#82909f;display:block;font-size:.57rem;text-transform:uppercase}}.ob-qpill-metric strong{{font-size:.76rem;overflow-wrap:anywhere}}.ob-qpill-session{{grid-template-columns:repeat(7,minmax(0,1fr))}}.ob-qpill-session .is-primary strong{{font-size:1.15rem}}.ob-qpill-chips{{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px}}.ob-qpill-chip{{background:#1b2735;border-radius:999px;font-size:.62rem;padding:3px 7px}}.ob-qpill-subrow{{align-items:flex-start;display:grid;gap:12px;grid-template-columns:1fr 1fr;margin-top:9px}}.ob-qpill-block h4{{color:#8e9baa;font-size:.62rem;letter-spacing:.07em;margin:0 0 4px}}.ob-qpill-block div{{display:flex;flex-direction:column;font-size:.68rem;gap:2px}}.ob-qpill-research{{display:grid;gap:12px;grid-template-columns:repeat(3,minmax(0,1fr))}}.ob-qpill-dna{{grid-column:1/-1}}.ob-qpill-dna summary{{cursor:pointer;font-size:.67rem;font-weight:800}}@media(max-width:850px){{.ob-qpill-metrics,.ob-qpill-session{{grid-template-columns:repeat(2,minmax(0,1fr))}}.ob-qpill-research{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}@media(max-width:560px){{.ob-qpill-head{{align-items:flex-start;flex-direction:column}}.ob-qpill-nav{{overflow-x:auto;width:100%}}.ob-qpill-nav label{{flex:1;text-align:center;white-space:nowrap}}.ob-qpill-metrics,.ob-qpill-session,.ob-qpill-subrow,.ob-qpill-research{{grid-template-columns:minmax(0,1fr)}}}}</style><section class="ob-qpill"><div class="ob-qpill-head"><div><div class="ob-qpill-identity"><span class="ob-qpill-symbol">QQQ</span><strong class="ob-qpill-price">{escape(_fmt(model["price"],"price"))}</strong><span class="ob-qpill-bias">{escape(model["bias"])} BIAS</span><span class="ob-qpill-context">{escape(_fmt(model["regime"]))} · {escape(_fmt(model["setup"]))}</span></div><div class="ob-qpill-update">{escape(format_card_timestamp(model.get("updated_at")))}</div></div><span class="ob-qpill-status">{escape(model["status"])}</span></div><input type="radio" name="qqq-command-view" id="qqq-view-overview"{checked("overview")}><input type="radio" name="qqq-command-view" id="qqq-view-session"{checked("session")}><input type="radio" name="qqq-command-view" id="qqq-view-edge"{checked("edge")}><input type="radio" name="qqq-command-view" id="qqq-view-research"{checked("research")}><nav class="ob-qpill-nav" aria-label="QQQ command views"><label for="qqq-view-overview">OVERVIEW</label><label for="qqq-view-session">SESSION</label><label for="qqq-view-edge">EDGE</label><label for="qqq-view-research">RESEARCH</label></nav><div class="ob-qpill-panes"><div class="ob-qpill-pane is-overview"><div class="ob-qpill-metrics">{overview}</div><div class="ob-qpill-subrow"><div class="ob-qpill-block"><h4>CONTEXT QUALITY</h4><strong>{escape(quality["label"])}{f' · {quality["score"]}/100' if quality["score"] is not None else ''}</strong></div><div class="ob-qpill-chips">{chips}</div></div></div><div class="ob-qpill-pane is-session"><h4>{'SESSION ACTIVE' if model['market_open'] else 'SESSION COMPLETE'}</h4><div class="ob-qpill-metrics ob-qpill-session">{session}</div><div class="ob-qpill-block"><h4>FIRST TWO</h4><div>{first_two}</div></div></div><div class="ob-qpill-pane is-edge"><span class="ob-qpill-muted">Historical / forward research only</span><div class="ob-qpill-metrics">{edge_markup}</div></div><div class="ob-qpill-pane is-research"><div class="ob-qpill-research"><div class="ob-qpill-block"><h4>CONTEXT QUALITY</h4><div><strong>{escape(quality["label"])}{f' · {quality["score"]}/100' if quality["score"] is not None else ''}</strong><span>Supporting context remains descriptive.</span></div></div><div class="ob-qpill-block"><h4>MARK COVERAGE</h4><div>{marks}</div></div><div class="ob-qpill-block"><h4>FIRST_TWO GOVERNANCE</h4><div>{first_two}<span>Sequence and overtrading research remains predeclared.</span></div></div><details class="ob-qpill-dna"><summary>QQQ DNA</summary><p class="ob-qpill-muted">CALL/PUT, 0DTE/1DTE, time, sequence, re-entry, spread, setup, regime, MFE/MAE and FIRST_TWO attribution remain descriptive research only.</p></details></div></div></div></section>'''


def _horizontal_band_qqq_command_card_markup(model):
    """Compact market-adaptive horizontal bands using the existing model."""
    pulse=model["session_pulse"];edge=model["edge_snapshot"];ft=model.get("first_two");quality=model["context_quality"];coverage=model["mark_coverage"]
    def metric(label,value,priority=""):
        return f'<div class="ob-qband-metric {priority}"><span>{escape(label)}</span><strong>{escape(str(value))}</strong></div>'
    contract=format_contract_label(model.get("contract"),strike=model.get("strike"),expiration=model.get("expiration"),bias=model.get("bias"))
    sequence=f'Trade #{model["session_trade_number"]}' if (model.get("session_trade_number") or 0)>0 else "No active trade"
    setup="".join(metric(*item) for item in (("Trigger",_fmt(model["trigger"],"price")),("Contract",contract),("DTE",_fmt(model["dte"])),("Spread",_fmt(model["spread"],"percent")),("State",sequence)))
    chips="".join(f'<span class="ob-qband-chip">{escape(chip)}</span>' for chip in model["chips"]) or '<span class="ob-qband-muted">Context confirmations unavailable</span>'
    session="".join(metric(label,value,"is-primary" if label=="P&L" else "") for label,value in (("Trades",pulse["closed_trades"]),("W/L",f'{pulse["wins"]}/{pulse["losses"]}'),("Win Rate",_fmt(pulse["win_rate"],"percent")),("P&L",_fmt(pulse["total_pnl"],"money")),("Average",_fmt(pulse["average_trade"],"money")),("Best",_fmt(pulse["best_trade"],"money")),("Worst",_fmt(pulse["worst_trade"],"money"))))
    edge_markup="".join(metric(*item) for item in (("Closed",edge["closed_trades"]),("Expectancy",_fmt(edge["expectancy"],"money")),("Profit Factor",_ratio(edge["profit_factor"])),("Win Rate",_fmt(edge["win_rate"],"percent")),("Avg Win",_fmt(edge["average_winner"],"money")),("Avg Loss",_fmt(edge["average_loser"],"money")),("Payoff",_ratio(edge["payoff_ratio"],"x")),("Profitable Sessions",_fmt(edge["profitable_session_percentage"],"percent"))))
    if ft:
        shadow=ft["first_two_shadow"]
        first_two=f'<strong>{escape(ft["governance"])}</strong><span>{shadow["accepted_trades"]}/50 accepted · {shadow["sessions"]}/20 sessions · {_fmt(shadow["total_pnl"],"money")} P&L · {_fmt(shadow["expectancy"],"money")} expectancy</span>'
    else:first_two='<strong>AWAITING SAMPLE</strong><span>Post-deployment observations have not accumulated.</span>'
    coverage_text=(f'{coverage["positions_with_1_or_more_marks"]} marked · {_ratio(coverage["average_marks_per_trade"])} avg/trade · {len(coverage["missing_mark_trades"])} missing' if coverage.get("positions_with_1_or_more_marks") else "Ordered-mark coverage awaiting observations")
    session_state="SESSION ACTIVE" if model["market_open"] else "SESSION COMPLETE";adaptive="is-live" if model["market_open"] else "is-closed"
    return f'''<style>.ob-qband{{background:#101722;border:1px solid #273344;border-radius:14px;color:#e8edf3;padding:13px}}.ob-qband-hero{{align-items:center;display:flex;gap:13px;justify-content:space-between}}.ob-qband-identity{{align-items:baseline;display:flex;flex-wrap:wrap;gap:7px 14px}}.ob-qband-symbol{{font-size:1.05rem;font-weight:850}}.ob-qband-price{{font-size:1.55rem;font-weight:850}}.ob-qband-bias{{font-size:.82rem;font-weight:800}}.ob-qband-context{{color:#a8b3bf;font-size:.75rem}}.ob-qband-status{{border:1px solid #3b526b;border-radius:999px;font-size:.68rem;font-weight:800;padding:4px 9px;white-space:nowrap}}.ob-qband-update{{color:#7f8d9b;font-size:.62rem;margin-top:2px}}.ob-qband-setup,.ob-qband-session{{display:grid;gap:8px;grid-template-columns:repeat(5,minmax(0,1fr));margin-top:9px}}.ob-qband-session{{background:#151f2b;border:1px solid #273344;border-radius:9px;grid-template-columns:repeat(8,minmax(0,1fr));padding:8px}}.ob-qband-metric{{min-width:0}}.ob-qband-metric span{{color:#82909f;display:block;font-size:.57rem;text-transform:uppercase}}.ob-qband-metric strong{{font-size:.76rem;overflow-wrap:anywhere}}.ob-qband-session .is-primary strong{{font-size:1.12rem}}.ob-qband-chips{{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px}}.ob-qband-chip{{background:#1b2735;border-radius:999px;font-size:.62rem;padding:3px 7px}}.ob-qband-intel{{display:grid;gap:9px;grid-template-columns:1.6fr .9fr .9fr;margin-top:9px}}.ob-qband-panel{{border-left:1px solid #273344;min-width:0;padding-left:10px}}.ob-qband-panel:first-child{{border-left:0;padding-left:0}}.ob-qband-panel h4{{color:#8e9baa;font-size:.62rem;letter-spacing:.08em;margin:0 0 5px}}.ob-qband-edge{{display:grid;gap:5px;grid-template-columns:repeat(4,minmax(0,1fr))}}.ob-qband-first{{display:flex;flex-direction:column;font-size:.68rem;gap:3px}}.ob-qband-first span,.ob-qband-muted{{color:#82909f;font-size:.63rem}}.ob-qband-quality{{font-size:.72rem}}.ob-qband-dna{{border-top:1px solid #273344;margin-top:9px;padding-top:7px}}.ob-qband-dna summary{{cursor:pointer;font-size:.68rem;font-weight:800}}.ob-qband.is-closed .ob-qband-session{{border-color:#405165}}.ob-qband.is-closed .ob-qband-setup{{opacity:.7}}@media(max-width:1000px){{.ob-qband-intel{{grid-template-columns:repeat(2,minmax(0,1fr))}}.ob-qband-quality-panel{{grid-column:1/-1}}.ob-qband-session{{grid-template-columns:repeat(4,minmax(0,1fr))}}}}@media(max-width:700px){{.ob-qband-hero{{align-items:flex-start;flex-direction:column;gap:7px}}.ob-qband-setup,.ob-qband-session,.ob-qband-edge,.ob-qband-intel{{grid-template-columns:minmax(0,1fr)}}.ob-qband-panel,.ob-qband-panel:first-child{{border-left:0;border-top:1px solid #273344;padding:8px 0 0}}}}</style><section class="ob-qband {adaptive}"><div class="ob-qband-hero"><div><div class="ob-qband-identity"><span class="ob-qband-symbol">QQQ</span><strong class="ob-qband-price">{escape(_fmt(model["price"],"price"))}</strong><span class="ob-qband-bias">{escape(model["bias"])} BIAS</span><span class="ob-qband-context">{escape(_fmt(model["regime"]))} · {escape(_fmt(model["setup"]))}</span></div><div class="ob-qband-update">{escape(format_card_timestamp(model.get("updated_at")))}</div></div><span class="ob-qband-status">{escape(model["status"])}</span></div><div class="ob-qband-setup">{setup}</div><div class="ob-qband-chips">{chips}</div><div class="ob-qband-session">{metric("Session",session_state)}{session}</div><div class="ob-qband-intel"><div class="ob-qband-panel"><h4>QQQ EDGE</h4><div class="ob-qband-edge">{edge_markup}</div></div><div class="ob-qband-panel"><h4>FIRST_TWO</h4><div class="ob-qband-first">{first_two}</div></div><div class="ob-qband-panel ob-qband-quality-panel"><h4>TRADE / DATA QUALITY</h4><div class="ob-qband-quality"><strong>{escape(quality["label"])}{f' · {quality["score"]}/100' if quality["score"] is not None else ''}</strong><div>{escape(coverage_text)}</div></div></div></div><div class="ob-qband-dna"><details><summary>QQQ DNA</summary><p class="ob-qband-muted">CALL/PUT, DTE, sequence, MIRROR/MANAGED, MFE/MAE, session and mark attribution remain descriptive research only. Complete detail remains in Developer Tools.</p></details></div></section>'''


def _three_zone_qqq_command_card_markup(model):
    """Wide three-zone instrument panel; the DNA disclosure remains full-width."""
    def metrics(items, css="ob-qqq-wide-metrics"):
        return f'<div class="{css}">'+"".join(
            f'<div><span>{escape(label)}</span><strong>{escape(str(value))}</strong></div>' for label,value in items)+"</div>"
    pulse=model["session_pulse"]; edge=model["edge_snapshot"]; quality=model["context_quality"]; ft=model.get("first_two"); coverage=model["mark_coverage"]
    chips="".join(f'<span class="ob-qqq-chip">{escape(chip)}</span>' for chip in model["chips"]) or '<span class="ob-qqq-muted">Context evidence unavailable</span>'
    left=metrics((("Price",_fmt(model["price"],"price")),("Bias",model["bias"]),("Regime",_fmt(model["regime"])),("Setup",_fmt(model["setup"])),("Trigger",_fmt(model["trigger"],"price"))))
    center=metrics((("Contract",_fmt(model["contract"])),("Strike",_fmt(model["strike"],"price")),("Expiration",_fmt(model["expiration"])),("DTE",_fmt(model["dte"])),("Spread",_fmt(model["spread"],"percent")),("Trade #",_fmt(model["session_trade_number"]))))
    pulse_html=metrics((("Trades",pulse["closed_trades"]),("W/L",f'{pulse["wins"]}/{pulse["losses"]}'),("Win rate",_fmt(pulse["win_rate"],"percent")),("P&L",_fmt(pulse["total_pnl"],"money")),("Avg",_fmt(pulse["average_trade"],"money")),("Best",_fmt(pulse["best_trade"],"money")),("Worst",_fmt(pulse["worst_trade"],"money"))),"ob-qqq-pulse")
    first_two="Forward experiment begins with post-deployment QQQ trades." if not ft else f'{ft["first_two_shadow"]["accepted_trades"]}/50 accepted · {ft["first_two_shadow"]["sessions"]}/20 sessions · {ft["governance"]}<br>{_fmt(ft["baseline"]["expectancy"],"money")} → {_fmt(ft["first_two_shadow"]["expectancy"],"money")} expectancy · PF {_fmt(ft["baseline"]["profit_factor"])} → {_fmt(ft["first_two_shadow"]["profit_factor"])}'
    edge_html=metrics((("Closed",edge["closed_trades"]),("Expectancy",_fmt(edge["expectancy"],"money")),("PF",_fmt(edge["profit_factor"])),("Win rate",_fmt(edge["win_rate"],"percent")),("Avg win",_fmt(edge["average_winner"],"money")),("Avg loss",_fmt(edge["average_loser"],"money")),("Payoff",_fmt(edge["payoff_ratio"])),("Profitable sessions",_fmt(edge["profitable_session_percentage"],"percent"))),"ob-qqq-edge")
    session_label="SESSION PULSE · SESSION ACTIVE" if model["market_open"] else "SESSION PULSE · SESSION COMPLETE"
    return f'''<style>.ob-qqq-wide{{background:#101722;border:1px solid #273344;border-radius:14px;color:#e8edf3;padding:14px}}.ob-qqq-wide-head{{align-items:center;display:flex;justify-content:space-between;gap:12px}}.ob-qqq-wide-head h3{{font-size:1.08rem;margin:0}}.ob-qqq-status{{border:1px solid #3b526b;border-radius:999px;font-size:.7rem;font-weight:800;padding:4px 9px}}.ob-qqq-wide-layout{{display:grid;gap:14px;grid-template-columns:minmax(180px,.8fr) minmax(260px,1.1fr) minmax(420px,2fr);margin-top:11px}}.ob-qqq-zone{{border-left:1px solid #273344;min-width:0;padding-left:12px}}.ob-qqq-zone:first-child{{border-left:0;padding-left:0}}.ob-qqq-zone h4{{color:#91a0af;font-size:.67rem;letter-spacing:.08em;margin:0 0 6px}}.ob-qqq-wide-metrics,.ob-qqq-pulse,.ob-qqq-edge{{display:grid;gap:6px;grid-template-columns:repeat(2,minmax(0,1fr))}}.ob-qqq-pulse{{grid-template-columns:repeat(4,minmax(0,1fr))}}.ob-qqq-edge{{grid-template-columns:repeat(4,minmax(0,1fr));margin-top:5px}}.ob-qqq-wide-metrics div,.ob-qqq-pulse div,.ob-qqq-edge div{{min-width:0}}.ob-qqq-wide-metrics span,.ob-qqq-pulse span,.ob-qqq-edge span{{color:#8492a1;display:block;font-size:.58rem;text-transform:uppercase}}.ob-qqq-wide-metrics strong,.ob-qqq-pulse strong,.ob-qqq-edge strong{{font-size:.76rem;overflow-wrap:anywhere}}.ob-qqq-chips{{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px}}.ob-qqq-chip{{background:#1b2735;border-radius:999px;font-size:.65rem;padding:3px 7px}}.ob-qqq-quality{{margin-top:8px;font-size:.72rem}}.ob-qqq-right-section+ .ob-qqq-right-section{{border-top:1px solid #273344;margin-top:8px;padding-top:7px}}.ob-qqq-right-section p{{font-size:.7rem;margin:3px 0}}.ob-qqq-dna{{border-top:1px solid #273344;margin-top:10px;padding-top:8px}}.ob-qqq-dna summary{{cursor:pointer;font-size:.72rem;font-weight:800}}.ob-qqq-muted{{color:#8492a1;font-size:.66rem}}@media(max-width:1000px){{.ob-qqq-wide-layout{{grid-template-columns:repeat(2,minmax(0,1fr))}}.ob-qqq-zone-right{{grid-column:1/-1}}}}@media(max-width:700px){{.ob-qqq-wide-layout{{grid-template-columns:minmax(0,1fr)}}.ob-qqq-zone,.ob-qqq-zone:first-child{{border-left:0;border-top:1px solid #273344;padding:9px 0 0}}.ob-qqq-zone:first-child{{border-top:0;padding-top:0}}.ob-qqq-zone-right{{grid-column:auto}}.ob-qqq-pulse,.ob-qqq-edge{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}</style><section class="ob-qqq-wide"><div class="ob-qqq-wide-head"><div><h3>QQQ COMMAND CARD</h3><span class="ob-qqq-muted">{escape(_fmt(model["updated_at"]))}</span></div><span class="ob-qqq-status">{escape(model["status"])}</span></div><div class="ob-qqq-wide-layout"><div class="ob-qqq-zone ob-qqq-zone-left"><h4>QQQ NOW</h4>{left}</div><div class="ob-qqq-zone ob-qqq-zone-center"><h4>SETUP / CONTRACT</h4>{center}<div class="ob-qqq-quality">CONTEXT QUALITY · <strong>{escape(quality["label"])}{f' · {quality["score"]}/100' if quality["score"] is not None else ''}</strong></div><div class="ob-qqq-chips">{chips}</div></div><div class="ob-qqq-zone ob-qqq-zone-right"><div class="ob-qqq-right-section"><h4>{session_label}</h4>{pulse_html}</div><div class="ob-qqq-right-section"><h4>FIRST_TWO FORWARD TEST</h4><p>{first_two}</p></div><div class="ob-qqq-right-section"><h4>QQQ EDGE SNAPSHOT</h4>{edge_html}<span class="ob-qqq-muted">Historical / forward research metrics only</span></div><div class="ob-qqq-right-section"><h4>MARK COVERAGE</h4><p>{coverage["positions_with_1_or_more_marks"]} marked · {_fmt(coverage["average_marks_per_trade"])} avg/trade · {len(coverage["missing_mark_trades"])} missing</p></div></div></div><div class="ob-qqq-dna"><details><summary>QQQ DNA</summary><p class="ob-qqq-muted">CALL/PUT, DTE, sequence, MIRROR/MANAGED, MFE/MAE, session and mark attribution remain descriptive research only. Complete detail remains in Developer Tools.</p></details></div></section>'''
