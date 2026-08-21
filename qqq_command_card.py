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
            option_type,expiration,dte,strike,quantity,underlying_entry_price,entry_bid,entry_ask,entry_fill,spread_percent,
            status,management_state,opened_at,closed_at,current_mark,current_value,unrealized_pnl,peak_return_pct,
            exit_fill,exit_reason,realized_pnl,realized_return_percent,mfe_pct,mae_pct,last_quote_at,update_status,updated_at
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


def _parse_timestamp(value):
    if not value: return None
    try:
        parsed=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except (TypeError,ValueError): return None


def _trade_session(row):
    parsed=_parse_timestamp(_value(row,"opened_at"))
    return parsed.astimezone(EASTERN).date().isoformat() if parsed else None


def format_trade_timestamp(value):
    parsed=_parse_timestamp(value)
    return "—" if parsed is None else f'{parsed.astimezone(EASTERN).strftime("%I:%M:%S %p").lstrip("0")} ET'


def _duration(opened_at,closed_at):
    opened=_parse_timestamp(opened_at);closed=_parse_timestamp(closed_at)
    if not opened or not closed: return None
    seconds=max(0,int((closed-opened).total_seconds()))
    minutes,remainder=divmod(seconds,60)
    return f"{minutes}m {remainder}s" if minutes else f"{remainder}s"


def _direction_kind(value):
    value=str(value or "").upper()
    if value in {"BULLISH","CALL","C"}: return "CALL"
    if value in {"BEARISH","PUT","P"}: return "PUT"
    return None


def _contract_kind(row):
    explicit=_direction_kind(_value(row,"option_type"))
    if explicit: return explicit
    match=re.fullmatch(r"[A-Z]+\d{6}([CP])\d{8}",str(_value(row,"option_symbol") or "").upper())
    return _direction_kind(match.group(1)) if match else None


def _expiration_date(row):
    value=_value(row,"expiration")
    if value:
        try: return datetime.fromisoformat(str(value)).date()
        except (TypeError,ValueError): pass
    match=re.fullmatch(r"[A-Z]+(\d{6})[CP]\d{8}",str(_value(row,"option_symbol") or "").upper())
    if match:
        try: return datetime.strptime(match.group(1),"%y%m%d").date()
        except ValueError: return None
    return None


def _contract_consistency(row, *, direction, opportunity_id, today, require_identity=False):
    expiration=_expiration_date(row); expected=_direction_kind(direction); actual=_contract_kind(row)
    if expiration is None or expiration < today: return False,"EXPIRED" if expiration and expiration<today else "EXPIRATION UNAVAILABLE"
    if expected and actual != expected: return False,"DIRECTION / OPTION TYPE MISMATCH"
    row_identity=_value(row,"opportunity_id")
    if require_identity and opportunity_id and str(row_identity or "")!=str(opportunity_id): return False,"OPPORTUNITY IDENTITY MISMATCH"
    return True,None


def current_qqq_contract(trades, signal, plan, *, now):
    """Select only a current-session, identity-consistent contract for the setup panel."""
    today=now.astimezone(EASTERN).date(); opportunity_id=signal.get("opportunity_id") or plan.get("opportunity_id")
    direction=plan.get("direction") or signal.get("direction")
    current=[row for row in trades if str(_value(row,"variant") or "").upper()=="INTRADAY_MANAGED"
        and _trade_session(row)==today.isoformat() and str(_value(row,"status") or "").upper()=="OPEN"]
    if current:
        exact=[row for row in current if not opportunity_id or str(_value(row,"opportunity_id") or "")==str(opportunity_id)]
        row=(exact or current)[0]
        valid,reason=_contract_consistency(row,direction=direction or _value(row,"direction"),opportunity_id=opportunity_id,
            today=today,require_identity=bool(opportunity_id))
        return (row if valid else None),("CURRENT CONTRACT" if valid else "CONTRACT DATA MISMATCH"),reason
    selected_contract=plan.get("option_symbol") or plan.get("contract")
    if selected_contract:
        selected=dict(plan);selected["option_symbol"]=selected_contract
        selected.setdefault("option_type",plan.get("option_type"));selected.setdefault("opportunity_id",plan.get("opportunity_id"))
        selected_at=_parse_timestamp(plan.get("selected_at"))
        current_selection=bool(selected_at and selected_at.astimezone(EASTERN).date()==today)
        valid,reason=_contract_consistency(selected,direction=direction,opportunity_id=opportunity_id,today=today,
            require_identity=bool(opportunity_id))
        if current_selection and valid: return selected,"CURRENT CONTRACT",None
        return None,"CONTRACT DATA MISMATCH" if reason and reason!="EXPIRED" else "AWAITING CONTRACT SELECTION",reason
    return None,"AWAITING CONTRACT SELECTION",None


