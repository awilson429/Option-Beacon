"""Phase 2 deterministic shadow research; never owns trading decisions or exits."""
from __future__ import annotations

import hashlib
import json
import logging
import math
from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean, median

from opportunity_context import experiment_scope, number, signal_age_bucket, timestamp

LOGGER = logging.getLogger(__name__)
CONVICTION_DIMENSIONS = (
    "setup_quality", "momentum_quality", "market_alignment", "sector_alignment",
    "multi_timeframe_alignment", "relative_volume_quality", "catalyst_quality",
    "signal_freshness", "option_quality", "execution_quality",
)


def llm_synthesis_interface(context):
    """Documented disabled interface; no client, request, cost, or trading authority."""
    return {"status":"DISABLED","context_summary":None,"strongest_supporting_factors":[],
            "strongest_conflicting_factors":[],"context_quality":"UNKNOWN","research_rank":None,
            "uncertainty":"NOT_EVALUATED","rationale":None,"allowed_biases":["BUY_BIAS","WATCH_BIAS","AVOID_BIAS"],
            "trading_authority":False}


def context_conviction(context):
    checks = context.get("checks") or {}
    features = context.get("features") or {}
    option = context.get("option_execution") or {}
    structure = (context.get("structure") or {}).get("classification")
    relvol = number((context.get("relative_volume") or {}).get("value"))
    age = number((context.get("lifecycle") or {}).get("authoritative_to_mirror_open_seconds"))
    spread = number(option.get("spread_percent"))
    available = number((context.get("multi_timeframe") or {}).get("total_timeframes_available"))
    aligned = number((context.get("multi_timeframe") or {}).get("multi_timeframe_alignment_pct"))
    dimensions = {
        "setup_quality": _dimension("PASS", 80, [structure], structure not in (None, "INSUFFICIENT_DATA")),
        "momentum_quality": _numeric_dimension(number(features.get("momentum_acceleration")), 0, "MOMENTUM_POSITIVE"),
        "market_alignment": _from_check(checks.get("market_alignment")),
        "sector_alignment": _from_check(checks.get("sector_alignment")),
        "multi_timeframe_alignment": _dimension("PASS" if aligned is not None and aligned >= 67 else "WARN", aligned, [f"ALIGNED_{aligned}"], bool(available)),
        "relative_volume_quality": _dimension("PASS" if relvol is not None and relvol >= 1 else "WARN", min(100, relvol * 40) if relvol is not None else None, [f"RELVOL_{relvol}"], relvol is not None),
        "catalyst_quality": _dimension("UNKNOWN", None, ["CATALYST_NOT_AVAILABLE"], (context.get("catalyst") or {}).get("availability") == "AVAILABLE"),
        "signal_freshness": _dimension("PASS" if age is not None and age <= 180 else "WARN", max(0, 100-age/3) if age is not None else None, ["AUTHORITATIVE_TO_EXECUTION_GT_180S"] if age is not None and age > 180 else ["SIGNAL_AGE_ACCEPTABLE"], age is not None),
        "option_quality": _dimension("PASS" if spread is not None and spread <= 20 else "FAIL", max(0, 100-spread*4) if spread is not None else None, [f"SPREAD_PERCENT_{spread}"], spread is not None),
        "execution_quality": _dimension("PASS" if option.get("conservative_fill") is not None else "UNKNOWN", None, ["CONSERVATIVE_FILL_PRESENT"] if option.get("conservative_fill") is not None else ["EXECUTION_NOT_AVAILABLE"], option.get("conservative_fill") is not None),
    }
    return {"model": "CONTEXT_CONVICTION_V1", "dimensions": dimensions,
            "coverage_complete": sum(v["coverage"] == "COMPLETE" for v in dimensions.values()),
            "coverage_total": len(CONVICTION_DIMENSIONS)}


