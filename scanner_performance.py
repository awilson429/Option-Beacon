"""Context-local, structured scanner timing instrumentation."""

from __future__ import annotations

import contextvars
import math
import statistics
import time
from collections import defaultdict
from contextlib import contextmanager


FULL_SCAN_WARNING_MS = 300_000
MEDIAN_SYMBOL_WARNING_MS = 5_000
P90_SYMBOL_WARNING_MS = 10_000
RATE_LIMIT_WAIT_WARNING_MS = 30_000
FAILURE_PERCENT_WARNING = 10.0

_CURRENT_SYMBOL = contextvars.ContextVar("scanner_symbol_timing", default=None)
_CURRENT_RUN = contextvars.ContextVar("scanner_run_timing", default=None)


class SymbolTiming:
    def __init__(self, symbol, attempt_index, symbol_count, *, monotonic=time.perf_counter):
        self.symbol = str(symbol).upper()
        self.attempt_index = int(attempt_index)
        self.symbol_count = int(symbol_count)
        self.monotonic = monotonic
        self.started = monotonic()
        self.stages = defaultdict(float)
        self.providers = defaultdict(float)
        self.provider_calls = defaultdict(int)
        self.provider_status_counts = defaultdict(int)
        self.provider_outcomes = defaultdict(int)
        self.retry_count = 0
        self.rate_limit_count = 0
        self.timeout_count = 0
        self.retry_backoff_ms = 0.0
        self.intentional_throttle_ms = 0.0

    @contextmanager
    def measure(self, stage):
        started = self.monotonic()
        try:
            yield
        finally:
            self.stages[str(stage)] += (self.monotonic() - started) * 1000

    def provider_call(
        self, provider, operation, elapsed_ms, *, success, rate_limited=False,
        timeout=False, http_status=None,
    ):
        key = f"{provider}:{operation}"
        self.providers[key] += float(elapsed_ms)
        self.provider_calls[key] += 1
        self.provider_outcomes[f"{key}:{'success' if success else 'failure'}"] += 1
        if http_status is not None:
            self.provider_status_counts[f"{key}:{int(http_status)}"] += 1
        self.rate_limit_count += int(bool(rate_limited))
        self.timeout_count += int(bool(timeout))

    def retry_wait(self, duration_seconds, *, rate_limited=False):
        self.retry_count += 1
        self.retry_backoff_ms += float(duration_seconds) * 1000

    def throttle_wait(self, duration_seconds):
        self.intentional_throttle_ms += float(duration_seconds) * 1000

    def finish(self, *, success, exception_type=None, completed_wall_time=None):
        completed = self.monotonic()
        return {
            "symbol": self.symbol,
            "attempt_index": self.attempt_index,
            "symbol_count": self.symbol_count,
            "total_ms": round((completed - self.started) * 1000, 3),
            "success": bool(success),
            "exception_type": exception_type,
            "stages_ms": _rounded(self.stages),
            "provider_time_ms": _rounded(self.providers),
            "provider_calls": dict(sorted(self.provider_calls.items())),
            "provider_status_counts": dict(sorted(self.provider_status_counts.items())),
            "provider_outcomes": dict(sorted(self.provider_outcomes.items())),
            "retry_count": self.retry_count,
            "rate_limit_count": self.rate_limit_count,
            "timeout_count": self.timeout_count,
            "retry_backoff_ms": round(self.retry_backoff_ms, 3),
            "intentional_throttle_ms": round(self.intentional_throttle_ms, 3),
            "completed_wall_time": completed_wall_time,
        }


@contextmanager
def symbol_timing(symbol, attempt_index, symbol_count, *, monotonic=time.perf_counter):
    timing = SymbolTiming(symbol, attempt_index, symbol_count, monotonic=monotonic)
    token = _CURRENT_SYMBOL.set(timing)
    try:
        yield timing
    finally:
        _CURRENT_SYMBOL.reset(token)


@contextmanager
def measure_stage(stage):
    timing = _CURRENT_SYMBOL.get()
    if timing is None:
        yield
    else:
        with timing.measure(stage):
            yield


def record_provider_call(
    provider, operation, elapsed_ms, *, success, rate_limited=False, timeout=False,
    http_status=None,
):
    timing = _CURRENT_SYMBOL.get()
    if timing is None:
        timing = _CURRENT_RUN.get()
    if timing is not None:
        timing.provider_call(
            provider, operation, elapsed_ms, success=success,
            rate_limited=rate_limited, timeout=timeout, http_status=http_status,
        )


