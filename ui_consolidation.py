"""Read-only presentation models for the consolidated OptionBeacon workspace."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone

import pandas as pd


PRIMARY_NAVIGATION=("Command Center","Performance","SPY / QQQ","Research / Developer Tools")
LEGACY_ROUTE_ALIASES={"Trade Desk":"Command Center","Opportunities":"Command Center","Paper Trading":"Performance",
    "Strategy Lab":"Research / Developer Tools","Advanced":"Research / Developer Tools",
    "Positions":"Command Center","Journal":"Performance","Developer Tools":"Research / Developer Tools"}
ADVANCED_FIELDS=("opportunity_id","source_signal_id","trade_id","position_id","exact_timestamps","raw_reason_codes","contract_metadata","lifecycle")


def context_label(context):
    checks=(context or {}).get("checks") or {};statuses=[(value or {}).get("status") for value in checks.values()]
    if statuses.count("PASS")>=3 and "FAIL" not in statuses:return "Strong"
    if "FAIL" in statuses:return "Weak"
    if any(value in {"PASS","WARN"} for value in statuses):return "Mixed"
    return "Unavailable"


def unified_opportunities(events, mirrors, filtered, contexts, shadows):
    mirror={str(r.get("opportunity_id")):r for r in mirrors}; filt={str(r.get("opportunity_id")):r for r in filtered}
    ctx={str(r.get("opportunity_id")):r for r in contexts}; shadow={str(r.get("opportunity_id")):r for r in shadows}
    rows=[]
    for event in events:
        identity=str(event.get("opportunity_id") or event.get("trade_id"));m=mirror.get(identity,{}) ;f=filt.get(identity,{}) ;c=ctx.get(identity,{})
        broad="Accepted" if f.get("broad_decision")=="ACCEPTED" else f"Rejected: {f.get('broad_reason') or 'Rule'}" if f else "Pending"
        filtered_state="Executed" if f.get("execution_eligible") else f"Rejected: {f.get('execution_rejection_reason') or 'Not eligible'}" if f else "Pending"
        row={"Symbol":event.get("symbol"),"Direction":event.get("direction"),"Setup":event.get("setup"),
            "Confidence / Quality":event.get("rule_score"),"Context":context_label(c),"Spread":m.get("spread_percent"),
            "Signal Age":f.get("signal_age_seconds"),"BROAD":broad,"FILTERED":filtered_state,
            "Status":"Open" if m.get("status") in {"OPEN","EXIT_PENDING"} else "Closed" if m.get("status")=="CLOSED" else m.get("disposition_code") or "Ready",
            "_advanced":{"opportunity_id":identity,"source_signal_id":f.get("source_signal_id"),"trade_id":m.get("mirror_trade_id"),
                "exact_timestamps":{"signal":event.get("event_timestamp"),"opened":m.get("opened_at"),"closed":m.get("exit_quote_at")},
                "raw_reason_codes":{"mirror":m.get("disposition_code"),"broad":f.get("broad_reason"),"filtered":f.get("execution_rejection_reason")},
                "contract_metadata":{"contract":m.get("option_symbol"),"bid":m.get("entry_bid"),"ask":m.get("entry_ask"),"dte":m.get("dte")},
                "lifecycle":c.get("lifecycle") or {}},"_context":c,"_shadow":shadow.get(identity,{})}
        rows.append(row)
    return rows


def unified_positions(mirrors, broad, filtered, health):
    health_map={(str(r.get("lane")),str(r.get("trade_id"))):r for r in health}
    rows=[]
    for row in mirrors:
        if row.get("status") not in {"OPEN","EXIT_PENDING"}:continue
        h=health_map.get(("MIRROR",str(row.get("mirror_trade_id"))),{})
        rows.append(_position("MIRROR",row.get("symbol"),row.get("direction"),row.get("option_symbol"),row.get("entry_fill"),row.get("current_mark"),row.get("unrealized_pnl"),row.get("mfe_pct"),h.get("setup_health"),row.get("status")))
    for row in broad:
        if row.get("status")!="OPEN":continue
        h=health_map.get(("BROAD",str(row.get("trade_id"))),{})
        rows.append(_position("BROAD",row.get("symbol"),row.get("direction"),row.get("option_symbol"),row.get("entry_price"),row.get("current_price"),row.get("pnl"),row.get("mfe"),h.get("setup_health"),row.get("status")))
    for row in filtered:
        if row.get("status")!="OPEN" or not row.get("execution_eligible"):continue
        h=health_map.get(("FILTERED",str(row.get("filtered_trade_id"))),{})
        rows.append(_position("FILTERED",row.get("symbol"),row.get("direction"),row.get("option_symbol"),row.get("entry_fill"),row.get("current_mark"),row.get("pnl"),row.get("mfe_pct"),h.get("setup_health"),row.get("status")))
    return rows


def exact_lane_comparison(events, mirrors, broad, filtered):
    maps=[{str(r.get("opportunity_id")):r for r in values} for values in (mirrors,broad,filtered)]
    rows=[]
    for event in events:
        identity=str(event.get("opportunity_id"));m,b,f=(mapping.get(identity,{}) for mapping in maps)
        rows.append({"Symbol":event.get("symbol"),"MIRROR":_lane_state(m,"disposition_code"),
            "BROAD":"ACCEPTED" if b.get("accepted") else f"REJECTED: {b.get('reason_code')}" if b else "PENDING",
            "FILTERED":"EXECUTED" if f.get("execution_eligible") else f"REJECTED: {f.get('execution_rejection_reason')}" if f else "PENDING",
            "Outcome":m.get("realized_return_percent")})
    return rows


class ConsolidatedUIRepository:
    """Bounded explicit projections for normal UI; schema and providers are untouched."""
    def __init__(self,repository):self.repository=repository
    def command_center(self,limit=100):
        with self.repository.connection() as connection:
            events=self.repository._fetchall(connection,"""SELECT id,trade_id,opportunity_id,symbol,direction,setup,
                event_timestamp,rule_score FROM authoritative_trade_events WHERE event_type='TRADE_ENTERED'
                ORDER BY event_timestamp DESC LIMIT ?""",(min(int(limit),200),))
        ids=[str(r.get("opportunity_id")) for r in events if r.get("opportunity_id")]
        data=self._by_ids(ids)
        opportunities=unified_opportunities(events,data["mirrors"],data["filtered"],data["contexts"],data["shadows"])
        positions=unified_positions(data["mirrors"],data["broad_positions"],data["filtered"],data["health"])
        return {"opportunities":opportunities,"positions":positions,"activity":self._activity(10),
            "summary":self._today_summary(),"raw":data,"events":events}
    def performance(self,limit=5000):
        return {"lanes":self._lane_summary(),"comparison_loader":lambda:self.lane_comparison(limit=limit)}
    def lane_comparison(self,limit=5000):
        with self.repository.connection() as connection:
            events=self.repository._fetchall(connection,"""SELECT opportunity_id,symbol,event_timestamp FROM
                authoritative_trade_events WHERE event_type='TRADE_ENTERED' ORDER BY event_timestamp DESC LIMIT ?""",(min(int(limit),10000),))
        ids=[r["opportunity_id"] for r in events];data=self._by_ids(ids)
        return exact_lane_comparison(events,data["mirrors"],data["broad_decisions"],data["filtered"])
    def _by_ids(self,ids):
        if not ids:return {key:[] for key in ("mirrors","filtered","contexts","shadows","broad_decisions","broad_positions","health")}
        ids=ids[:5000];p=','.join('?' for _ in ids)
        with self.repository.connection() as c:
            mirrors=self.repository._fetchall(c,f"""SELECT mirror_trade_id,opportunity_id,symbol,direction,option_symbol,dte,
                entry_bid,entry_ask,entry_fill,current_mark,spread_percent,total_debit,opened_at,status,disposition_code,
                exit_quote_at,realized_pnl,realized_return_percent,unrealized_pnl,mfe_pct FROM mirror_execution_trades
                WHERE opportunity_id IN ({p}) ORDER BY entry_event_at DESC LIMIT ?""",(*ids,len(ids)))
            filtered=self.repository._fetchall(c,f"""SELECT filtered_trade_id,opportunity_id,source_signal_id,broad_decision,
                broad_reason,execution_eligible,execution_rejection_reason,symbol,direction,option_symbol,spread_percent,
                signal_age_seconds,entry_fill,total_debit,opened_at,closed_at,status,realized_pnl,mfe_pct FROM filtered_execution_trades
                WHERE opportunity_id IN ({p}) ORDER BY authoritative_event_at DESC LIMIT ?""",(*ids,len(ids)))
            contexts=self.repository._fetchall(c,f"""SELECT opportunity_id,context_json FROM opportunity_context
                WHERE opportunity_id IN ({p}) LIMIT ?""",(*ids,len(ids)))
            shadows=self.repository._fetchall(c,f"""SELECT opportunity_id,decision,decision_json FROM context_shadow_decisions
                WHERE opportunity_id IN ({p}) LIMIT ?""",(*ids,len(ids)))
            broad_decisions=self.repository._fetchall(c,f"""SELECT t.source_signal_id AS opportunity_id,j.accepted,j.reason_code
                FROM paper_execution_trades t JOIN paper_execution_journal j ON j.trade_id=t.trade_id
                WHERE t.source_signal_id IN ({p}) ORDER BY j.created_at DESC LIMIT ?""",(*ids,len(ids)*3))
            broad_positions=self.repository._fetchall(c,f"""SELECT t.source_signal_id AS opportunity_id,p.trade_id,p.symbol,
                p.option_symbol,p.option_type AS direction,p.entry_option_price AS entry_price,p.current_option_price AS current_price,
                p.unrealized_pnl_dollars AS pnl,p.mfe_pct AS mfe,p.status FROM paper_execution_positions p
                JOIN paper_execution_trades t ON t.trade_id=p.trade_id WHERE t.source_signal_id IN ({p}) LIMIT ?""",(*ids,len(ids)))
            health=self.repository._fetchall(c,f"""SELECT pcm.trade_id,pcm.opportunity_id,pcm.lane,pcm.setup_health,pcm.observed_at
                FROM position_context_marks pcm JOIN (SELECT lane,trade_id,MAX(observed_at) observed_at FROM position_context_marks
                WHERE opportunity_id IN ({p}) GROUP BY lane,trade_id) latest ON latest.lane=pcm.lane AND latest.trade_id=pcm.trade_id
                AND latest.observed_at=pcm.observed_at LIMIT ?""",(*ids,len(ids)*3))
        for row in contexts:
            try:row.update(json.loads(row.pop("context_json")))
            except Exception:pass
        for row in shadows:
            try:row.update(json.loads(row.pop("decision_json")))
            except Exception:pass
        return {"mirrors":mirrors,"filtered":filtered,"contexts":contexts,"shadows":shadows,
            "broad_decisions":broad_decisions,"broad_positions":broad_positions,"health":health}
    def _lane_summary(self):
        queries={"MIRROR":("mirror_execution_trades","realized_pnl","realized_return_percent","total_debit","exit_quote_at"),
            "BROAD":("paper_execution_trades","realized_pnl_dollars","realized_return_pct","total_debit","closed_at"),
            "FILTERED":("filtered_execution_trades","realized_pnl","realized_return_percent","total_debit","closed_at")}
        result=[]
        with self.repository.connection() as c:
            for lane,(table,pnl,ret,debit,closed) in queries.items():
                row=self.repository._fetchone(c,f"""SELECT COUNT(*) AS closed,
                    SUM(CASE WHEN {pnl}>0 THEN 1 ELSE 0 END) wins,SUM(CASE WHEN {pnl}<0 THEN 1 ELSE 0 END) losses,
                    SUM({pnl}) pnl,AVG({ret}) average_return,AVG({pnl}) expectancy,
                    SUM(CASE WHEN {pnl}>0 THEN {pnl} ELSE 0 END) gross_profit,
                    ABS(SUM(CASE WHEN {pnl}<0 THEN {pnl} ELSE 0 END)) gross_loss,
                    MAX({debit}) peak_capital FROM {table} WHERE {closed} IS NOT NULL""") or {}
                closed_n=int(row.get("closed") or 0);wins=int(row.get("wins") or 0);losses=int(row.get("losses") or 0);peak=_num(row.get("peak_capital"));pnl_value=_num(row.get("pnl"))
                result.append({"Lane":lane,"Closed Trades":closed_n,"Wins":wins,"Losses":losses,
                    "Win Rate":wins/(wins+losses)*100 if wins+losses else None,"P&L":pnl_value,
                    "Average Return":_num(row.get("average_return")),"Expectancy":_num(row.get("expectancy")),
                    "Profit Factor":_num(row.get("gross_profit"))/_num(row.get("gross_loss")) if _num(row.get("gross_loss")) else None,
                    "Peak Capital":peak,"Return on Peak Capital":pnl_value/peak*100 if pnl_value is not None and peak else None})
        return result
    def _today_summary(self):
        today=datetime.now(timezone.utc).date().isoformat()
        queries={"Signals":("authoritative_trade_events","event_timestamp","COUNT(*)","event_type='TRADE_ENTERED'"),
            "MIRROR P&L":("mirror_execution_trades","entry_event_at","COALESCE(SUM(realized_pnl),0)","1=1"),
            "BROAD P&L":("paper_execution_trades","opened_at","COALESCE(SUM(realized_pnl_dollars),0)","1=1"),
            "FILTERED P&L":("filtered_execution_trades","opened_at","COALESCE(SUM(realized_pnl),0)","1=1")}
        result={}
        with self.repository.connection() as c:
            for label,(table,column,expression,extra) in queries.items():
                row=self.repository._fetchone(c,f"SELECT {expression} value FROM {table} WHERE {column}>=? AND {extra}",(today,)) or {};result[label]=row.get("value")
            open_row=self.repository._fetchone(c,"""SELECT
                (SELECT COUNT(*) FROM mirror_execution_trades WHERE status IN ('OPEN','EXIT_PENDING'))+
                (SELECT COUNT(*) FROM paper_execution_positions WHERE status='OPEN')+
                (SELECT COUNT(*) FROM filtered_execution_trades WHERE status='OPEN' AND execution_eligible=1) value""") or {}
            capital=self.repository._fetchone(c,"""SELECT COALESCE(SUM(total_debit),0) value FROM mirror_execution_trades
                WHERE status IN ('OPEN','EXIT_PENDING')""") or {}
        result.update({"Open Positions":open_row.get("value"),"Capital Deployed":capital.get("value")});return result
    def _activity(self,limit):
        with self.repository.connection() as c:
            mirror=self.repository._fetchall(c,"""SELECT event_at,event_type,reason_code,opportunity_id FROM
                mirror_execution_journal ORDER BY event_at DESC LIMIT ?""",(limit,))
            filt=self.repository._fetchall(c,"""SELECT updated_at,opportunity_id,symbol,status,execution_rejection_reason,
                realized_return_percent FROM filtered_execution_trades ORDER BY updated_at DESC LIMIT ?""",(limit,))
        rows=[{"At":r.get("event_at"),"Event":f"MIRROR {str(r.get('event_type') or '').replace('_',' ').title()}"} for r in mirror]
        rows += [{"At":r.get("updated_at"),"Event":f"FILTERED {r.get('symbol')} — {r.get('execution_rejection_reason') or r.get('status')}"} for r in filt]
        return sorted(rows,key=lambda r:str(r.get("At") or ""),reverse=True)[:limit]


def render_command_center(st,repository,latest_results,trade_state):
    st.markdown("## Command Center");st.caption("What is happening · What matters · What you are holding · System status")
    model=ConsolidatedUIRepository(repository).command_center() if repository else {"opportunities":[],"positions":[],"activity":[],"summary":{}}
    spy=(latest_results or {}).get("SPY") or {};qqq=(latest_results or {}).get("QQQ") or {};health=(trade_state or {}).get("reliability_state") or "Unavailable"
    strip=st.columns(6)
    for column,(label,value) in zip(strip,(("Market",spy.get("market_status") or "Unavailable"),("Regime",spy.get("market_regime") or spy.get("regime") or "Unavailable"),("SPY",spy.get("bias") or "Unavailable"),("QQQ",qqq.get("bias") or "Unavailable"),("System",health),("Scanner",_freshness(trade_state)))):column.metric(label,value)
    st.markdown("### Today")
    columns=st.columns(6)
    for column,(label,value) in zip(columns,model["summary"].items()):column.metric(label,_display(value,money="P&L" in label or "Capital" in label))
    st.markdown("### Current Opportunities")
    if not model["opportunities"]:st.caption("No current signals require attention.")
    else:
        visible=[{k:_display(v,percentage=k=="Spread",seconds=k=="Signal Age") for k,v in row.items() if not k.startswith("_")} for row in model["opportunities"]]
        st.dataframe(pd.DataFrame(visible),use_container_width=True,hide_index=True)
        labels=[f"{row['Symbol']} · {row['Direction']} · {row['Setup']}" for row in model["opportunities"]]
        selected=st.selectbox("Opportunity detail",range(len(labels)),format_func=lambda i:labels[i],key="command_opportunity_detail")
        _render_opportunity_detail(st,model["opportunities"][selected])
    st.markdown("### Open Positions")
    if model["positions"]:st.dataframe(pd.DataFrame(model["positions"]),use_container_width=True,hide_index=True)
    else:st.caption("No open BROAD/FILTERED/MIRROR positions.")
    st.markdown("### Recent Activity")
    if model["activity"]:st.dataframe(pd.DataFrame(model["activity"]),use_container_width=True,hide_index=True)
    else:st.caption("No meaningful trade activity yet.")
    return model


def render_performance(st,repository,scorecard_renderer):
    st.markdown("## Performance");st.caption("Consistent MIRROR · BROAD · FILTERED accounting")
    model=ConsolidatedUIRepository(repository).performance() if repository else {"lanes":[]}
    if model["lanes"]:st.dataframe(pd.DataFrame([{k:_display(v,money=k in {"P&L","Expectancy","Peak Capital"},percentage=k in {"Win Rate","Average Return","Return on Peak Capital"}) for k,v in row.items()} for row in model["lanes"]]),use_container_width=True,hide_index=True)
    else:st.caption("No completed lane results are available.")
    with st.expander("Daily Results",expanded=False):
        if st.button("Load Daily Experiment Scorecard",key="performance_load_scorecard"):scorecard_renderer(st,repository)
    with st.expander("Unified Lane Comparison",expanded=False):
        if st.button("Load MIRROR / BROAD / FILTERED Comparison",key="performance_load_comparison"):
            rows=ConsolidatedUIRepository(repository).lane_comparison();st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True) if rows else st.caption("No comparable signals.")
    with st.expander("Performance Analytics",expanded=False):
        st.caption("BROAD Filter Performance · Winner DNA · Spread and Signal Age · Market, Sector, RelVol and Timeframe Attribution · Option Execution · Context Interactions")
        st.caption("Load these analyses from Research / Developer Tools to keep historical egress on demand.")
    return model


def _render_opportunity_detail(st,row):
    c=row.get("_context") or {};checks=c.get("checks") or {}
    with st.expander("Why This Trade",expanded=False):
        st.dataframe(pd.DataFrame([{"Factor":key.replace("_"," ").title(),"State":(value or {}).get("status") or "UNKNOWN"} for key,value in checks.items()]),use_container_width=True,hide_index=True)
    with st.expander("Technical Details",expanded=False):
        features=c.get("features") or {};sector=c.get("sector") or {};st.json({"RSI":features.get("rsi"),"VWAP":features.get("vwap_relationship"),"EMA":features.get("ema_alignment"),"Relative Volume":(c.get("relative_volume") or {}).get("value"),"Multi-Timeframe":c.get("multi_timeframe"),"Structure":(c.get("structure") or {}).get("classification"),"Market Regime":(c.get("market") or {}).get("market_regime"),"Sector Relative Strength":sector.get("stock_vs_sector_relative_strength"),"Catalyst":c.get("catalyst")})
    with st.expander("Advanced / Technical",expanded=False):st.json(row.get("_advanced") or {})


def _position(lane,symbol,direction,contract,entry,current,pnl,mfe,health,status):return {"Symbol":symbol,"Lane":lane,"Direction":direction,"Contract":contract,"Entry":_display(entry,money=True),"Current":_display(current,money=True),"P&L":_display(pnl,money=True),"MFE":_display(mfe,percentage=True),"Trade Health":health or "Unavailable","Exit Status":status}
def _lane_state(row,key):return "EXECUTED" if row.get("opened_at") else str(row.get(key) or "PENDING").replace("MIRROR_","")
def _num(value):
    try:value=float(value);return value if math.isfinite(value) else None
    except (TypeError,ValueError):return None
def _display(value,money=False,percentage=False,seconds=False):
    value=_num(value) if isinstance(value,(int,float)) else value
    if value is None:return "—"
    if money and isinstance(value,(int,float)):return f"${value:+,.2f}"
    if percentage and isinstance(value,(int,float)):return f"{value:.1f}%"
    if seconds and isinstance(value,(int,float)):return f"{value:.0f}s"
    return value
def _freshness(state):
    value=(state or {}).get("last_success_at");return value.isoformat() if hasattr(value,"isoformat") else str(value or "Unavailable")