def context_shadow_decision(context):
    conviction = context_conviction(context)
    dims = conviction["dimensions"]
    spread = number((context.get("option_execution") or {}).get("spread_percent"))
    relvol = number((context.get("relative_volume") or {}).get("value"))
    mtf = number((context.get("multi_timeframe") or {}).get("multi_timeframe_alignment_pct"))
    severe_conflict = dims["market_alignment"]["status"] == "WARN" and dims["sector_alignment"]["status"] == "WARN" and mtf == 0
    if spread is not None and spread > 20:
        decision, reasons = "WOULD_REJECT", ["PREDECLARED_SPREAD_GT_20"]
    elif severe_conflict and relvol is not None and relvol < .5:
        decision, reasons = "WOULD_REJECT", ["MARKET_SECTOR_TIMEFRAME_CONFLICT", "RELVOL_LT_0_5"]
    else:
        passes = sum(value["status"] == "PASS" for value in dims.values())
        decision = "WOULD_TRADE" if passes >= 5 and dims["option_quality"]["status"] != "FAIL" else "WOULD_WATCH"
        reasons = [f"PASS_DIMENSIONS_{passes}", "DESCRIPTIVE_WHEN_COVERAGE_LIMITED"]
    return {"lane": "CONTEXT_SHADOW", "decision": decision, "reasons": reasons,
            "conviction": conviction, "cannot_open_positions": True, "evaluated_at": datetime.now(timezone.utc).isoformat()}


def setup_health(mark, previous=None):
    required = [mark.get("price_vs_vwap"), mark.get("multi_timeframe_alignment"), mark.get("unrealized_return")]
    if all(value is None for value in required): return "INSUFFICIENT_DATA"
    direction = str(mark.get("direction") or "").upper()
    vwap = str(mark.get("price_vs_vwap") or "UNKNOWN").upper()
    vwap_broken = (direction.startswith("BULL") and vwap == "BELOW") or (direction.startswith("BEAR") and vwap == "ABOVE")
    mtf = number(mark.get("multi_timeframe_alignment"))
    market_opposed = str(mark.get("market_alignment") or "") == "WARN"
    ema_failed = mark.get("ema_aligned") is False
    if vwap_broken and (ema_failed or market_opposed or (mtf is not None and mtf < 34)): return "BROKEN"
    weakening = vwap_broken or ema_failed or market_opposed or (mtf is not None and mtf < 50)
    if previous and previous.get("setup_health") in {"BROKEN", "WEAKENING"} and not weakening: return "RECOVERING"
    return "WEAKENING" if weakening else "HEALTHY"


def position_context_mark(*, trade_id, opportunity_id, lane, symbol, observed_at, context=None, quote=None,
                          underlying_price=None, option_mark=None, unrealized_return=None, mfe=None, mae=None,
                          direction=None, technical=None, previous=None):
    context, quote, technical = context or {}, quote or {}, technical or {}
    market, sector, mtf = context.get("market") or {}, context.get("sector") or {}, context.get("multi_timeframe") or {}
    bid, ask = number(quote.get("bid")), number(quote.get("ask"))
    midpoint = (bid+ask)/2 if bid is not None and ask is not None else None
    spread = (ask-bid)/midpoint*100 if midpoint else None
    mark = {"trade_id": str(trade_id), "opportunity_id": str(opportunity_id), "lane": lane,
        "symbol": symbol, "observed_at": timestamp(observed_at).isoformat(), "underlying_price": number(underlying_price),
        "option_mark": number(option_mark), "unrealized_return": number(unrealized_return), "mfe_to_date": number(mfe), "mae_to_date": number(mae),
        "direction": direction, "market_regime": market.get("market_regime"), "spy_trend": market.get("spy_direction"),
        "qqq_trend": market.get("qqq_direction"), "market_alignment": ((context.get("checks") or {}).get("market_alignment") or {}).get("status"),
        "sector_trend": sector.get("sector_direction"), "stock_vs_sector_strength": sector.get("stock_vs_sector_relative_strength"),
        "sector_vs_spy_strength": sector.get("sector_vs_spy_relative_strength"), "price_vs_vwap": technical.get("price_vs_vwap"),
        "ema_aligned": technical.get("ema_aligned"), "rsi": number(technical.get("rsi")),
        "relative_volume": number(technical.get("relative_volume") or (context.get("relative_volume") or {}).get("value")),
        "multi_timeframe_alignment": number(technical.get("multi_timeframe_alignment") or mtf.get("multi_timeframe_alignment_pct")),
        "bid": bid, "ask": ask, "midpoint": midpoint, "spread_percent": spread,
        "atr": number(technical.get("atr")), "underlying_peak": number(technical.get("underlying_peak")),
        "ha_state": technical.get("ha_state") or "INSUFFICIENT_DATA"}
    mark["setup_health"] = setup_health(mark, previous)
    mark["mark_id"] = hashlib.sha256(f"{lane}|{trade_id}|{mark['observed_at']}".encode()).hexdigest()
    return mark