def record_retry_wait(duration_seconds, *, rate_limited=False):
    timing = _CURRENT_SYMBOL.get()
    if timing is None:
        timing = _CURRENT_RUN.get()
    if timing is not None:
        timing.retry_wait(duration_seconds, rate_limited=rate_limited)


def record_throttle_wait(duration_seconds):
    timing = _CURRENT_SYMBOL.get() or _CURRENT_RUN.get()
    if timing is not None:
        timing.throttle_wait(duration_seconds)


class RunTiming:
    def __init__(self, scanner_id, run_number, *, monotonic=time.perf_counter):
        self.scanner_id = scanner_id
        self.run_number = run_number
        self.monotonic = monotonic
        self.started = monotonic()
        self.phases = defaultdict(float)
        self.symbols = []
        self.providers = defaultdict(float)
        self.provider_calls = defaultdict(int)
        self.provider_status_counts = defaultdict(int)
        self.provider_outcomes = defaultdict(int)
        self.retry_count = 0
        self.rate_limit_count = 0
        self.timeout_count = 0
        self.retry_backoff_ms = 0.0
        self.intentional_throttle_ms = 0.0

    def provider_call(
        self, provider, operation, elapsed_ms, *, success, rate_limited=False,
        timeout=False, http_status=None,
    ):
        key = f"{provider}:{operation}"
        self.providers[key] += float(elapsed_ms)
        self.provider_calls[key] += 1
        self.provider_outcomes[f"{key}:{'success' if success else 'failure'}"] += 1
        if http_status is not None:
            self.provider_status_counts[f"{key}:{int(http_status)}"] += 1
        self.rate_limit_count += int(bool(rate_limited))
        self.timeout_count += int(bool(timeout))

    def retry_wait(self, duration_seconds, *, rate_limited=False):
        self.retry_count += 1
        self.retry_backoff_ms += float(duration_seconds) * 1000

    def throttle_wait(self, duration_seconds):
        self.intentional_throttle_ms += float(duration_seconds) * 1000

    @contextmanager
    def measure(self, phase):
        started = self.monotonic()
        try:
            yield
        finally:
            self.phases[str(phase)] += (self.monotonic() - started) * 1000

    def add_symbol(self, record):
        self.symbols.append(record)

    def summary(self, *, symbol_count, symbols_attempted, results, failures):
        total_ms = (self.monotonic() - self.started) * 1000
        durations = [record["total_ms"] for record in self.symbols]
        provider_time = defaultdict(float, self.providers)
        provider_calls = defaultdict(int, self.provider_calls)
        provider_status_counts = defaultdict(int, self.provider_status_counts)
        provider_outcomes = defaultdict(int, self.provider_outcomes)
        for record in self.symbols:
            for key, value in record["provider_time_ms"].items():
                provider_time[key] += value
            for key, value in record["provider_calls"].items():
                provider_calls[key] += value
            for key, value in record["provider_status_counts"].items():
                provider_status_counts[key] += value
            for key, value in record["provider_outcomes"].items():
                provider_outcomes[key] += value
        symbol_ms = self.phases.get("symbol_scan", sum(durations))
        pre_names = {
            "lock_acquisition", "market_data_cycle_start", "configuration_resolution",
            "configuration_persistence", "paper_state_restore", "universe_loading",
            "authoritative_open_trade_loading",
        }
        post_names = {
            "provider_summary", "snapshot_write", "paper_handoff_query",
            "paper_cycle", "health_completion", "lock_release",
        }
        persistence_stages = {
            "authoritative_persistence", "trade_plan_persistence",
            "legacy_outcome_persistence", "scanner_result_persistence",
        }
        per_symbol_persistence_ms = sum(
            record["stages_ms"].get(stage, 0.0)
            for record in self.symbols for stage in persistence_stages
        )
        persistence_ms = per_symbol_persistence_ms + sum(
            self.phases.get(name, 0.0) for name in {
                "snapshot_write", "paper_handoff_query", "paper_cycle",
                "health_completion", "scanner_health_progress",
            }
        )
        network_ms = sum(provider_time.values())
        retry_ms = self.retry_backoff_ms + sum(record["retry_backoff_ms"] for record in self.symbols)
        throttle_ms = self.intentional_throttle_ms + sum(record["intentional_throttle_ms"] for record in self.symbols)
        local_compute_ms = max(
            0.0, sum(durations) - network_ms - retry_ms - throttle_ms - per_symbol_persistence_ms
        )
        slowest = sorted(
            ({"symbol": row["symbol"], "total_ms": row["total_ms"]} for row in self.symbols),
            key=lambda row: (-row["total_ms"], row["symbol"]),
        )[:5]
        completed_times = [row["completed_wall_time"] for row in self.symbols if row.get("completed_wall_time")]
        started_times = [row["started_wall_time"] for row in self.symbols if row.get("started_wall_time")]
        rotation_skew_ms = (
            (max(completed_times) - min(started_times)).total_seconds() * 1000
            if completed_times and started_times else 0.0
        )
        first_started = min(started_times) if started_times else None
        cumulative_delay = sorted(
            (
                {
                    "symbol": row["symbol"],
                    "attempt_index": row["attempt_index"],
                    "cumulative_delay_ms": round(
                        (row["completed_wall_time"] - first_started).total_seconds() * 1000,
                        3,
                    ),
                }
                for row in self.symbols
                if first_started is not None and row.get("completed_wall_time")
            ),
            key=lambda row: (-row["cumulative_delay_ms"], row["symbol"]),
        )[:5]
        record = {
            "event": "scanner_performance_summary",
            "scanner_id": self.scanner_id,
            "run_number": self.run_number,
            "symbol_count": int(symbol_count),
            "symbols_attempted": int(symbols_attempted),
            "results": int(results),
            "failures": int(failures),
            "total_run_duration_ms": round(total_ms, 3),
            "symbol_processing_duration_ms": round(symbol_ms, 3),
            "pre_scan_duration_ms": round(sum(self.phases.get(name, 0.0) for name in pre_names), 3),
            "post_scan_duration_ms": round(sum(self.phases.get(name, 0.0) for name in post_names), 3),
            "avg_symbol_ms": round(statistics.fmean(durations), 3) if durations else None,
            "median_symbol_ms": round(statistics.median(durations), 3) if durations else None,
            "p90_symbol_ms": round(percentile(durations, 90), 3) if durations else None,
            "max_symbol_ms": round(max(durations), 3) if durations else None,
            "slowest_symbols": slowest,
            "provider_time_ms": _rounded(provider_time),
            "provider_calls": dict(sorted(provider_calls.items())),
            "provider_status_counts": dict(sorted(provider_status_counts.items())),
            "provider_outcomes": dict(sorted(provider_outcomes.items())),
            "retry_backoff_ms": round(retry_ms, 3),
            "intentional_throttle_ms": round(throttle_ms, 3),
            "persistence_ms": round(persistence_ms, 3),
            "local_compute_ms": round(local_compute_ms, 3),
            "rate_limit_count": self.rate_limit_count + sum(row["rate_limit_count"] for row in self.symbols),
            "retry_count": self.retry_count + sum(row["retry_count"] for row in self.symbols),
            "timeout_count": self.timeout_count + sum(row["timeout_count"] for row in self.symbols),
            "rotation_skew_ms": round(rotation_skew_ms, 3),
            "first_symbol_started_at": first_started.isoformat() if first_started else None,
            "last_symbol_completed_at": max(completed_times).isoformat() if completed_times else None,
            "first_symbols": [row["symbol"] for row in self.symbols[:5]],
            "last_symbols": [row["symbol"] for row in self.symbols[-5:]],
            "longest_cumulative_delay_symbols": cumulative_delay,
            "phases_ms": _rounded(self.phases),
        }
        return record