def build_qqq_trade_coverage(trades, signal, plan, *, now, stale=False):
    """Build a presentation-only lifecycle from authoritative, already-loaded state."""
    today=now.astimezone(EASTERN).date().isoformat()
    managed=[row for row in trades if str(_value(row,"variant") or "").upper()=="INTRADAY_MANAGED"]
    session_rows=[row for row in managed if _trade_session(row)==today]
    open_rows=[row for row in session_rows if str(_value(row,"status") or "").upper()=="OPEN"]
    closed_rows=[row for row in session_rows if str(_value(row,"status") or "").upper()=="CLOSED"]
    row=(open_rows or closed_rows or [None])[0]
    selected_contract=plan.get("option_symbol") or plan.get("contract")
    if row:
        closed=str(_value(row,"status") or "").upper()=="CLOSED"
        management=str(_value(row,"management_state") or "").upper()
        state="CLOSED" if closed else "MANAGING" if management not in {"","OPEN","ENTERED"} else "ENTERED"
        valid,mismatch_reason=_contract_consistency(row,direction=_value(row,"direction"),
            opportunity_id=signal.get("opportunity_id"),today=now.astimezone(EASTERN).date(),
            require_identity=bool(not closed and signal.get("opportunity_id")))
        if not valid: state="CONTRACT DATA MISMATCH"
        stamp=_value(row,"closed_at") if closed else (_value(row,"last_quote_at") or _value(row,"updated_at") or _value(row,"opened_at"))
        bid=_number(_value(row,"entry_bid"));ask=_number(_value(row,"entry_ask"))
        midpoint=(bid+ask)/2 if bid is not None and ask is not None else None
        coverage={key:_value(row,key) for key in (
            "trade_id","opportunity_id","variant","direction","option_symbol","option_type","expiration","dte","strike",
            "quantity","underlying_entry_price","entry_bid","entry_ask","entry_fill","spread_percent","opened_at","closed_at",
            "current_mark","current_value","unrealized_pnl","peak_return_pct","exit_fill","exit_reason","realized_pnl",
            "realized_return_percent","mfe_pct","mae_pct","management_state","last_quote_at","update_status")}
        parsed_stamp=_parse_timestamp(stamp)
        row_stale=bool(parsed_stamp and (now.astimezone(timezone.utc)-parsed_stamp.astimezone(timezone.utc)).total_seconds()>300)
        coverage.update(state=state,updated_at=stamp,midpoint=midpoint,trigger=signal.get("trigger_price") or plan.get("trigger_price"),
            stale=bool(row_stale and not closed),duration=_duration(_value(row,"opened_at"),_value(row,"closed_at")),
            mismatch_reason=mismatch_reason,display_dte=((_expiration_date(row)-now.astimezone(EASTERN).date()).days if _expiration_date(row) else None),
            contract_label=format_contract_label(_value(row,"option_symbol"),strike=_value(row,"strike"),expiration=_value(row,"expiration"),bias=_value(row,"direction")))
        coverage["copy_line"]=None if not valid else (f'{format_trade_timestamp(_value(row,"opened_at"))} | {_value(row,"direction") or "—"} | '
            f'{coverage["contract_label"]} | OCC {_value(row,"option_symbol") or "—"} | DTE {_value(row,"dte") if _value(row,"dte") is not None else "—"} | '
            f'Fill {_fmt(_value(row,"entry_fill"),"price")} | QQQ {_fmt(_value(row,"underlying_entry_price"),"price")} | {_value(row,"variant")}')
        return coverage
    signal_state=str(signal.get("state") or "").upper()
    mismatch_reason=None
    if selected_contract:
        selected=dict(plan);selected["option_symbol"]=selected_contract
        selected_stamp=_parse_timestamp(plan.get("selected_at"))
        current_selected=bool(selected_stamp and selected_stamp.astimezone(EASTERN).date()==now.astimezone(EASTERN).date())
        valid,mismatch_reason=_contract_consistency(selected,direction=plan.get("direction") or signal.get("direction"),
            opportunity_id=signal.get("opportunity_id"),today=now.astimezone(EASTERN).date(),require_identity=bool(signal.get("opportunity_id")))
        state="CONTRACT SELECTED" if current_selected and valid else "CONTRACT DATA MISMATCH" if mismatch_reason else "AWAITING CONTRACT SELECTION"
    else: state="ENTRY TRIGGERED" if signal_state=="TRIGGERED" else "WATCHING" if signal_state in {"ARMED","SETUP_DETECTED"} else "NO TRADE"
    return {"state":state,"stale":bool(stale and state!="NO TRADE"),"updated_at":signal.get("updated_at"),
        "mismatch_reason":mismatch_reason,
        "opportunity_id":signal.get("opportunity_id"),"direction":plan.get("direction") or signal.get("direction"),
        "option_symbol":selected_contract,"contract_label":format_contract_label(selected_contract,strike=plan.get("strike"),expiration=plan.get("expiration"),bias=plan.get("direction") or signal.get("direction")),
        "selected_at":plan.get("selected_at"),"strike":plan.get("strike"),"expiration":plan.get("expiration"),"dte":plan.get("dte"),"entry_bid":plan.get("bid"),
        "entry_ask":plan.get("ask"),"midpoint":plan.get("midpoint"),"spread_percent":plan.get("spread_percent"),
        "underlying_entry_price":signal.get("underlying_price"),"trigger":plan.get("trigger_price") or signal.get("trigger_price"),
        "copy_line":None}