def heikin_ashi_states(bars):
    states, prior_open, prior_close = [], None, None
    for bar in bars:
        values = [number(bar.get(k)) for k in ("open", "high", "low", "close")]
        if any(v is None for v in values): states.append("INSUFFICIENT_DATA"); continue
        o, h, l, c = values; ha_close = (o+h+l+c)/4
        ha_open = (o+c)/2 if prior_open is None else (prior_open+prior_close)/2
        states.append("BULLISH" if ha_close > ha_open else "BEARISH" if ha_close < ha_open else "NEUTRAL")
        prior_open, prior_close = ha_open, ha_close
    return states


def entry_current_exit_deltas(marks):
    ordered = sorted(marks, key=lambda row: timestamp(row.get("observed_at")) or datetime.min.replace(tzinfo=timezone.utc))
    if not ordered: return None
    entry, exit_mark = ordered[0], ordered[-1]
    best = max(ordered, key=lambda row: number(row.get("unrealized_return")) if number(row.get("unrealized_return")) is not None else -math.inf)
    worst = min(ordered, key=lambda row: number(row.get("unrealized_return")) if number(row.get("unrealized_return")) is not None else math.inf)
    return {"trade_id": entry.get("trade_id"), "opportunity_id": entry.get("opportunity_id"), "entry": entry,
        "best": best, "worst": worst, "exit": exit_mark, "rsi_change": _delta(entry, exit_mark, "rsi"),
        "relative_volume_change": _delta(entry, exit_mark, "relative_volume"), "spread_change": _delta(entry, exit_mark, "spread_percent"),
        "alignment_change": _delta(entry, exit_mark, "multi_timeframe_alignment"),
        "market_regime_changed": entry.get("market_regime") != exit_mark.get("market_regime"),
        "vwap_status_changed": entry.get("price_vs_vwap") != exit_mark.get("price_vs_vwap"),
        "mfe": max((number(r.get("unrealized_return")) for r in ordered if number(r.get("unrealized_return")) is not None), default=None),
        "mae": min((number(r.get("unrealized_return")) for r in ordered if number(r.get("unrealized_return")) is not None), default=None)}


def simulate_shadow_exits(marks):
    """First-trigger simulations over ordered observed marks; never writes real exits."""
    ordered = sorted(marks, key=lambda row: timestamp(row.get("observed_at")) or datetime.min.replace(tzinfo=timezone.utc))
    policies = {}
    for name, predicate in {
        "SETUP_HEALTH_EXIT": lambda r, _p: r.get("setup_health") == "BROKEN",
        "VWAP_FAILURE": lambda r, _p: _vwap_failed(r),
        "EMA_TREND_FAILURE": lambda r, _p: r.get("ema_aligned") is False,
        "HA_FIRST_OPPOSING": lambda r, _p: _ha_opposed(r),
        "HA_TWO_OPPOSING": lambda r, p: _ha_opposed(r) and p is not None and _ha_opposed(p),
        "HA_VWAP_FAILURE": lambda r, _p: _ha_opposed(r) and _vwap_failed(r),
        "HA_EMA_FAILURE": lambda r, _p: _ha_opposed(r) and r.get("ema_aligned") is False,
    }.items():
        policies[name] = _first_trigger(ordered, predicate)
    for floor in (5, 10, 15):
        policies[f"BREAKEVEN_AFTER_{floor}"] = _breakeven(ordered, floor)
    for peak in (10, 15, 20, 25):
        policies[f"MFE_GIVEBACK_{peak}"] = _giveback(ordered, peak, .5)
    policies["VOLATILITY_AWARE_TRAIL"] = _atr_trail(ordered, 2)
    policies["CHANDELIER_TRAIL"] = _atr_trail(ordered, 3)
    policies["TIME_BASED_TIGHTENING"] = _time_tightening(ordered)
    policies["PARTIAL_25_AT_10"] = _partial(ordered, 10, .25)
    policies["PARTIAL_50_AT_15"] = _partial(ordered, 15, .50)
    return policies