def performance_warnings(summary):
    checks = (
        (summary.get("total_run_duration_ms", 0) > FULL_SCAN_WARNING_MS, "FULL_SCAN_SLOW"),
        ((summary.get("median_symbol_ms") or 0) > MEDIAN_SYMBOL_WARNING_MS, "MEDIAN_SYMBOL_SLOW"),
        ((summary.get("p90_symbol_ms") or 0) > P90_SYMBOL_WARNING_MS, "P90_SYMBOL_SLOW"),
        (summary.get("retry_backoff_ms", 0) > RATE_LIMIT_WAIT_WARNING_MS, "RETRY_BACKOFF_HIGH"),
        ((summary.get("failures", 0) / max(1, summary.get("symbols_attempted", 0)) * 100) > FAILURE_PERCENT_WARNING, "FAILURE_RATE_HIGH"),
    )
    return [
        {"event": "scanner_performance_warning", "scanner_id": summary["scanner_id"],
         "run_number": summary["run_number"], "reason": reason}
        for triggered, reason in checks if triggered
    ]


def activate_run_timing(timing):
    return _CURRENT_RUN.set(timing)


def reset_run_timing(token):
    _CURRENT_RUN.reset(token)


def percentile(values, percent):
    """Return a deterministic nearest-rank percentile."""
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    rank = max(1, math.ceil(float(percent) / 100 * len(ordered)))
    return ordered[rank - 1]


def _rounded(values):
    return {key: round(value, 3) for key, value in sorted(values.items())}