def build_qqq_command_card_model(latest_qqq, data, *, now, market_open, stale=False, active_setup=False):
    now_et=now.astimezone(EASTERN); trades=list(data.get("trades") or []); signals=list(data.get("signals") or [])
    signal=signals[0] if signals else {}; live=latest_qqq or {}; plan=live.get("trade_plan") or {}; today=now_et.date().isoformat()
    today_rows=[row for row in trades if _trade_session(row)==today]
    completed=[row for row in trades if _trade_session(row)!=today]
    pulse=_performance(today_rows); edge=_performance(completed)
    managed=[row for row in trades if str(row.get("variant") or "").upper()=="INTRADAY_MANAGED"]
    latest_trade=(managed or trades or [{}])[0]; stamp=signal.get("updated_at") or live.get("timestamp") or latest_trade.get("updated_at")
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
    setup_contract,contract_status,contract_issue=current_qqq_contract(trades,signal,plan,now=now)
    spread=_number(_value(setup_contract,"spread_percent")); sequence=max((int(r.get("session_trade_number") or 0) for r in data.get("shadow") or [] if r.get("eastern_session")==today),default=0)
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
    trade_coverage=build_qqq_trade_coverage(trades,signal,plan,now=now,stale=stale)
    return {"status":status,"price":live.get("price") or signal.get("underlying_price"),"bias":direction,
        "regime":signal.get("regime") or live.get("regime"),"setup":plan.get("setup_type") or plan.get("setup") or signal.get("setup"),
        "tradeability":signal.get("state"),"trigger":plan.get("trigger_price") or signal.get("trigger_price"),
        "contract":_value(setup_contract,"option_symbol"),"strike":_value(setup_contract,"strike"),"expiration":_value(setup_contract,"expiration"),
        "dte":((_expiration_date(setup_contract)-now_et.date()).days if setup_contract and _expiration_date(setup_contract) else None),
        "bid":_value(setup_contract,"entry_bid",_value(setup_contract,"bid")),"ask":_value(setup_contract,"entry_ask",_value(setup_contract,"ask")),
        "midpoint":((_number(_value(setup_contract,"entry_bid",_value(setup_contract,"bid")))+_number(_value(setup_contract,"entry_ask",_value(setup_contract,"ask"))))/2 if _number(_value(setup_contract,"entry_bid",_value(setup_contract,"bid"))) is not None and _number(_value(setup_contract,"entry_ask",_value(setup_contract,"ask"))) is not None else None),
        "spread":spread,"updated_at":stamp,"chips":chips,"context_quality":context_quality(evidence,stale=stale),
        "session_pulse":pulse,"session_trade_number":sequence,"first_two":first_two,"edge_snapshot":edge,
        "mark_coverage":mark_coverage(data.get("shadow") or [],data.get("marks") or []),"dna_summary":dna,"market_open":market_open,
        "trade_coverage":trade_coverage,"contract_status":contract_status,"contract_issue":contract_issue}


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


