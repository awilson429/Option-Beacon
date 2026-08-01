"""Descriptive intelligence analytics joined from snapshots and outcomes."""

from __future__ import annotations

import math
from collections import defaultdict
from statistics import mean


DEFAULT_MINIMUM_SAMPLE_SIZE = 20


def analyze_intelligence_records(snapshots, outcomes, *, group_by="setup_type", minimum_sample_size=DEFAULT_MINIMUM_SAMPLE_SIZE):
    snapshot_map = {item["opportunity_id"]: item for item in snapshots}
    groups, exclusions = defaultdict(list), defaultdict(int)
    for outcome in outcomes:
        snapshot = snapshot_map.get(outcome.get("opportunity_id"))
        if snapshot is None: exclusions["missing_snapshot"] += 1; continue
        value = _number(outcome.get("realized_return"))
        if not outcome.get("exit_timestamp") or value is None or outcome.get("never_entered"):
            exclusions["incomplete_or_ineligible_outcome"] += 1; continue
        key = _group_value(snapshot, outcome, group_by)
        groups[str(key if key is not None else "UNKNOWN")].append((value, outcome))
    results = [_summarize(name, rows, minimum_sample_size) for name, rows in sorted(groups.items())]
    return {"group_by": group_by, "minimum_sample_size": minimum_sample_size, "groups": results, "exclusions": dict(exclusions), "methodology": "IN_SAMPLE_DESCRIPTIVE"}


def _summarize(name, rows, minimum):
    returns = [row[0] for row in rows]; wins = [x for x in returns if x > 0]; losses = [x for x in returns if x < 0]
    pf = sum(wins) / abs(sum(losses)) if losses else math.inf if wins else None
    outcome_rows = [row[1] for row in rows]
    return {"group": name, "sample_size": len(rows), "sufficient_sample": len(rows) >= minimum,
            "uncertainty": "SUFFICIENT_DESCRIPTIVE_SAMPLE" if len(rows) >= minimum else "INSUFFICIENT_SAMPLE",
            "wins": len(wins), "losses": len(losses), "win_rate": len(wins)/(len(wins)+len(losses))*100 if wins or losses else None,
            "average_winner": mean(wins) if wins else None, "average_loser": mean(losses) if losses else None,
            "average_realized_return": mean(returns), "expectancy": mean(returns), "profit_factor": pf,
            "average_mfe": _average(row.get("maximum_favorable_excursion") for row in outcome_rows),
            "average_mae": _average(row.get("maximum_adverse_excursion") for row in outcome_rows),
            "average_hold_minutes": _average(row.get("duration_minutes") for row in outcome_rows)}


def _group_value(snapshot, outcome, group):
    if group in snapshot: return snapshot[group]
    if group == "market_regime": return (snapshot.get("market_regime") or {}).get("regime")
    if group == "sector_rank": return (snapshot.get("sector_context") or {}).get("sector_rank")
    if group == "sector_alignment": return (snapshot.get("sector_context") or {}).get("alignment_status")
    if group == "time_of_day": return snapshot.get("session_segment")
    if group == "day_of_week": return str(snapshot.get("eastern_trading_date"))
    if group == "exit_reason": return outcome.get("exit_reason")
    if group in {"score_bucket", "confidence_bucket"}: return _bucket((snapshot.get("scoring") or {}).get("confidence"), (0, 65, 70, 80, 90, 101))
    if group == "volume_bucket": return _bucket((snapshot.get("features") or {}).get("relative_volume"), (0, 1, 1.5, 2, math.inf))
    if group == "rsi_bucket": return _bucket((snapshot.get("features") or {}).get("rsi"), (0, 30, 50, 70, 101))
    if group == "risk_reward_bucket": return _bucket((snapshot.get("features") or {}).get("risk_reward"), (0, 1, 2, 3, math.inf))
    return "UNKNOWN"


def _bucket(value, edges):
    number = _number(value)
    if number is None: return "UNKNOWN"
    for low, high in zip(edges, edges[1:]):
        if low <= number < high: return f"{low:g}-{high:g}"
    return "UNKNOWN"


def _number(value):
    try: number = float(value)
    except (TypeError, ValueError): return None
    return number if math.isfinite(number) else None


def _average(values):
    values = [number for value in values if (number := _number(value)) is not None]
    return mean(values) if values else None