def signal_timing(context):
    lifecycle, maturity = context.get("lifecycle") or {}, context.get("signal_maturity") or {}
    first = number(maturity.get("seconds_from_first_seen_to_authoritative"))
    setup = number(lifecycle.get("setup_to_authoritative_seconds"))
    execution = number(lifecycle.get("authoritative_to_mirror_open_seconds"))
    total = number(lifecycle.get("total_candidate_to_execution_seconds"))
    if total is None and first is not None and execution is not None:
        total = first + execution
    if total is None: label = "INSUFFICIENT_DATA"
    elif first is not None and first <= 60: label = "EARLY_VISIBLE"
    elif execution is not None and execution > 300: label = "VERY_LATE_EXECUTION"
    elif first is not None and first > 300: label = "LATE_CONFIRMATION"
    else: label = "NORMAL_MATURITY"
    return {"first_seen_to_authoritative_seconds": first, "setup_to_authoritative_seconds": setup,
            "authoritative_to_execution_seconds": execution, "total_first_seen_to_execution_seconds": total, "classification": label}


def relative_strength_bucket(value):
    value = number(value)
    if value is None: return "UNKNOWN"
    if value >= 2: return "STRONG_OUTPERFORMANCE"
    if value >= .5: return "MODERATE_OUTPERFORMANCE"
    if value >= -.5: return "NEUTRAL"
    return "UNDERPERFORMANCE"


def moneyness_bucket(value):
    value=number(value)
    if value is None:return "UNKNOWN"
    if value>1:return "ITM"
    if value < -1:return "OTM"
    return "ATM"


def liquidity_bucket(value):
    value=number(value)
    if value is None:return "UNKNOWN"
    if value<10:return "LT_10"
    if value<50:return "10_49"
    if value<100:return "50_99"
    if value<500:return "100_499"
    return "GE_500"


def portfolio_context(candidate, open_positions, correlations=None):
    correlations = correlations or {}
    sector = candidate.get("sector"); direction = candidate.get("direction"); symbol = candidate.get("symbol")
    same_sector = sum(row.get("sector") == sector and sector not in (None, "UNKNOWN") for row in open_positions)
    same_direction = sum(row.get("direction") == direction and direction is not None for row in open_positions)
    correlated = sum(number(correlations.get(tuple(sorted((symbol, row.get("symbol")))))) is not None and correlations[tuple(sorted((symbol, row.get("symbol"))))] >= .8 for row in open_positions if row.get("symbol"))
    debit = sum(number(row.get("debit")) or 0 for row in open_positions)
    return {"simultaneous_positions": len(open_positions), "same_sector_positions": same_sector,
            "same_direction_positions": same_direction, "highly_correlated_positions": correlated,
            "aggregate_debit_before": debit, "aggregate_debit_after": debit+(number(candidate.get("debit")) or 0),
            "increases_sector_concentration": same_sector > 0, "increases_direction_concentration": same_direction > 0,
            "increases_correlated_exposure": correlated > 0}