QQQ_COMMAND_CARD_VIEWS=("LIVE / SESSION","EDGE","RESEARCH")
QQQ_COMMAND_CARD_VIEW_KEY="qqq_command_card_view"


def _display_expiration(value):
    if not value: return "—"
    try:
        parsed=datetime.fromisoformat(str(value))
        return f'{parsed.strftime("%b")} {parsed.day}'
    except (TypeError,ValueError): return str(value)


def _trade_coverage_markup(coverage):
    state=coverage.get("state") or "NO TRADE"; badge="DATA STALE" if coverage.get("stale") else state
    direction=_direction_kind(coverage.get("direction"));tone="positive" if direction=="CALL" else "negative" if direction=="PUT" else "neutral"
    def item(label,value): return f'<div class="ob-cover-item"><span>{escape(label)}</span><strong>{escape(str(value))}</strong></div>'
    if state in {"WATCHING","ENTRY TRIGGERED","NO TRADE","AWAITING CONTRACT SELECTION"}:
        details=(("Direction",_fmt(coverage.get("direction"))),("QQQ",_fmt(coverage.get("underlying_entry_price"),"price")),("Entry trigger",_fmt(coverage.get("trigger"),"price")),("Updated",format_trade_timestamp(coverage.get("updated_at"))))
        note="Trigger observed; no managed entry is persisted." if state=="ENTRY TRIGGERED" else "No managed entry is persisted for this session."
    elif state=="CONTRACT DATA MISMATCH":
        details=(("Status","NOT ACTIONABLE"),("Reason",_fmt(coverage.get("mismatch_reason"))),("Opportunity",_fmt(coverage.get("opportunity_id"))),("Updated",format_trade_timestamp(coverage.get("updated_at"))))
        note="Replication is unavailable until authoritative contract identity is consistent."
    elif state=="CONTRACT SELECTED":
        details=(("Contract",coverage.get("contract_label")),("Raw OCC",_fmt(coverage.get("option_symbol"))),("Selected",format_trade_timestamp(coverage.get("selected_at"))),("Bid / Ask",f'{_fmt(coverage.get("entry_bid"),"price")} / {_fmt(coverage.get("entry_ask"),"price")}'),("Mid / Spread",f'{_fmt(coverage.get("midpoint"),"price")} / {_fmt(coverage.get("spread_percent"),"percent")}'),("QQQ / Trigger",f'{_fmt(coverage.get("underlying_entry_price"),"price")} / {_fmt(coverage.get("trigger"),"price")}'),("Status","WAITING FOR ENTRY"))
        note="Contract selection is not an entry."
    else:
        details=(("Entry",format_trade_timestamp(coverage.get("opened_at"))),("Contract",coverage.get("contract_label")),("Raw OCC",_fmt(coverage.get("option_symbol"))),("DTE / Qty",f'{_fmt(coverage.get("dte"))} / {_fmt(coverage.get("quantity"))}'),("Fill",_fmt(coverage.get("entry_fill"),"price")),("Bid / Ask",f'{_fmt(coverage.get("entry_bid"),"price")} / {_fmt(coverage.get("entry_ask"),"price")}'),("Mid / Spread",f'{_fmt(coverage.get("midpoint"),"price")} / {_fmt(coverage.get("spread_percent"),"percent")}'),("QQQ / Trigger",f'{_fmt(coverage.get("underlying_entry_price"),"price")} / {_fmt(coverage.get("trigger"),"price")}'),("Variant",_fmt(coverage.get("variant"))))
        if state=="MANAGING": details+=(('Current mark',_fmt(coverage.get("current_mark"),"price")),('Unrealized',_fmt(coverage.get("unrealized_pnl"),"money")),('MFE / MAE',f'{_fmt(coverage.get("mfe_pct"),"percent")} / {_fmt(coverage.get("mae_pct"),"percent")}'),('Management',_fmt(coverage.get("management_state"))))
        if state=="CLOSED": details+=(('Exit',format_trade_timestamp(coverage.get("closed_at"))),('Exit fill',_fmt(coverage.get("exit_fill"),"price")),('Return / P&L',f'{_fmt(coverage.get("realized_return_percent"),"percent")} / {_fmt(coverage.get("realized_pnl"),"money")}'),('Exit reason',_fmt(coverage.get("exit_reason"))),('Duration',_fmt(coverage.get("duration"))),('MFE / MAE',f'{_fmt(coverage.get("mfe_pct"),"percent")} / {_fmt(coverage.get("mae_pct"),"percent")}'))
        note="Canonical manual lane: INTRADAY_MANAGED."
    copy=f'<div class="ob-qnative-copy">{escape(coverage["copy_line"])}</div>' if coverage.get("copy_line") else ""
    style='''<style>.ob-qnative-coverage{background:radial-gradient(circle at 85% 40%,rgba(40,217,120,.09),transparent 22rem),linear-gradient(135deg,#0b1a29,#07131f);border:1px solid #2b435b;border-radius:12px;margin-bottom:12px;padding:15px 17px;position:relative}.ob-qnative-coverage:after{background:linear-gradient(90deg,transparent,#28d978,transparent);bottom:-1px;content:"";height:2px;left:30%;position:absolute;width:50%}.ob-qnative-coverage-head{align-items:center;display:flex;justify-content:space-between}.ob-qnative-coverage-head h4{color:#dbe5ef;font-size:.72rem;letter-spacing:.07em;margin:0}.ob-qnative-coverage-grid{display:grid;gap:12px 24px;grid-template-columns:repeat(4,minmax(0,1fr));margin:14px 0 10px}.ob-cover-item{border-right:1px solid #1d3348}.ob-cover-item:last-child{border:0}.ob-qnative-coverage-grid span{color:#8395a7;display:block;font-size:.58rem;text-transform:uppercase}.ob-qnative-coverage-grid strong{font-size:1.15rem;overflow-wrap:anywhere}.ob-cover-positive .ob-cover-item:first-child strong{color:#28d978}.ob-cover-negative .ob-cover-item:first-child strong{color:#f05b68}.ob-qnative-copy{background:#050d16;border:1px solid #1b3044;border-radius:6px;font-family:monospace;font-size:.67rem;margin:9px 0;padding:8px;user-select:all}@media(max-width:650px){.ob-qnative-coverage-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.ob-cover-item{border:0}}</style>'''
    return style+f'<div class="ob-qnative-coverage ob-cover-{tone}"><div class="ob-qnative-coverage-head"><h4>QQQ TRADE COVERAGE</h4><span class="ob-qnative-status">● {escape(badge)}</span></div><div class="ob-qnative-coverage-grid">{"".join(item(*entry) for entry in details)}</div>{copy}<span class="ob-qnative-muted">{escape(note)}</span></div>'


