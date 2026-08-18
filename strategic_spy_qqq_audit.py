"""Pure strategic comparison of broad-universe and dedicated SPY/QQQ ledgers.

The builder performs no I/O.  It reports unavailable evidence as unavailable and
never reconstructs trades, quotes, or context with provider calls.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import mean, median, pstdev
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")
PREVIOUS_AUDIT_CUTOFF = "2026-08-14T04:00:00+00:00"  # end of 2026-08-13 ET
SYSTEMS = ("BROAD", "MIRROR", "FILTERED", "SPY", "QQQ", "SPY_QQQ")


def number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def timestamp(value):
    if not value:
        return None
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def session(value):
    parsed = timestamp(value)
    return parsed.astimezone(EASTERN).date().isoformat() if parsed else None


def percentile(values, fraction):
    values = sorted(values)
    if not values:
        return None
    index = (len(values) - 1) * fraction
    low, high = math.floor(index), math.ceil(index)
    return values[low] if low == high else values[low] + (values[high] - values[low]) * (index - low)


def _streak(values, wanted):
    best = current = 0
    for value in values:
        current = current + 1 if wanted(value) else 0
        best = max(best, current)
    return best


def _drawdown(pnls):
    equity = peak = 0.0
    peak_index = trough_index = 0
    worst = worst_pct = 0.0
    recovery = 0
    underwater_since = None
    for index, pnl in enumerate(pnls):
        equity += pnl
        if equity >= peak:
            if underwater_since is not None:
                recovery = max(recovery, index - underwater_since)
                underwater_since = None
            peak, peak_index = equity, index
        else:
            underwater_since = index if underwater_since is None else underwater_since
            drawdown = peak - equity
            if drawdown > worst:
                worst, trough_index = drawdown, index
                worst_pct = drawdown / peak * 100 if peak > 0 else None
    return {"maximum_realized_drawdown": worst, "maximum_percentage_drawdown": worst_pct,
            "longest_recovery_period_trades": recovery, "peak_index": peak_index, "trough_index": trough_index}


def performance(rows):
    closed = [row for row in rows if row.get("closed_at") and number(row.get("pnl")) is not None]
    pnls = [number(row["pnl"]) for row in closed]
    returns = [number(row.get("return_pct")) for row in closed]
    returns = [value for value in returns if value is not None]
    wins, losses = [value for value in pnls if value > 0], [value for value in pnls if value < 0]
    chronological = sorted(closed, key=lambda row: timestamp(row.get("closed_at")) or datetime.min.replace(tzinfo=timezone.utc))
    ordered_pnl = [number(row["pnl"]) for row in chronological]
    by_day = defaultdict(float)
    for row in chronological:
        by_day[row.get("session") or session(row.get("closed_at"))] += number(row["pnl"])
    daily = [by_day[key] for key in sorted(key for key in by_day if key)]
    debit = [number(row.get("debit")) for row in rows if number(row.get("debit")) is not None]
    gross_profit, gross_loss = sum(wins), abs(sum(losses))
    avg_win, avg_loss = (mean(wins) if wins else None), (mean(losses) if losses else None)
    return {
        "total_records": len(rows), "opened_trades": sum(bool(row.get("opened_at")) for row in rows),
        "closed_trades": len(closed), "open_trades": sum(bool(row.get("opened_at")) and not row.get("closed_at") for row in rows),
        "wins": len(wins), "losses": len(losses), "win_rate": len(wins) / len(closed) * 100 if closed else None,
        "total_pnl": sum(pnls) if pnls else None, "average_pnl": mean(pnls) if pnls else None,
        "median_pnl": median(pnls) if pnls else None, "average_return": mean(returns) if returns else None,
        "median_return": median(returns) if returns else None, "expectancy_per_trade": mean(pnls) if pnls else None,
        "average_winner": avg_win, "average_loser": avg_loss,
        "payoff_ratio": avg_win / abs(avg_loss) if avg_win is not None and avg_loss else None,
        "profit_factor": gross_profit / gross_loss if gross_loss else None,
        "profit_factor_note": "NO LOSING TRADES" if gross_profit and not gross_loss else None,
        "max_observed_winner": max(pnls) if pnls else None, "max_observed_loser": min(pnls) if pnls else None,
        "profitable_session_percentage": sum(value > 0 for value in daily) / len(daily) * 100 if daily else None,
        "losing_session_percentage": sum(value < 0 for value in daily) / len(daily) * 100 if daily else None,
        "average_daily_pnl": mean(daily) if daily else None, "median_daily_pnl": median(daily) if daily else None,
        "daily_pnl_standard_deviation": pstdev(daily) if len(daily) > 1 else None,
        "best_day": max(daily) if daily else None, "worst_day": min(daily) if daily else None,
        "longest_winning_day_streak": _streak(daily, lambda value: value > 0),
        "longest_losing_day_streak": _streak(daily, lambda value: value < 0),
        "maximum_consecutive_losses": _streak(ordered_pnl, lambda value: value < 0),
        "worst_5_trade_sequence": min((sum(ordered_pnl[i:i+5]) for i in range(len(ordered_pnl)-4)), default=None),
        "worst_10_trade_sequence": min((sum(ordered_pnl[i:i+10]) for i in range(len(ordered_pnl)-9)), default=None),
        "cumulative_debit": sum(debit) if debit else None,
        "pnl_per_dollar_deployed": sum(pnls) / sum(debit) if pnls and debit and sum(debit) else None,
        **_drawdown(ordered_pnl), "daily": [{"session": key, "pnl": by_day[key]} for key in sorted(key for key in by_day if key)],
        "rolling": {str(size): _rolling(chronological, size) for size in (5, 10, 20)},
    }


def _rolling(rows, size):
    results = []
    for end in range(size, len(rows) + 1):
        values = [number(row["pnl"]) for row in rows[end-size:end]]
        wins, losses = [v for v in values if v > 0], [v for v in values if v < 0]
        results.append({"ending_at": rows[end-1].get("closed_at"), "n": size, "expectancy": mean(values),
                        "win_rate": len(wins) / size * 100,
                        "profit_factor": sum(wins) / abs(sum(losses)) if losses else None,
                        "profit_factor_note": "NO LOSING TRADES" if wins and not losses else None})
    return results


def execution(rows):
    spreads = [number(row.get("spread_percent")) for row in rows]
    spreads = [value for value in spreads if value is not None]
    ages = [number(row.get("signal_age_seconds")) for row in rows]
    ages = [value for value in ages if value is not None]
    return {"spread_coverage": len(spreads), "average_spread_percent": mean(spreads) if spreads else None,
            "median_spread_percent": median(spreads) if spreads else None, "p90_spread_percent": percentile(spreads, .9),
            "signal_age_coverage": len(ages), "average_signal_age_seconds": mean(ages) if ages else None,
            "median_signal_age_seconds": median(ages) if ages else None,
            "missing_quotes": sum(row.get("opened_at") and number(row.get("entry_fill")) is None for row in rows),
            "dte": _distribution(rows, "dte"), "option_volume": _summary_values(rows, "option_volume"),
            "open_interest": _summary_values(rows, "open_interest"),
            "quote_age": "NOT PERSISTED", "execution_latency": "AVAILABLE ONLY WHERE SIGNAL AND OPEN TIMESTAMPS EXIST",
            "fill_assumption": sorted({str(row.get("fill_model")) for row in rows if row.get("fill_model")})}


def excursions(rows):
    closed = [row for row in rows if row.get("closed_at") and number(row.get("return_pct")) is not None]
    mfe = [number(row.get("mfe")) for row in closed if number(row.get("mfe")) is not None]
    mae = [number(row.get("mae")) for row in closed if number(row.get("mae")) is not None]
    conversions = [number(row.get("return_pct")) / number(row.get("mfe")) * 100 for row in closed
                   if number(row.get("mfe")) and number(row.get("mfe")) > 0]
    losers = [row for row in closed if number(row.get("pnl")) < 0]
    return {"coverage": len(mfe), "average_mfe": mean(mfe) if mfe else None, "median_mfe": median(mfe) if mfe else None,
            "average_mae": mean(mae) if mae else None, "median_mae": median(mae) if mae else None,
            "average_mfe_captured_percent": mean(conversions) if conversions else None,
            "profitable_before_loss": {str(level): {"n": sum((number(row.get("mfe")) or -math.inf) >= level for row in losers),
                "loser_percent": sum((number(row.get("mfe")) or -math.inf) >= level for row in losers) / len(losers) * 100 if losers else None}
                for level in (5, 10, 15, 20, 30)},
            "winner_giveback_over_25pct_of_mfe": _giveback_count(closed, .25),
            "winner_giveback_over_50pct_of_mfe": _giveback_count(closed, .50)}


def _giveback_count(rows, fraction):
    return sum(bool(number(row.get("pnl")) is not None and number(row.get("pnl")) > 0 and
               number(row.get("mfe")) is not None and number(row.get("mfe")) > 0 and
               number(row.get("return_pct")) is not None and
               number(row.get("mfe")) - number(row.get("return_pct")) > number(row.get("mfe")) * fraction)
               for row in rows)


def _distribution(rows, key):
    counts = Counter(str(row.get(key) if row.get(key) is not None else "DATA UNAVAILABLE") for row in rows)
    return [{"value": key, "n": count} for key, count in sorted(counts.items())]


def _summary_values(rows, key):
    values = [number(row.get(key)) for row in rows]
    values = [value for value in values if value is not None]
    return {"coverage": len(values), "average": mean(values) if values else None, "median": median(values) if values else None}


def grouped(rows, key):
    groups = defaultdict(list)
    for row in rows:
        groups[str(row.get(key) or "DATA UNAVAILABLE")].append(row)
    return [{"group": label, **performance(items), "excursions": excursions(items)} for label, items in sorted(groups.items())]


def _inventory(rows, timestamp_keys=("signal_at", "opened_at", "closed_at", "observed_at")):
    times = [timestamp(row.get(key)) for row in rows for key in timestamp_keys if row.get(key)]
    sessions = {row.get("session") or session(next((row.get(key) for key in timestamp_keys if row.get(key)), None)) for row in rows}
    return {"first_timestamp": min(times).isoformat() if times else None, "latest_timestamp": max(times).isoformat() if times else None,
            "sessions": len(sessions - {None}), "records": len(rows), "opened_trades": sum(bool(row.get("opened_at")) for row in rows),
            "closed_trades": sum(bool(row.get("closed_at")) for row in rows),
            "open_trades": sum(bool(row.get("opened_at")) and not row.get("closed_at") for row in rows),
            "new_records_since_previous_audit": sum(any(timestamp(row.get(key)) and timestamp(row.get(key)).isoformat() >= PREVIOUS_AUDIT_CUTOFF for key in timestamp_keys) for row in rows)}


def _quality(rows, *, trade_lane=True):
    ids = [str(row.get("trade_id") or row.get("opportunity_id")) for row in rows if row.get("trade_id") or row.get("opportunity_id")]
    duplicates = sum(count - 1 for count in Counter(ids).values() if count > 1)
    missing_entries = sum(bool(row.get("opened_at")) and number(row.get("entry_fill")) is None for row in rows)
    stale = sum(bool(row.get("opened_at")) and not row.get("closed_at") for row in rows)
    closed = sum(bool(row.get("closed_at")) for row in rows)
    issues = duplicates + missing_entries
    grade = "INSUFFICIENT" if not rows or (trade_lane and closed < 5) else "POOR" if issues > len(rows) * .2 else "USABLE WITH LIMITATIONS" if issues or stale else "GOOD"
    return {"grade": grade, "duplicate_identities": duplicates, "missing_entries": missing_entries,
            "missing_exits_or_stale_open": stale, "closed_with_missing_outcome": sum(bool(row.get("closed_at")) and number(row.get("pnl")) is None for row in rows),
            "missing_spread": sum(bool(row.get("opened_at")) and number(row.get("spread_percent")) is None for row in rows),
            "missing_signal_age": sum(bool(row.get("opened_at")) and number(row.get("signal_age_seconds")) is None for row in rows)}


def _score(metrics, quality, dimension):
    if quality["grade"] == "INSUFFICIENT" or metrics["closed_trades"] < 5:
        return "INSUFFICIENT DATA"
    if dimension == "current_expectancy": return "STRONG" if (metrics["expectancy_per_trade"] or 0) > 0 else "WEAK"
    if dimension == "consistency": return "STRONG" if (metrics["profitable_session_percentage"] or 0) >= 60 else "MODERATE" if (metrics["profitable_session_percentage"] or 0) >= 45 else "WEAK"
    if dimension == "drawdown": return "MODERATE" if metrics["maximum_realized_drawdown"] is not None else "INSUFFICIENT DATA"
    return "MODERATE"


def build_strategic_audit(snapshot):
    """Build complete audit from normalized, actual persisted observations."""
    lanes = {name: list(snapshot.get("lanes", {}).get(name, ())) for name in SYSTEMS}
    lanes["SPY_QQQ"] = lanes["SPY"] + lanes["QQQ"]
    inventories = {name: _inventory(rows) for name, rows in lanes.items()}
    extra = {name: _inventory(list(snapshot.get(name, ())), trade_lane_keys) for name, trade_lane_keys in (
        ("AUTHORITATIVE", ("signal_at", "closed_at")), ("OPPORTUNITY_CONTEXT", ("captured_at",)),
        ("CONTEXT_SHADOW", ("evaluated_at",)), ("POSITION_CONTEXT", ("observed_at",)),
        ("DAILY_SCORECARD_ANALYTICS", ("signal_at", "opened_at", "closed_at")))}
    inventories.update(extra)
    quality = {name: _quality(rows) for name, rows in lanes.items()}
    for name in ("AUTHORITATIVE", "OPPORTUNITY_CONTEXT", "CONTEXT_SHADOW", "POSITION_CONTEXT", "DAILY_SCORECARD_ANALYTICS"):
        quality[name] = _quality(list(snapshot.get(name, ())), trade_lane=name == "DAILY_SCORECARD_ANALYTICS")
    source_records = snapshot.get("underlying_records", {})
    opportunity_n = len(source_records.get("opportunities", ()))
    outcome_n = len(source_records.get("intelligence_outcome_labels", ()))
    event_n = len(source_records.get("authoritative", ()))
    quality["AUTHORITATIVE"].update({"opportunities": opportunity_n, "outcome_labels": outcome_n,
        "authoritative_trade_events": event_n, "missing_outcomes": max(0, opportunity_n - outcome_n),
        "outcome_coverage_percent": outcome_n / opportunity_n * 100 if opportunity_n else None,
        "grade": "INSUFFICIENT" if not event_n or outcome_n < 5 else quality["AUTHORITATIVE"]["grade"]})
    metrics = {name: performance(rows) for name, rows in lanes.items()}
    execution_results = {name: execution(rows) for name, rows in lanes.items()}
    excursion_results = {name: excursions(rows) for name, rows in lanes.items()}
    breakdowns = {name: {"direction": grouped(rows, "direction"), "time_of_day": grouped(rows, "time_bucket"),
                          "setup": grouped(rows, "setup"), "regime": grouped(rows, "regime"),
                          "signal_age": grouped(rows, "signal_age_bucket")} for name, rows in lanes.items()}
    spy_qqq = lanes["SPY_QQQ"]
    translation = Counter(row.get("translation_class") or "DATA UNAVAILABLE" for row in spy_qqq)
    scorecard = []
    dimensions = ("current_expectancy", "consistency", "drawdown", "execution_quality", "liquidity", "signal_frequency",
                  "sample_efficiency", "underlying_directional_accuracy", "option_translation_efficiency", "exit_efficiency",
                  "operational_complexity", "data_completeness")
    for name in ("BROAD", "SPY", "QQQ", "SPY_QQQ"):
        scorecard.append({"system": name, **{dimension: _score(metrics[name], quality[name], dimension) for dimension in dimensions}})
    sufficient = {name: metrics[name]["closed_trades"] >= 30 for name in ("BROAD", "SPY", "QQQ", "SPY_QQQ")}
    positive = {name: sufficient[name] and (metrics[name]["expectancy_per_trade"] or 0) > 0 for name in sufficient}
    if not any(sufficient.values()): recommendation = "NOT ENOUGH EVIDENCE"
    else:
        eligible = [name for name in sufficient if positive[name]]
        recommendation = max(eligible, key=lambda name: metrics[name]["expectancy_per_trade"], default="NOT ENOUGH EVIDENCE")
    leak = "INSUFFICIENT DATA"
    if excursion_results["SPY_QQQ"]["coverage"] >= 10 and excursion_results["SPY_QQQ"]["profitable_before_loss"]["10"]["n"]:
        leak = "EXIT MANAGEMENT"
    elif execution_results["SPY_QQQ"]["spread_coverage"] >= 10 and (execution_results["SPY_QQQ"]["median_spread_percent"] or 0) > 20:
        leak = "SPREAD / EXECUTION"
    return {
        "audit_metadata": {**snapshot.get("metadata", {}), "source_of_truth": "PERSISTED RECORDS ONLY",
                           "read_only": True, "provider_calls": 0, "database_writes": 0,
                           "previous_audit_cutoff": PREVIOUS_AUDIT_CUTOFF,
                           "audit_date_range": {"first": min((item["first_timestamp"] for item in inventories.values() if item["first_timestamp"]), default=None),
                                                "latest": max((item["latest_timestamp"] for item in inventories.values() if item["latest_timestamp"]), default=None)}},
        "inventory": inventories, "data_quality": quality, "performance": metrics,
        "consistency_and_risk": metrics, "execution": execution_results, "mfe_mae_exit": excursion_results,
        "breakdowns": breakdowns, "underlying_vs_option_translation": {"SPY_QQQ": dict(translation),
            "note": "Classes are reported only when persisted underlying outcome evidence exists."},
        "signal_frequency_and_sample_efficiency": _frequency(lanes),
        "complexity": snapshot.get("complexity", {}), "context_coverage": snapshot.get("context_coverage", {}),
        "shadow_exit_experiments": snapshot.get("shadow_exit_experiments", []),
        "strategic_scorecard": scorecard,
        "verdict": {"positive_expectancy_evidence": positive, "biggest_observed_leak": leak,
                    "architecture_recommendation": recommendation,
                    "forced_choice_today": recommendation if recommendation != "NOT ENOUGH EVIDENCE" else "HYBRID DATA COLLECTION; evidence is not mature enough to retire either architecture"},
        "next_experiment": {"name": "SPY/QQQ-only forward experiment", "hypothesis": "Actual dedicated SPY/QQQ trades produce more consistent net expectancy than BROAD.",
            "predeclared_rule": "Run the existing SPY/QQQ lane unchanged and compare every closed trade with unchanged BROAD; no hindsight exclusions.",
            "baseline": "BROAD", "experimental_lane": "existing SPY/QQQ intraday strategy", "minimum_sample": "50 closed SPY/QQQ trades and 20 sessions",
            "success_metric": "positive expectancy, profit factor >1, and >=50% profitable sessions, all forward-only",
            "failure_criterion": "non-positive expectancy or profit factor <=1 after the minimum sample"},
        "limitations": snapshot.get("limitations", []), "underlying_records": snapshot.get("underlying_records", {}),
    }


def _frequency(lanes):
    result = {}
    for name, rows in lanes.items():
        sessions = sorted({row.get("session") for row in rows if row.get("session")})
        opened = sum(bool(row.get("opened_at")) for row in rows)
        rate = opened / len(sessions) if sessions else None
        result[name] = {"sessions": len(sessions), "signals_per_session": len(rows) / len(sessions) if sessions else None,
                        "trades_per_session": rate, "no_trade_sessions": "UNAVAILABLE WITHOUT COMPLETE SESSION CALENDAR",
                        "estimated_sessions_for_samples": {str(n): math.ceil(n / rate) if rate else None for n in (50, 100, 250, 500)}}
    return result
