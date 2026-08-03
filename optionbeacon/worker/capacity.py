"""Scanner capacity measurements and evidence-based summaries."""

from __future__ import annotations

import math
import os
from collections import defaultdict
from statistics import mean


BENCHMARK_LIMIT_ENV = "OPTIONBEACON_BENCHMARK_SYMBOL_LIMIT"
MIN_RECOMMENDATION_SCANS = 10


def percentile(values, percentile_value):
    values = sorted(float(value) for value in values)
    if not values:
        return 0.0
    rank = (len(values) - 1) * float(percentile_value) / 100
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return values[low]
    return values[low] + (values[high] - values[low]) * (rank - low)


def utilization_percent(duration_seconds, interval_seconds):
    if not interval_seconds or interval_seconds <= 0:
        return 0.0
    return float(duration_seconds) / float(interval_seconds) * 100


def capacity_health(utilization, *, overlap=False, rate_limit_count=0,
                    failed_symbols=0, attempted_symbols=0, partial_scan=False):
    failure_rate = failed_symbols / attempted_symbols if attempted_symbols else 0
    provider_degraded = rate_limit_count > 0 or partial_scan or failure_rate >= 0.1
    if overlap or utilization >= 100 or (provider_degraded and failure_rate >= 0.5):
        return "OVERLOADED"
    if utilization >= 75 or (provider_degraded and failure_rate >= 0.2):
        return "SATURATED"
    if utilization >= 50 or provider_degraded:
        return "CAUTION"
    return "HEALTHY"


def deterministic_symbol_subset(symbols, value=None):
    raw = os.getenv(BENCHMARK_LIMIT_ENV, "") if value is None else value
    if raw in (None, ""):
        return list(symbols), None
    try:
        limit = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{BENCHMARK_LIMIT_ENV} must be a positive integer") from exc
    if limit <= 0:
        raise ValueError(f"{BENCHMARK_LIMIT_ENV} must be a positive integer")
    return list(symbols)[:limit], limit


def aggregate_symbol_timings(timings):
    durations = [float(item.get("duration_seconds", 0)) for item in timings]
    return {
        "avg_symbol_seconds": mean(durations) if durations else 0.0,
        "p50_symbol_seconds": percentile(durations, 50),
        "p95_symbol_seconds": percentile(durations, 95),
        "max_symbol_seconds": max(durations, default=0.0),
        "repository_write_seconds": sum(
            float(item.get("repository_seconds", 0)) for item in timings
        ),
    }


def opportunity_density(visible_opportunities, successful_symbols):
    return (float(visible_opportunities) / successful_symbols) if successful_symbols else 0.0


def schedule_delay_seconds(intended_start, actual_start):
    if intended_start is None:
        return 0.0
    return max(0.0, (actual_start - intended_start).total_seconds())


def summarize_capacity(records, *, minimum_scans=MIN_RECOMMENDATION_SCANS):
    groups = defaultdict(list)
    for row in records:
        groups[int(row["configured_symbols"])].append(row)
    comparisons = []
    for size, rows in sorted(groups.items()):
        durations = [float(row["scan_duration_seconds"]) for row in rows]
        attempted = sum(int(row.get("attempted_symbols") or 0) for row in rows)
        successes = sum(int(row.get("successful_symbols") or 0) for row in rows)
        requests = sum(int(row.get("request_count") or 0) for row in rows)
        rate_limits = sum(int(row.get("rate_limit_count") or 0) for row in rows)
        opportunities = sum(int(row.get("opportunities_generated") or 0) for row in rows)
        comparison = {
            "universe_size": size,
            "scans_observed": len(rows),
            "avg_duration_seconds": mean(durations),
            "p95_duration_seconds": percentile(durations, 95),
            "avg_utilization_percent": mean(float(row["utilization_percent"]) for row in rows),
            "success_rate_percent": successes / attempted * 100 if attempted else 0.0,
            "rate_limit_percent": rate_limits / requests * 100 if requests else 0.0,
            "avg_retries": mean(float(row.get("retry_count") or 0) for row in rows),
            "overlap_count": sum(bool(row.get("overlap_detected")) for row in rows),
            "opportunity_density": opportunity_density(opportunities, successes),
        }
        comparison["capacity_health"] = capacity_health(
            comparison["avg_utilization_percent"],
            overlap=comparison["overlap_count"] > 0,
            rate_limit_count=rate_limits,
            failed_symbols=max(0, attempted - successes),
            attempted_symbols=attempted,
        )
        comparisons.append(comparison)
    eligible = [row for row in comparisons if row["scans_observed"] >= minimum_scans]
    acceptable = [
        row for row in eligible
        if row["p95_duration_seconds"] < 60
        and row["success_rate_percent"] >= 90
        and row["capacity_health"] in {"HEALTHY", "CAUTION"}
    ]
    return {
        "scans_observed": len(records),
        "universe_comparison": comparisons,
        "recommended_max_symbols": max((row["universe_size"] for row in acceptable), default=None),
        "minimum_scans_required": minimum_scans,
        "insufficient_data": not eligible,
    }


def verbose_capacity_diagnostics_enabled(value=None):
    raw = os.getenv("OPTIONBEACON_VERBOSE_CAPACITY_DIAGNOSTICS", "false") if value is None else value
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}