def research_coverage(contexts, marks):
    paths = {"market_regime": ("market","market_regime"), "sector_mapping": ("sector","sector"),
        "relative_strength": ("sector","stock_vs_sector_relative_strength"), "multi_timeframe_trend": ("multi_timeframe","total_timeframes_available"),
        "relative_volume": ("relative_volume","value"), "signal_timing": ("lifecycle","setup_to_authoritative_seconds"),
        "pullback_reclaim": ("structure","classification"), "option_spread": ("option_execution","spread_percent"),
        "option_volume": ("option_execution","volume"), "open_interest": ("option_execution","open_interest"),
        "catalyst": ("catalyst","catalyst_type")}
    rows = [_coverage(name, contexts, path) for name, path in paths.items()]
    rows += [{"factor":"position_context_refresh","available":len(marks),"total":len(contexts),"coverage_pct":len({m.get('opportunity_id') for m in marks})/len(contexts)*100 if contexts else None},
             {"factor":"setup_health_classification","available":sum(m.get("setup_health") != "INSUFFICIENT_DATA" for m in marks),"total":len(marks),"coverage_pct":sum(m.get("setup_health") != "INSUFFICIENT_DATA" for m in marks)/len(marks)*100 if marks else None}]
    return rows


def aggregate_research(contexts, decisions, marks):
    groups = defaultdict(int)
    for row in decisions: groups[row.get("decision") or "UNKNOWN"] += 1
    health = defaultdict(int)
    for row in marks: health[row.get("setup_health") or "UNKNOWN"] += 1
    exits = []
    by_trade = defaultdict(list)
    for row in marks: by_trade[(row.get("lane"),row.get("trade_id"))].append(row)
    for key, rows in by_trade.items():
        for policy, trigger in simulate_shadow_exits(rows).items():
            if trigger: exits.append({"lane":key[0],"trade_id":key[1],"policy":policy,**trigger})
    LOGGER.info(json.dumps({"event":"context_attribution_generated","contexts":len(contexts),"marks":len(marks),"shadow_decisions":len(decisions)}, sort_keys=True))
    return {"context_shadow":dict(groups), "setup_health":dict(health), "coverage":research_coverage(contexts,marks),
            "deltas":[entry_current_exit_deltas(rows) for rows in by_trade.values()], "shadow_exits":exits,
            "timing":[{"opportunity_id":c.get("opportunity_id"),**signal_timing(c)} for c in contexts]}


class ContextualResearchRepository:
    """On-demand bounded Phase 2 reads; no schema initialization and no writes."""
    def __init__(self, repository): self.repository=repository
    def load(self, *, scope="FORWARD TEST", limit=5000):
        contexts=self.repository.list_opportunity_contexts(limit=min(int(limit),10000))
        if scope!="ALL":contexts=[c for c in contexts if c.get("experiment_scope")==scope.replace(" ","_")]
        ids=[c["opportunity_id"] for c in contexts]
        decisions=self.repository.list_context_shadow_decisions(scope=scope,limit=limit)
        marks=self.repository.list_position_context_marks(opportunity_ids=ids,limit=min(int(limit)*4,20000)) if ids else []
        filtered=[]
        if ids:
            placeholders=','.join('?' for _ in ids)
            try:
                with self.repository.connection() as connection:
                    filtered=self.repository._fetchall(connection,f"""SELECT opportunity_id,broad_decision,
                        spread_percent,signal_age_seconds FROM filtered_execution_trades
                        WHERE opportunity_id IN ({placeholders}) ORDER BY authoritative_event_at LIMIT ?""",
                        (*ids,min(int(limit),10000)))
            except Exception:
                filtered=[]
        report=aggregate_research(contexts,decisions,marks)
        report.update({"scope":scope,"contexts":len(contexts),"marks":len(marks),
            "relative_strength":[{"opportunity_id":c["opportunity_id"],
                "stock_vs_sector":relative_strength_bucket((c.get("sector") or {}).get("stock_vs_sector_relative_strength")),
                "stock_vs_spy":relative_strength_bucket((c.get("sector") or {}).get("stock_vs_spy_relative_strength")),
                "sector_vs_spy":relative_strength_bucket((c.get("sector") or {}).get("sector_vs_spy_relative_strength"))} for c in contexts],
            "multi_timeframe":[{"opportunity_id":c["opportunity_id"],**(c.get("multi_timeframe") or {})} for c in contexts],
            "regimes":_counts((c.get("market") or {}).get("market_regime") for c in contexts),
            "structures":_counts((c.get("structure") or {}).get("classification") for c in contexts),
            "relvol_spread":[{"opportunity_id":c["opportunity_id"],"relative_volume_bucket":(c.get("relative_volume") or {}).get("bucket"),
                "spread_bucket":(c.get("option_execution") or {}).get("spread_bucket")} for c in contexts],
            "option_execution":[{"opportunity_id":c["opportunity_id"],
                "spread_bucket":(c.get("option_execution") or {}).get("spread_bucket"),
                "signal_age_bucket":signal_age_bucket((c.get("lifecycle") or {}).get("authoritative_to_mirror_open_seconds")),
                "dte_bucket":(c.get("option_execution") or {}).get("dte_bucket"),
                "moneyness_bucket":moneyness_bucket((c.get("option_execution") or {}).get("signed_moneyness_percent")),
                "volume_bucket":liquidity_bucket((c.get("option_execution") or {}).get("volume")),
                "oi_bucket":liquidity_bucket((c.get("option_execution") or {}).get("open_interest"))} for c in contexts],
            "interactions":interaction_counts(contexts,filtered),
            "provenance":_counts((c.get("discovery") or {}).get("source") or "UNKNOWN" for c in contexts)})
        return report


