"""Deterministic, decision-time opportunity context and read-only attribution."""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, timezone
from statistics import mean
from zoneinfo import ZoneInfo
from sector_context import sector_for_symbol

EASTERN = ZoneInfo("America/New_York")
SCHEMA_VERSION = 1
TREND_TIMEFRAMES = ("1m", "5m", "15m", "60m", "daily")


def number(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def timestamp(value):
    if not value:
        return None
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def return_percent(start, end):
    start, end = number(start), number(end)
    return (end / start - 1) * 100 if start and end is not None else None


def trend_state(value):
    if isinstance(value, dict):
        fast = number(value.get("fast_ema") or value.get("ema_fast"))
        slow = number(value.get("slow_ema") or value.get("ema_slow"))
        slope = number(value.get("slope"))
        if fast is not None and slow is not None:
            if fast > slow and (slope is None or slope > 0): return "BULLISH"
            if fast < slow and (slope is None or slope < 0): return "BEARISH"
            return "NEUTRAL"
        value = value.get("trend") or value.get("direction")
    text = str(value or "").strip().upper()
    if text in {"UP", "BULLISH", "POSITIVE"}: return "BULLISH"
    if text in {"DOWN", "BEARISH", "NEGATIVE"}: return "BEARISH"
    if text in {"FLAT", "NEUTRAL", "SIDEWAYS"}: return "NEUTRAL"
    return "INSUFFICIENT_DATA"


def relative_volume_bucket(value):
    value = number(value)
    if value is None: return "UNKNOWN"
    if value < .5: return "LT_0_5"
    if value < 1: return "0_5_TO_1"
    if value < 1.5: return "1_TO_1_5"
    if value < 2: return "1_5_TO_2"
    if value < 3: return "2_TO_3"
    if value < 5: return "3_TO_5"
    return "GE_5"


def signal_age_bucket(value):
    value = number(value)
    if value is None: return "UNKNOWN"
    if value <= 30: return "LE_30"
    if value <= 60: return "31_60"
    if value <= 120: return "61_120"
    if value <= 180: return "121_180"
    if value <= 300: return "181_300"
    return "GT_300"


def spread_bucket(value):
    value = number(value)
    if value is None: return "UNKNOWN"
    if value <= 5: return "LE_5"
    if value <= 10: return "5_10"
    if value <= 15: return "10_15"
    if value <= 20: return "15_20"
    return "GT_20"


def dte_bucket(value):
    value = number(value)
    if value is None: return "UNKNOWN"
    if value <= 0: return "0"
    if value == 1: return "1"
    if value <= 3: return "2_3"
    if value <= 7: return "4_7"
    return "GT_7"


def experiment_scope(value):
    day = value if isinstance(value, date) and not isinstance(value, datetime) else timestamp(value).astimezone(EASTERN).date()
    if date(2026, 8, 10) <= day <= date(2026, 8, 13): return "DEVELOPMENT"
    if day >= date(2026, 8, 17): return "FORWARD_TEST"
    return "OUTSIDE_BOUNDARY"


def pullback_structure(data, direction):
    """Classify only measurements observed no later than the decision timestamp."""
    if data.get("observed_after_decision"): return "INSUFFICIENT_DATA"
    impulse, pullback = number(data.get("initial_impulse_magnitude")), number(data.get("pullback_depth"))
    reclaimed = data.get("reclaim_confirmed")
    if impulse is None: return "INSUFFICIENT_DATA"
    bullish = str(direction).upper().startswith("BULL")
    if pullback is not None and reclaimed is True:
        return "BULLISH_PULLBACK_RECLAIM" if bullish else "BEARISH_BOUNCE_REJECTION"
    if pullback in (None, 0) and impulse > 0:
        return "DIRECT_BREAKOUT" if bullish else "DIRECT_BREAKDOWN"
    return "NO_CLEAR_STRUCTURE"


def _elapsed(start, end):
    start, end = timestamp(start), timestamp(end)
    return max(0, (end - start).total_seconds()) if start and end and end >= start else None


def build_opportunity_context(result, record, *, captured_at=None):
    """Build solely from the point-in-time scanner result; never fetch data."""
    at = timestamp(captured_at or result.get("last_candle_at") or result.get("timestamp") or record.timestamp)
    direction = record.direction
    raw_market = dict(result.get("market_context") or {})
    spy_direction = trend_state(raw_market.get("spy_direction") or result.get("spy_direction"))
    qqq_direction = trend_state(raw_market.get("qqq_direction") or result.get("qqq_direction"))
    desired = "BULLISH" if str(direction).upper().startswith("BULL") else "BEARISH"
    volatility = number(raw_market.get("normalized_volatility") or result.get("normalized_volatility") or result.get("atr_percent"))
    if spy_direction == qqq_direction == "BULLISH": regime = "RISK_ON_TREND"
    elif spy_direction == qqq_direction == "BEARISH": regime = "RISK_OFF_TREND"
    elif volatility is not None and volatility >= 1.5: regime = "HIGH_VOLATILITY"
    elif volatility is not None and volatility <= .55: regime = "LOW_VOLATILITY"
    elif "INSUFFICIENT_DATA" in {spy_direction, qqq_direction}: regime = "INSUFFICIENT_DATA"
    else: regime = "CHOP"
    mapped_sector, mapped_etf = sector_for_symbol(record.symbol)
    sector = str(result.get("sector") or mapped_sector)
    sector_etf = result.get("sector_etf") or result.get("sector_benchmark") or mapped_etf
    stock_return = number(result.get("symbol_session_return"))
    sector_return = number(result.get("sector_session_return"))
    spy_return = number(result.get("spy_session_return"))
    stock_vs_sector = stock_return - sector_return if stock_return is not None and sector_return is not None else None
    stock_vs_spy = stock_return - spy_return if stock_return is not None and spy_return is not None else None
    sector_vs_spy = sector_return - spy_return if sector_return is not None and spy_return is not None else None
    sector_direction = trend_state("BULLISH" if sector_return is not None and sector_return > 0 else "BEARISH" if sector_return is not None and sector_return < 0 else "NEUTRAL" if sector_return == 0 else None)
    raw_trends = result.get("timeframe_trends") or {}
    trends = {frame: trend_state(raw_trends.get(frame) or result.get(f"trend_{frame}")) for frame in TREND_TIMEFRAMES}
    available = [value for value in trends.values() if value != "INSUFFICIENT_DATA"]
    aligned = sum(value == desired for value in available)
    first_seen = result.get("first_candidate_detected_at") or result.get("first_seen_timestamp")
    setup_at = result.get("setup_detected_at")
    confirmed_at = result.get("setup_confirmed_at")
    authoritative_at = getattr(record, "entry_time", None) or result.get("authoritative_entered_at")
    if authoritative_at: maturity = "AUTHORITATIVE_ENTRY"
    elif confirmed_at: maturity = "CONFIRMED_SETUP"
    elif setup_at: maturity = "DEVELOPING_SETUP"
    else: maturity = "EARLY_CANDIDATE"
    relvol = number(result.get("relative_volume") or result.get("volume_ratio"))
    option = dict(result.get("option_context") or {})
    spread_pct = number(option.get("spread_percent"))
    lifecycle = {name: result.get(name) for name in (
        "first_candidate_detected_at", "setup_detected_at", "setup_confirmed_at", "broad_decided_at",
        "mirror_contract_selected_at", "mirror_opened_at", "filtered_evaluated_at", "filtered_opened_at")}
    lifecycle["authoritative_entered_at"] = authoritative_at
    ages = {
        "candidate_to_setup_seconds": _elapsed(first_seen, setup_at),
        "setup_to_authoritative_seconds": _elapsed(setup_at, authoritative_at),
        "authoritative_to_contract_seconds": _elapsed(authoritative_at, lifecycle["mirror_contract_selected_at"]),
        "authoritative_to_mirror_open_seconds": _elapsed(authoritative_at, lifecycle["mirror_opened_at"]),
        "authoritative_to_filtered_open_seconds": _elapsed(authoritative_at, lifecycle["filtered_opened_at"]),
        "total_candidate_to_execution_seconds": _elapsed(first_seen, lifecycle["filtered_opened_at"] or lifecycle["mirror_opened_at"]),
    }
    age_value = ages["setup_to_authoritative_seconds"] or _elapsed(first_seen, authoritative_at)
    alignment = "PASS" if spy_direction == qqq_direction == desired else "WARN" if "INSUFFICIENT_DATA" not in {spy_direction, qqq_direction} else "UNKNOWN"
    return {
        "schema_version": SCHEMA_VERSION, "opportunity_id": record.trade_id, "captured_at": at.isoformat(),
        "eastern_session": at.astimezone(EASTERN).date().isoformat(), "experiment_scope": experiment_scope(at),
        "market": {"market_regime": regime, "regime_confidence": "MEDIUM" if regime != "INSUFFICIENT_DATA" else "LOW",
            "spy_direction": spy_direction, "qqq_direction": qqq_direction, "spy_vs_vwap": raw_market.get("spy_vs_vwap"),
            "qqq_vs_vwap": raw_market.get("qqq_vs_vwap"), "spy_momentum": raw_market.get("spy_momentum"),
            "qqq_momentum": raw_market.get("qqq_momentum"), "breadth": raw_market.get("market_breadth"),
            "volatility_proxy": raw_market.get("vix"), "risk_classification": "RISK_ON" if regime == "RISK_ON_TREND" else "RISK_OFF" if regime == "RISK_OFF_TREND" else "UNKNOWN", "timestamp": at.isoformat()},
        "sector": {"sector": sector, "sector_etf": sector_etf, "stock_return": stock_return, "sector_return": sector_return,
            "spy_return": spy_return, "stock_vs_sector_relative_strength": stock_vs_sector,
            "stock_vs_spy_relative_strength": stock_vs_spy, "sector_vs_spy_relative_strength": sector_vs_spy,
            "sector_direction": sector_direction, "sector_alignment_with_trade": sector_direction == desired if sector_direction != "INSUFFICIENT_DATA" else None, "timestamp": at.isoformat()},
        "multi_timeframe": {"trends": trends, "number_of_timeframes_aligned_with_trade": aligned,
            "total_timeframes_available": len(available), "multi_timeframe_alignment_pct": aligned / len(available) * 100 if available else None},
        "relative_volume": {"value": relvol, "bucket": relative_volume_bucket(relvol)},
        "lifecycle": {**lifecycle, **ages, "signal_age_bucket": signal_age_bucket(age_value)},
        "signal_maturity": {"earliest_valid_state": maturity, "first_seen_timestamp": first_seen,
            "confirmed_timestamp": confirmed_at, "authoritative_timestamp": authoritative_at,
            "seconds_from_first_seen_to_authoritative": _elapsed(first_seen, authoritative_at)},
        "structure": {"classification": pullback_structure(result.get("price_structure") or {}, direction), **(result.get("price_structure") or {})},
        "catalyst": {"availability": "AVAILABLE" if result.get("catalyst_context") else "NOT_AVAILABLE", **(result.get("catalyst_context") or {})},
        "option_execution": {**option, "spread_bucket": spread_bucket(spread_pct), "dte_bucket": dte_bucket(option.get("dte"))},
        "checks": {"market_alignment": {"status": alignment, "values": {"spy_direction": spy_direction, "qqq_direction": qqq_direction}},
            "sector_alignment": {"status": "PASS" if sector_direction == desired else "WARN" if sector_direction != "INSUFFICIENT_DATA" else "UNKNOWN", "values": {"sector_direction": sector_direction}},
            "multi_timeframe_alignment": {"status": "PASS" if available and aligned == len(available) else "WARN" if available else "UNKNOWN", "values": {"aligned": aligned, "available": len(available)}},
            "relative_volume": {"status": "PASS" if relvol is not None and relvol >= 1 else "WARN" if relvol is not None else "UNKNOWN", "values": {"relative_volume": relvol}},
            "signal_age": {"status": "PASS" if age_value is not None and age_value <= 180 else "WARN" if age_value is not None else "UNKNOWN", "values": {"seconds": age_value}},
            "option_spread": {"status": "PASS" if spread_pct is not None and spread_pct <= 20 else "FAIL" if spread_pct is not None else "UNKNOWN", "values": {"spread_percent": spread_pct}},
            "catalyst": {"status": "UNKNOWN", "values": {"availability": "AVAILABLE" if result.get("catalyst_context") else "NOT_AVAILABLE"}}},
    }


FACTOR_PATHS = {
    "market_regime": ("market", "market_regime"), "sector_alignment": ("sector", "sector_alignment_with_trade"),
    "stock_vs_sector_relative_strength": ("sector", "stock_vs_sector_relative_strength"),
    "stock_vs_spy_relative_strength": ("sector", "stock_vs_spy_relative_strength"),
    "multi_timeframe_alignment_count": ("multi_timeframe", "number_of_timeframes_aligned_with_trade"),
    "relative_volume_bucket": ("relative_volume", "bucket"), "signal_age_bucket": ("lifecycle", "signal_age_bucket"),
    "signal_maturity": ("signal_maturity", "earliest_valid_state"), "pullback_reclaim": ("structure", "classification"),
    "spread_bucket": ("option_execution", "spread_bucket"), "dte_bucket": ("option_execution", "dte_bucket"),
    "catalyst_category": ("catalyst", "catalyst_type"),
}


def context_coverage(contexts):
    total = len(contexts)
    fields = {name: path for name, path in FACTOR_PATHS.items()}
    return [{"factor": name, "available": sum(_path(row, path) not in (None, "UNKNOWN", "NOT_AVAILABLE", "INSUFFICIENT_DATA") for row in contexts),
             "total": total, "coverage_pct": sum(_path(row, path) not in (None, "UNKNOWN", "NOT_AVAILABLE", "INSUFFICIENT_DATA") for row in contexts) / total * 100 if total else None}
            for name, path in fields.items()]


def attribution(contexts, outcomes, lanes, *, scope="ALL"):
    outcomes = {str(row.get("opportunity_id")): row for row in outcomes}
    lane_maps = {name: {str(row.get("opportunity_id")): row for row in rows} for name, rows in lanes.items()}
    selected = [row for row in contexts if scope == "ALL" or row.get("experiment_scope") == scope.replace(" ", "_")]
    report = []
    for factor, path in FACTOR_PATHS.items():
        groups = defaultdict(list)
        for row in selected: groups[str(_path(row, path) if _path(row, path) is not None else "UNKNOWN")].append(row)
        for value, rows in sorted(groups.items()):
            ids = [str(row["opportunity_id"]) for row in rows]
            auth = [outcomes[i] for i in ids if i in outcomes and number(outcomes[i].get("realized_return")) is not None]
            item = {"factor": factor, "value": value, "N": len(rows), **_returns(auth, "realized_return")}
            for lane in ("MIRROR", "BROAD", "FILTERED"):
                found = [lane_maps.get(lane, {}).get(i) for i in ids if lane_maps.get(lane, {}).get(i)]
                stats = _returns(found, "return_pct", "pnl")
                item.update({f"{lane.lower()}_participation": len(found) / len(rows) * 100 if rows else None,
                             f"{lane.lower()}_win_rate": stats["win_rate"], f"{lane.lower()}_avg_return": stats["avg_return"], f"{lane.lower()}_pnl": stats["pnl"]})
            mirror = lane_maps.get("MIRROR", {})
            item["auth_win_mirror_loss_rate"] = sum(number(outcomes.get(i, {}).get("realized_return")) > 0 and number(mirror.get(i, {}).get("pnl")) < 0 for i in ids if number(outcomes.get(i, {}).get("realized_return")) is not None and number(mirror.get(i, {}).get("pnl")) is not None) / len(auth) * 100 if auth else None
            item["governance"] = _governance(rows, contexts, outcomes)
            report.append(item)
    return {"scope": scope, "coverage": context_coverage(selected), "factors": report, "interactions": predeclared_interactions(selected, outcomes)}


def predeclared_interactions(contexts, outcomes):
    tests = {
        "high_relvol+sector_alignment": lambda c: number(_path(c, ("relative_volume", "value"))) is not None and _path(c, ("relative_volume", "value")) >= 1.5 and _path(c, ("sector", "sector_alignment_with_trade")) is True,
        "market+multi_timeframe_alignment": lambda c: _path(c, ("checks", "market_alignment", "status")) == "PASS" and _path(c, ("multi_timeframe", "multi_timeframe_alignment_pct")) == 100,
        "pullback_reclaim+high_relvol": lambda c: "RECLAIM" in str(_path(c, ("structure", "classification"))) and number(_path(c, ("relative_volume", "value"))) is not None and _path(c, ("relative_volume", "value")) >= 1.5,
        "sector_alignment+positive_relative_strength": lambda c: _path(c, ("sector", "sector_alignment_with_trade")) is True and number(_path(c, ("sector", "stock_vs_sector_relative_strength"))) is not None and _path(c, ("sector", "stock_vs_sector_relative_strength")) > 0,
    }
    outcome_map = outcomes if isinstance(outcomes, dict) else {str(row.get("opportunity_id")): row for row in outcomes}
    rows = []
    for name, predicate in tests.items():
        matched = [c for c in contexts if predicate(c)]
        stats = _returns([outcome_map[str(c["opportunity_id"])] for c in matched if str(c["opportunity_id"]) in outcome_map], "realized_return")
        rows.append({"interaction": name, "N": len(matched), **stats})
    return rows


def _governance(rows, all_contexts, outcomes):
    if len(rows) < 10: return "INSUFFICIENT DATA"
    values = {str(row["opportunity_id"]): number(outcomes.get(str(row["opportunity_id"]), {}).get("realized_return")) for row in all_contexts}
    dev = [values.get(str(r["opportunity_id"])) for r in rows if r.get("experiment_scope") == "DEVELOPMENT"]
    fwd = [values.get(str(r["opportunity_id"])) for r in rows if r.get("experiment_scope") == "FORWARD_TEST"]
    dev, fwd = [v for v in dev if v is not None], [v for v in fwd if v is not None]
    return "PROMISING" if len(dev) >= 10 and len(fwd) >= 10 and mean(dev) > 0 and mean(fwd) > 0 else "UNSTABLE"


def _returns(rows, return_key, pnl_key=None):
    returns = [number(row.get(return_key)) for row in rows]; returns = [v for v in returns if v is not None]
    pnl = [number(row.get(pnl_key)) for row in rows] if pnl_key else returns
    pnl = [v for v in pnl if v is not None]
    wins, losses = [v for v in pnl if v > 0], [v for v in pnl if v < 0]
    return {"win_rate": len(wins) / (len(wins) + len(losses)) * 100 if wins or losses else None,
            "avg_return": mean(returns) if returns else None, "pnl": sum(pnl) if pnl else None,
            "expectancy": mean(pnl) if pnl else None,
            "profit_factor": sum(wins) / abs(sum(losses)) if losses else math.inf if wins else None}


def _path(row, path):
    for key in path:
        if not isinstance(row, dict): return None
        row = row.get(key)
    return row


class OpportunityContextAnalyticsRepository:
    """Bounded explicit-column reads with exact opportunity joins and no writes."""
    def __init__(self, repository):
        self.repository = repository

    def load(self, *, scope="FORWARD TEST", limit=5000):
        contexts = self.repository.list_opportunity_contexts(limit=min(int(limit), 10000))
        if scope != "ALL":
            wanted = scope.replace(" ", "_")
            contexts = [row for row in contexts if row.get("experiment_scope") == wanted]
        ids = [str(row["opportunity_id"]) for row in contexts]
        if not ids:
            return attribution([], [], {}, scope=scope)
        placeholders = ",".join("?" for _ in ids)
        with self.repository.connection() as connection:
            outcomes = self.repository._fetchall(connection, f"""SELECT opportunity_id,
                realized_return,exit_reason,event_timestamp FROM authoritative_trade_events
                WHERE event_type='TRADE_CLOSED' AND opportunity_id IN ({placeholders})
                ORDER BY event_timestamp LIMIT ?""", (*ids, min(int(limit), 10000)))
            mirror = self.repository._fetchall(connection, f"""SELECT opportunity_id,
                realized_return_percent AS return_pct,realized_pnl AS pnl,opened_at,exit_quote_at AS closed_at
                FROM mirror_execution_trades WHERE opportunity_id IN ({placeholders})
                ORDER BY entry_event_at LIMIT ?""", (*ids, min(int(limit), 10000)))
            filtered = self.repository._fetchall(connection, f"""SELECT opportunity_id,
                realized_return_percent AS return_pct,realized_pnl AS pnl,opened_at,closed_at
                FROM filtered_execution_trades WHERE opportunity_id IN ({placeholders})
                ORDER BY authoritative_event_at LIMIT ?""", (*ids, min(int(limit), 10000)))
            broad = self.repository._fetchall(connection, f"""SELECT t.source_signal_id AS opportunity_id,
                t.realized_return_pct AS return_pct,t.realized_pnl_dollars AS pnl,t.opened_at,t.closed_at
                FROM paper_execution_trades t WHERE t.source_signal_id IN ({placeholders})
                AND EXISTS (SELECT 1 FROM paper_execution_journal j WHERE j.trade_id=t.trade_id
                    AND UPPER(COALESCE(j.metadata_json,'')) LIKE '%BROAD%')
                ORDER BY t.opened_at LIMIT ?""", (*ids, min(int(limit), 10000)))
        return attribution(contexts, outcomes, {"MIRROR": mirror, "BROAD": broad, "FILTERED": filtered}, scope=scope)