def qqq_command_card_markup(model, *, view="LIVE / SESSION"):
    """Render exactly one server-selected pane; navigation is owned by Streamlit."""
    if view not in QQQ_COMMAND_CARD_VIEWS: view="LIVE / SESSION"
    pulse=model["session_pulse"];edge=model["edge_snapshot"];ft=model.get("first_two");quality=model["context_quality"];coverage=model["mark_coverage"]
    def metric(label,value):
        return f'<div class="ob-qnative-metric"><span>{escape(label)}</span><strong>{escape(str(value))}</strong></div>'
    contract=(format_contract_label(model.get("contract"),strike=model.get("strike"),expiration=model.get("expiration"),bias=model.get("bias"))
        if model.get("contract") else model.get("contract_status") or "NO CURRENT CONTRACT")
    setup_items=(("Strike",_fmt(model["strike"],"price")),("DTE",_fmt(model["dte"])),("Spread",_fmt(model["spread"],"percent")),("Expiration",_display_expiration(model["expiration"])))
    if model["market_open"] and (model.get("session_trade_number") or 0)>0:
        setup_items+=(('Trade State',f'Trade #{model["session_trade_number"]}'),)
    empty_hint=('' if model.get("contract") else '<div class="ob-qnative-empty-hint">◇ <span>Contract selection begins when entry conditions align.</span></div>')
    setup=f'<strong class="ob-qnative-contract">{escape(contract)}</strong><div class="ob-qnative-setup-lead"><strong>{escape(model["bias"])} BIAS</strong><span>Trigger {escape(_fmt(model["trigger"],"price"))}</span></div><div class="ob-qnative-setup-metrics">'+"".join(metric(*item) for item in setup_items)+f"</div>{empty_hint}"
    primary="".join(metric(*item) for item in (("Trades",pulse["closed_trades"]),("W/L",f'{pulse["wins"]} / {pulse["losses"]}'),("Win Rate",_fmt(pulse["win_rate"],"percent"))))
    supporting="".join(metric(*item) for item in (("Average",_fmt(pulse["average_trade"],"money")),("Best",_fmt(pulse["best_trade"],"money")),("Worst",_fmt(pulse["worst_trade"],"money"))))
    session=f'<div class="ob-qnative-pnl"><span>TODAY</span><strong>{escape(_fmt(pulse["total_pnl"],"money"))}</strong></div><div class="ob-qnative-session-row">{primary}</div><div class="ob-qnative-session-row is-supporting">{supporting}</div>'
    chips="".join(f'<span class="ob-qnative-chip">{escape(chip)}</span>' for chip in model["chips"] if chip and "TRADE #0" not in chip) or '<span class="ob-qnative-muted">Known factors unavailable</span>'
    if ft:
        shadow=ft["first_two_shadow"]
        first_two=f'<span class="ob-qnative-chip">{escape(ft["governance"])}</span><strong>{shadow["accepted_trades"]}/50 accepted</strong><span>{shadow["sessions"]}/20 sessions</span><span>Expectancy {_fmt(ft["baseline"]["expectancy"],"money")} → {_fmt(shadow["expectancy"],"money")}</span><span>PF {_ratio(ft["baseline"]["profit_factor"])} → {_ratio(shadow["profit_factor"])}</span>'
    else:first_two='<span class="ob-qnative-chip is-muted">AWAITING SAMPLE</span>'
    coverage_label="LIMITED" if quality["score"] is None or not model["chips"] else quality["label"]
    visual_style='''<style>.ob-qnative-live-grid{gap:12px}.ob-qnative-panel{background:linear-gradient(145deg,#0b1a29,#081522)!important;border-color:#263c52!important;border-radius:12px!important;padding:14px!important}.ob-qnative-contract{font-size:1.08rem!important}.ob-qnative-empty-hint{align-items:center;background:rgba(139,92,246,.09);border:1px solid rgba(139,92,246,.22);border-radius:8px;color:#a879ff;display:flex;font-size:.75rem;gap:8px;margin-top:12px;padding:10px}.ob-qnative-support{gap:12px;grid-template-columns:repeat(3,minmax(0,1fr))!important;margin-top:12px}.ob-qnative-strip{align-items:flex-start!important;border:1px solid #263c52!important;border-radius:12px!important;display:flex!important;flex-direction:column!important;padding:12px!important}.ob-qnative-strip strong{color:#f3a61d;font-size:1rem}.ob-qnative-confidence{background:#172536;border-radius:99px;height:5px;overflow:hidden;width:100%}.ob-qnative-confidence i{background:linear-gradient(90deg,#f3a61d,#8b5cf6);display:block;height:100%}.ob-qnative-strip small{color:#7f91a5;font-size:.58rem}.ob-qnative-strip.is-regime strong{border:1px solid #f3a61d;border-radius:99px;padding:5px 10px}@media(max-width:850px){.ob-qnative-support{grid-template-columns:1fr!important}}</style>'''
    shell_style='''<style>.ob-qnative{background:linear-gradient(145deg,#07131f,#091827)!important;border-color:#263c52!important;box-shadow:0 16px 42px rgba(0,0,0,.22);padding:15px 16px!important}.ob-qnative-symbol{font-size:1.35rem!important}.ob-qnative-price{font-size:2rem!important}.ob-qnative-bias{background:rgba(139,92,246,.14);border:1px solid #7548d8;border-radius:7px;color:#a879ff;padding:5px 8px}.ob-qnative-status{border-color:#7548d8!important;color:#a879ff}</style>'''
    trade_coverage=shell_style+visual_style+_trade_coverage_markup(model.get("trade_coverage") or {"state":"NO TRADE"})
    quality_score=quality.get("score") or 0
    live=f'''{trade_coverage}<div class="ob-qnative-live-grid"><div class="ob-qnative-panel"><h4>{'CURRENT QQQ SETUP' if model['market_open'] else 'LAST SESSION SETUP'}</h4>{setup}</div><div class="ob-qnative-panel"><h4>● {'SESSION ACTIVE' if model['market_open'] else 'SESSION COMPLETE'}</h4>{session}</div><div class="ob-qnative-support"><div class="ob-qnative-strip is-context"><h4>CONTEXT COVERAGE</h4><strong>{escape(coverage_label)}</strong><div class="ob-qnative-confidence"><i style="width:{quality_score}%"></i></div><div class="ob-qnative-chips"><span class="ob-qnative-muted">Known factors:</span>{chips}</div><small>More data = higher confidence</small></div><div class="ob-qnative-strip"><h4>FIRST TWO CONFIRMATIONS</h4><div class="ob-qnative-first">{first_two}</div></div><div class="ob-qnative-strip is-regime"><h4>MARKET CONDITION</h4><strong>{escape(_fmt(model.get('regime')))}</strong><span class="ob-qnative-muted">Current persisted regime</span></div></div></div>'''
    edge_markup="".join(metric(*item) for item in (("Closed Trades",edge["closed_trades"]),("Expectancy",_fmt(edge["expectancy"],"money")),("Profit Factor",_ratio(edge["profit_factor"])),("Win Rate",_fmt(edge["win_rate"],"percent")),("Avg Winner",_fmt(edge["average_winner"],"money")),("Avg Loser",_fmt(edge["average_loser"],"money")),("Payoff",_ratio(edge["payoff_ratio"],"x")),("Profitable Sessions",_fmt(edge["profitable_session_percentage"],"percent"))))
    edge_view=f'<span class="ob-qnative-muted">Historical / forward research metrics only</span><div class="ob-qnative-edge">{edge_markup}</div>'
    marks=(f'<strong>{coverage["positions_with_1_or_more_marks"]} marked</strong><span>{_ratio(coverage["average_marks_per_trade"])} avg/trade · {len(coverage["missing_mark_trades"])} missing</span>' if coverage.get("positions_with_1_or_more_marks") else '<span class="ob-qnative-chip is-muted">AWAITING OBSERVATIONS</span>')
    research=f'<div class="ob-qnative-research"><div><h4>CONTEXT COVERAGE</h4><span class="ob-qnative-chip">{escape(coverage_label)}</span><p>Known evidence remains descriptive; unavailable evidence is not negative evidence.</p></div><div><h4>FIRST_TWO GOVERNANCE</h4>{first_two}<p>Sequence and overtrading research remains predeclared.</p></div><div><h4>MARK TELEMETRY</h4>{marks}</div><details class="ob-qnative-dna"><summary>QQQ DNA</summary><p>CALL/PUT, 0DTE/1DTE, time, sequence, re-entry, spread, setup, regime, MFE/MAE and FIRST_TWO attribution remain descriptive research only.</p></details></div>'
    body={"LIVE / SESSION":live,"EDGE":edge_view,"RESEARCH":research}[view]
    return f'''<style>.ob-qnative{{background:#101722;border:1px solid #273344;border-radius:14px;color:#e8edf3;padding:11px 13px}}.ob-qnative-head{{align-items:center;display:flex;gap:10px;justify-content:space-between}}.ob-qnative-id{{align-items:baseline;display:flex;flex-wrap:wrap;gap:5px 11px}}.ob-qnative-symbol{{font-size:1rem;font-weight:850}}.ob-qnative-price{{font-size:1.38rem;font-weight:850}}.ob-qnative-bias{{font-size:.76rem;font-weight:800}}.ob-qnative-context{{color:#a8b3bf;font-size:.7rem}}.ob-qnative-status,.ob-qnative-chip{{background:#1b2735;border-radius:999px;font-size:.6rem;font-weight:750;padding:3px 7px}}.ob-qnative-status{{border:1px solid #3b526b;white-space:nowrap}}.ob-qnative-time,.ob-qnative-muted{{color:#82909f;font-size:.59rem}}.ob-qnative-body{{padding-top:8px}}.ob-qnative-live-grid{{display:grid;gap:9px;grid-template-columns:minmax(0,2fr) minmax(0,3fr)}}.ob-qnative-panel{{background:#151f2b;border:1px solid #263443;border-radius:9px;padding:9px 10px}}.ob-qnative-panel h4,.ob-qnative-strip h4,.ob-qnative-research h4{{color:#8e9baa;font-size:.59rem;letter-spacing:.07em;margin:0 0 7px}}.ob-qnative-contract{{display:block;font-size:1rem;margin-bottom:3px}}.ob-qnative-setup-lead{{align-items:baseline;display:flex;gap:12px;margin-bottom:10px}}.ob-qnative-setup-lead strong{{font-size:.7rem}}.ob-qnative-setup-lead span{{color:#a8b3bf;font-size:.67rem}}.ob-qnative-setup-metrics,.ob-qnative-session-row{{display:grid;gap:10px;grid-template-columns:repeat(2,minmax(0,1fr))}}.ob-qnative-session-row{{grid-template-columns:repeat(3,minmax(0,1fr))}}.ob-qnative-session-row.is-supporting{{border-top:1px solid #263443;margin-top:8px;padding-top:7px}}.ob-qnative-metric span,.ob-qnative-pnl span{{color:#82909f;display:block;font-size:.53rem;text-transform:uppercase}}.ob-qnative-metric strong{{font-size:.72rem}}.ob-qnative-pnl strong{{display:block;font-size:1.35rem;margin:1px 0 8px}}.ob-qnative-support{{display:grid;grid-column:1/-1;grid-template-columns:1fr 1fr}}.ob-qnative-strip{{align-items:center;background:#131c27;display:flex;gap:10px;padding:7px 9px}}.ob-qnative-strip:first-child{{border-radius:8px 0 0 8px}}.ob-qnative-strip:last-child{{border-left:1px solid #263443;border-radius:0 8px 8px 0}}.ob-qnative-chips,.ob-qnative-first{{align-items:center;display:flex;flex-wrap:wrap;gap:5px 10px}}.ob-qnative-first span,.ob-qnative-first strong{{font-size:.63rem}}.ob-qnative-edge{{display:grid;gap:9px;grid-template-columns:repeat(4,minmax(0,1fr));margin-top:7px}}.ob-qnative-edge .ob-qnative-metric{{border-bottom:1px solid #263443;padding:5px 2px}}.ob-qnative-research{{display:grid;gap:12px;grid-template-columns:repeat(3,minmax(0,1fr))}}.ob-qnative-research>div{{font-size:.65rem}}.ob-qnative-research p,.ob-qnative-dna p{{color:#82909f;font-size:.61rem}}.ob-qnative-dna{{border-top:1px solid #263443;grid-column:1/-1;padding-top:7px}}@media(max-width:850px){{.ob-qnative-live-grid,.ob-qnative-research{{grid-template-columns:minmax(0,1fr)}}.ob-qnative-edge{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}@media(max-width:560px){{.ob-qnative-head{{align-items:flex-start;flex-direction:column}}.ob-qnative-setup-metrics,.ob-qnative-session-row,.ob-qnative-edge,.ob-qnative-support{{grid-template-columns:minmax(0,1fr)}}.ob-qnative-strip,.ob-qnative-strip:first-child,.ob-qnative-strip:last-child{{border:0;border-radius:8px;margin-bottom:5px}}}}</style><section class="ob-qnative"><div class="ob-qnative-head"><div><div class="ob-qnative-id"><span class="ob-qnative-symbol">QQQ</span><strong class="ob-qnative-price">{escape(_fmt(model["price"],"price"))}</strong><span class="ob-qnative-bias">{escape(model["bias"])} BIAS</span><span class="ob-qnative-context">{escape(_fmt(model["regime"]))} · {escape(_fmt(model["setup"]))}</span></div><span class="ob-qnative-time">{escape(format_card_timestamp(model.get("updated_at")))}</span></div><span class="ob-qnative-status">{escape(model["status"])}</span></div><div class="ob-qnative-body" data-view="{escape(view)}">{body}</div></section>'''


def render_qqq_command_card(st_module, model):
    """Render native navigation and one presentation-only pane."""
    st_module.markdown('''<style>[data-testid="stSegmentedControl"]{max-width:24rem}[data-testid="stSegmentedControl"] button{font-size:.72rem;font-weight:750}</style>''',unsafe_allow_html=True)
    selected=st_module.segmented_control(
        "QQQ command view",QQQ_COMMAND_CARD_VIEWS,default="LIVE / SESSION",
        key=QQQ_COMMAND_CARD_VIEW_KEY,label_visibility="collapsed",
    ) or "LIVE / SESSION"
    markup=qqq_command_card_markup(model,view=selected)
    st_module.markdown(markup,unsafe_allow_html=True)
    return selected


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