def _counts(values):
    result=defaultdict(int)
    for value in values:result[str(value or "UNKNOWN")]+=1
    return [{"value":key,"N":value} for key,value in sorted(result.items())]


def interaction_counts(contexts, filtered_rows):
    filtered={str(r.get("opportunity_id")):r for r in filtered_rows}
    def values(c):
        option=c.get("option_execution") or {}; sector=c.get("sector") or {}; checks=c.get("checks") or {}; mtf=c.get("multi_timeframe") or {}
        f=filtered.get(str(c.get("opportunity_id")),{})
        spread=number(option.get("spread_percent") if option.get("spread_percent") is not None else f.get("spread_percent"))
        age=number((c.get("lifecycle") or {}).get("authoritative_to_mirror_open_seconds") if (c.get("lifecycle") or {}).get("authoritative_to_mirror_open_seconds") is not None else f.get("signal_age_seconds"))
        relvol=number((c.get("relative_volume") or {}).get("value")); structure=(c.get("structure") or {}).get("classification")
        market=(checks.get("market_alignment") or {}).get("status")=="PASS";sector_ok=sector.get("sector_alignment_with_trade") is True
        timeframe=number(mtf.get("multi_timeframe_alignment_pct"));broad=f.get("broad_decision")=="ACCEPTED"
        return {"tight":spread is not None and spread<=20,"fresh":age is not None and age<=180,"market":market,
            "sector":sector_ok,"high_relvol":relvol is not None and relvol>=1.5,"pullback":"RECLAIM" in str(structure),
            "timeframe":timeframe is not None and timeframe>=67,"broad":broad}
    tests={"tight spread + fresh signal":lambda v:v["tight"] and v["fresh"],
        "strong sector + strong market regime":lambda v:v["sector"] and v["market"],
        "high RelVol + sector alignment":lambda v:v["high_relvol"] and v["sector"],
        "pullback/reclaim + high RelVol":lambda v:v["pullback"] and v["high_relvol"],
        "multi-timeframe alignment + fresh signal":lambda v:v["timeframe"] and v["fresh"],
        "BROAD accepted + tight spread":lambda v:v["broad"] and v["tight"],
        "BROAD accepted + tight spread + fresh signal":lambda v:v["broad"] and v["tight"] and v["fresh"],
        "strong market + sector + timeframe alignment":lambda v:v["market"] and v["sector"] and v["timeframe"]}
    normalized=[values(c) for c in contexts]
    return [{"interaction":name,"N":sum(predicate(v) for v in normalized),"governance":"INSUFFICIENT DATA" if sum(predicate(v) for v in normalized)<10 else "UNSTABLE"} for name,predicate in tests.items()]


def _dimension(status, score, reasons, covered): return {"status":status if covered else "UNKNOWN","score":score if covered else None,"reasons":reasons,"coverage":"COMPLETE" if covered else "UNAVAILABLE"}
def _from_check(check):
    check=check or {}; return _dimension(check.get("status") or "UNKNOWN", 85 if check.get("status")=="PASS" else 45 if check.get("status")=="WARN" else None, list((check.get("values") or {}).keys()), bool(check))
def _numeric_dimension(value, threshold, reason): return _dimension("PASS" if value is not None and value>threshold else "WARN", min(100,max(0,50+value*10)) if value is not None else None,[reason],value is not None)
def _delta(a,b,key):
    x,y=number(a.get(key)),number(b.get(key)); return y-x if x is not None and y is not None else None
def _vwap_failed(r): return (str(r.get("direction") or "").upper().startswith("BULL") and r.get("price_vs_vwap")=="BELOW") or (str(r.get("direction") or "").upper().startswith("BEAR") and r.get("price_vs_vwap")=="ABOVE")
def _ha_opposed(r): return (str(r.get("direction") or "").upper().startswith("BULL") and r.get("ha_state")=="BEARISH") or (str(r.get("direction") or "").upper().startswith("BEAR") and r.get("ha_state")=="BULLISH")
def _first_trigger(rows,predicate):
    for i,row in enumerate(rows):
        if predicate(row,rows[i-1] if i else None): return {"observed_at":row.get("observed_at"),"shadow_return":number(row.get("unrealized_return")),"reason":"OBSERVED_TRIGGER"}
    return None
def _breakeven(rows,threshold):
    armed=False
    for row in rows:
        value=number(row.get("unrealized_return")); armed=armed or (value is not None and value>=threshold)
        if armed and value is not None and value<=0:return {"observed_at":row.get("observed_at"),"shadow_return":value,"reason":"BREAKEVEN_FLOOR"}
    return None
def _giveback(rows,threshold,fraction):
    peak=None
    for row in rows:
        value=number(row.get("unrealized_return")); peak=max(peak,value) if peak is not None and value is not None else value if value is not None else peak
        if peak is not None and peak>=threshold and value is not None and value<=peak*(1-fraction):return {"observed_at":row.get("observed_at"),"shadow_return":value,"reason":"MFE_GIVEBACK"}
    return None
def _atr_trail(rows,multiple):
    for row in rows:
        price,peak,atr=number(row.get("underlying_price")),number(row.get("underlying_peak")),number(row.get("atr"))
        if price is not None and peak is not None and atr is not None and price<=peak-multiple*atr:return {"observed_at":row.get("observed_at"),"shadow_return":number(row.get("unrealized_return")),"reason":f"ATR_TRAIL_{multiple}"}
    return None
def _time_tightening(rows):
    if not rows:return None
    start=timestamp(rows[0].get("observed_at"))
    for row in rows:
        held=(timestamp(row.get("observed_at"))-start).total_seconds()/60; value=number(row.get("unrealized_return"))
        floor=-20 if held<30 else -10 if held<60 else 0
        if value is not None and value<=floor:return {"observed_at":row.get("observed_at"),"shadow_return":value,"reason":f"TIME_FLOOR_{floor}"}
    return None
def _partial(rows,threshold,fraction):
    row=next((r for r in rows if number(r.get("unrealized_return")) is not None and number(r.get("unrealized_return"))>=threshold),None)
    return {"observed_at":row.get("observed_at"),"shadow_return":number(row.get("unrealized_return")),"fraction":fraction,"reason":"PARTIAL_PROFIT"} if row else None
def _coverage(name,rows,path):
    values=[]
    for row in rows:
        value=row
        for key in path:value=value.get(key) if isinstance(value,dict) else None
        values.append(value)
    available=sum(v not in (None,"UNKNOWN","NOT_AVAILABLE","INSUFFICIENT_DATA") for v in values)
    return {"factor":name,"available":available,"total":len(rows),"coverage_pct":available/len(rows)*100 if rows else None}
