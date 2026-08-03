"""Run one locked, idempotent OptionBeacon scan."""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

from build_information import build_information
from finnhub_universe import active_symbol_groups, flatten_symbol_groups
from intraday_session import configured_eod_exit_time, intraday_trade_exit_due
from optionbeacon_live import (
    begin_market_data_scan_cycle,
    end_market_data_scan_cycle,
    generate_signal,
    consume_signal_timing,
)
from optionbeacon_snapshot import save_latest_results
from optionbeacon.worker.logging_config import configure_worker_logging
from optionbeacon.worker.capacity import (
    aggregate_symbol_timings,
    capacity_health,
    deterministic_symbol_subset,
    opportunity_density,
    schedule_delay_seconds,
    utilization_percent,
    verbose_capacity_diagnostics_enabled,
)
from trade_repository import DEFAULT_SCANNER_ID, RepositoryUnavailable
from trade_state_service import (
    list_trade_outcomes,
    process_scanner_result,
    repository_for_runtime,
)


LOGGER = logging.getLogger(__name__)
EOD_QUOTE_ATTEMPTS = 3
EOD_QUOTE_BACKOFF_SECONDS = (1, 2)


def environment_symbol_groups():
    """Load the CLI universe without consulting Streamlit secrets."""
    return active_symbol_groups(api_key=os.getenv("FINNHUB_API_KEY", "").strip())


def run_scan_once(
    *,
    repository=None,
    signal_generator=generate_signal,
    symbol_groups_loader=environment_symbol_groups,
    snapshot_writer=save_latest_results,
    scanner_id=None,
    eod_exit_time=None,
    sleep=time.sleep,
    clock=lambda: datetime.now(timezone.utc),
    perf_counter=time.perf_counter,
    scanner_interval_seconds=None,
    intended_start=None,
) -> int:
    repository = repository or repository_for_runtime()
    scanner_id = scanner_id or os.getenv(
        "OPTIONBEACON_SCANNER_ID", DEFAULT_SCANNER_ID
    )
    eod_exit_time = configured_eod_exit_time(eod_exit_time)
    scanner_interval_seconds = float(
        scanner_interval_seconds or os.getenv("OPTIONBEACON_SCAN_SECONDS", "300")
    )
    actual_invocation = clock()
    owner = repository.acquire_scan_lock(scanner_id)
    if owner is None:
        LOGGER.warning("Scanner invocation skipped because another scan owns the lock")
        repository.record_capacity_metrics({
            "scanner_id": scanner_id, "scan_started_at": actual_invocation,
            "scan_completed_at": actual_invocation,
            "scanner_interval_seconds": scanner_interval_seconds,
            "configured_symbols": 0, "attempted_symbols": 0,
            "successful_symbols": 0, "failed_symbols": 0, "skipped_symbols": 0,
            "rate_limit_count": 0, "provider_warning_count": 0, "retry_count": 0,
            "request_count": 0, "cache_hit_count": 0, "scan_duration_seconds": 0,
            "avg_symbol_seconds": 0, "p50_symbol_seconds": 0,
            "p95_symbol_seconds": 0, "max_symbol_seconds": 0,
            "repository_write_seconds": 0, "opportunities_generated": 0,
            "actionable_opportunities": 0, "watch_count": 0, "wait_count": 0,
            "open_count": 0, "top_ranked_count": 0, "opportunity_density": 0,
            "partial_scan": 1, "scan_status": "SKIPPED_OVERLAP",
            "utilization_percent": 0, "capacity_health": "OVERLOADED",
            "overlap_detected": 1, "overlap_count": 1,
            "schedule_delay_seconds": schedule_delay_seconds(intended_start, actual_invocation),
            "intended_scan_start": intended_start,
            "metadata_json": {"reason": "scan_lock_held"},
        })
        return 2
    started = clock()
    build = build_information(streamlit_version="not-applicable")
    repository.record_scan_heartbeat(
        scanner_id,
        started_at=started,
        code_version=build["commit"],
        market_data_state="SCANNING",
    )
    results = {}
    failures = 0
    failed_symbols = []
    provider_summary = None
    symbol_timings = []
    available_symbol_count = 0
    begin_market_data_scan_cycle()
    LOGGER.info(
        json.dumps(
            {"event": "scan_started", "scanner_id": scanner_id},
            sort_keys=True,
        )
    )
    try:
        groups, source, universe_error = symbol_groups_loader()
        open_records = [
            record
            for record in list_trade_outcomes(repository)
            if record.entry_time is not None and record.exit_time is None
        ]
        open_symbols = {
            record.symbol.upper()
            for record in open_records
        }
        eod_due_symbols = {
            record.symbol.upper()
            for record in open_records
            if intraday_trade_exit_due(
                record.entry_time,
                clock(),
                eod_exit_time,
            )
        }
        symbols = list(
            dict.fromkeys([*flatten_symbol_groups(groups), *sorted(open_symbols)])
        )
        available_symbol_count = len(symbols)
        symbols, benchmark_limit = deterministic_symbol_subset(symbols)
        LOGGER.info(json.dumps({
            "event": "scanner_benchmark_universe",
            "benchmark_limit": benchmark_limit,
            "symbols": symbols,
        }, sort_keys=True))
        if universe_error:
            LOGGER.warning("Scanner universe warning: %s", universe_error)
        for symbol in symbols:
            symbol_started_at = clock()
            symbol_started = perf_counter()
            repository_seconds = 0.0
            phase_timing = {}
            result = None
            failure = None
            attempts = (
                EOD_QUOTE_ATTEMPTS
                if symbol in eod_due_symbols
                else 1
            )
            for attempt in range(attempts):
                try:
                    result = signal_generator(symbol)
                    phase_timing = consume_signal_timing(symbol)
                    price = float((result or {}).get("price"))
                    if price > 0:
                        failure = None
                        break
                    failure = ValueError("latest quote was unavailable")
                except Exception as exc:
                    phase_timing = consume_signal_timing(symbol)
                    failure = exc
                if attempt < attempts - 1:
                    delay = EOD_QUOTE_BACKOFF_SECONDS[attempt]
                    LOGGER.warning(
                        "EOD quote unavailable; retrying: %s",
                        json.dumps(
                            {
                                "symbol": symbol,
                                "attempt": attempt + 1,
                                "delay_seconds": delay,
                            },
                            sort_keys=True,
                        ),
                    )
                    sleep(delay)
            if failure is not None:
                failures += 1
                failed_symbols.append(symbol)
                if symbol in eod_due_symbols:
                    LOGGER.error(
                        "EOD exit quote unavailable: %s",
                        json.dumps(
                            {
                                "event": "eod_exit_quote_unavailable",
                                "symbol": symbol,
                                "error": type(failure).__name__,
                                "eod_exit_pending": True,
                            },
                            sort_keys=True,
                        ),
                    )
                if result is None:
                    duration = perf_counter() - symbol_started
                    symbol_timings.append({
                        "symbol": symbol, "started_at": symbol_started_at.isoformat(),
                        "ended_at": clock().isoformat(), "duration_seconds": duration,
                        "market_data_seconds": phase_timing.get("market_data_seconds", duration),
                        "analysis_seconds": phase_timing.get("analysis_seconds", 0),
                        "repository_seconds": 0,
                        "result": "rate_limited" if "rate limit" in str(failure).lower() else "provider_failure",
                    })
                    continue
            if result is None:
                duration = perf_counter() - symbol_started
                symbol_timings.append({
                    "symbol": symbol, "started_at": symbol_started_at.isoformat(),
                    "ended_at": clock().isoformat(), "duration_seconds": duration,
                    "market_data_seconds": phase_timing.get("market_data_seconds", duration),
                    "analysis_seconds": phase_timing.get("analysis_seconds", 0),
                    "repository_seconds": 0, "result": "insufficient_data",
                })
                continue
            results[symbol] = result
            repository_started = perf_counter()
            process_scanner_result(
                repository,
                result,
                source_version=build["commit"],
                current_timestamp=clock(),
                eod_exit_time=eod_exit_time,
            )
            repository_seconds = perf_counter() - repository_started
            duration = perf_counter() - symbol_started
            signal = str(result.get("signal") or result.get("status") or "").upper()
            symbol_timings.append({
                "symbol": symbol, "started_at": symbol_started_at.isoformat(),
                "ended_at": clock().isoformat(), "duration_seconds": duration,
                "market_data_seconds": phase_timing.get("market_data_seconds", max(0.0, duration - repository_seconds)),
                "analysis_seconds": phase_timing.get("analysis_seconds", 0), "repository_seconds": repository_seconds,
                "result": "actionable" if signal not in {"WAIT", "WATCH", "WATCHLIST", "MARKET CLOSED / WAIT"} else "opportunity_created",
            })
        provider_summary = end_market_data_scan_cycle()
        if failed_symbols or provider_summary["rate_limited_symbols"]:
            LOGGER.warning(
                json.dumps(
                    {
                        "event": "provider_warning_summary",
                        "provider": provider_summary["provider"],
                        "failed_symbols": sorted(set(failed_symbols)),
                        "rate_limited_symbols": provider_summary[
                            "rate_limited_symbols"
                        ],
                        "request_count": provider_summary["requests"],
                        "cache_hits": provider_summary["cache_hits"],
                    },
                    sort_keys=True,
                )
            )
        snapshot_writer(results)
        completed = clock()
        duration_seconds = (completed - started).total_seconds()
        timing_summary = aggregate_symbol_timings(symbol_timings)
        signals = [str(item.get("signal") or item.get("status") or "").upper() for item in results.values()]
        watch_count = sum(value in {"WATCH", "WATCHLIST"} for value in signals)
        wait_count = sum("WAIT" in value for value in signals)
        open_count = sum(value == "OPEN" for value in signals)
        actionable = len(signals) - watch_count - wait_count
        partial_scan = bool(failures or provider_summary["rate_limited_symbols"])
        utilization = utilization_percent(duration_seconds, scanner_interval_seconds)
        health = capacity_health(
            utilization, rate_limit_count=provider_summary.get("rate_limit_count", 0),
            failed_symbols=failures, attempted_symbols=len(symbols), partial_scan=partial_scan,
        )
        metadata = {
            "universe_source": source, "available_symbols": available_symbol_count,
            "benchmark_limit": benchmark_limit, "included_symbols": symbols,
            "failed_symbols": failed_symbols,
        }
        if verbose_capacity_diagnostics_enabled():
            metadata["symbol_timings"] = symbol_timings
        metrics = {
            "scanner_id": scanner_id, "scan_started_at": started, "scan_completed_at": completed,
            "scanner_interval_seconds": scanner_interval_seconds,
            "configured_symbols": len(symbols), "attempted_symbols": len(symbol_timings),
            "successful_symbols": len(results), "failed_symbols": failures,
            "skipped_symbols": max(0, available_symbol_count - len(symbols)),
            "rate_limit_count": provider_summary.get("rate_limit_count", 0),
            "provider_warning_count": int(bool(failed_symbols or provider_summary["rate_limited_symbols"] or universe_error)),
            "retry_count": provider_summary.get("retries", 0),
            "request_count": provider_summary["requests"], "cache_hit_count": provider_summary["cache_hits"],
            "scan_duration_seconds": duration_seconds, **timing_summary,
            "opportunities_generated": len(results), "actionable_opportunities": actionable,
            "watch_count": watch_count, "wait_count": wait_count, "open_count": open_count,
            "top_ranked_count": 0, "opportunity_density": opportunity_density(len(results), len(results)),
            "partial_scan": int(partial_scan), "scan_status": "PARTIAL" if partial_scan else "SUCCESS",
            "utilization_percent": utilization, "capacity_health": health,
            "overlap_detected": 0, "overlap_count": 0,
            "schedule_delay_seconds": schedule_delay_seconds(intended_start, started),
            "intended_scan_start": intended_start, "metadata_json": metadata,
        }
        repository.record_capacity_metrics(metrics)
        LOGGER.info(json.dumps({
            "event": "scanner_capacity_summary", "scanner_id": scanner_id,
            "configured_symbols": len(symbols), "successful_symbols": len(results),
            "failed_symbols": failures, "duration_seconds": duration_seconds,
            "utilization_percent": utilization,
            "rate_limit_count": metrics["rate_limit_count"], "retries": metrics["retry_count"],
            "opportunity_count": len(results), "capacity_health": health,
        }, sort_keys=True))
        repository.record_scan_heartbeat(
            scanner_id,
            completed_at=completed,
            success_at=completed,
            symbols_processed=len(results),
            scan_duration=(completed - started).total_seconds(),
            code_version=build["commit"],
            market_data_state=(
                "AVAILABLE"
                if results and failures == 0
                else "PARTIAL"
                if results
                else "UNAVAILABLE"
            ),
        )
        return 0 if results else 1
    except Exception as exc:
        LOGGER.exception("Fatal scanner failure")
        completed = clock()
        if provider_summary is None:
            provider_summary = end_market_data_scan_cycle()
        duration_seconds = (completed - started).total_seconds()
        timing_summary = aggregate_symbol_timings(symbol_timings)
        utilization = utilization_percent(duration_seconds, scanner_interval_seconds)
        failure_health = "OVERLOADED"
        try:
            repository.record_capacity_metrics({
                "scanner_id": scanner_id, "scan_started_at": started,
                "scan_completed_at": completed,
                "scanner_interval_seconds": scanner_interval_seconds,
                "configured_symbols": available_symbol_count,
                "attempted_symbols": len(symbol_timings),
                "successful_symbols": len(results), "failed_symbols": max(1, failures),
                "skipped_symbols": max(0, available_symbol_count - len(symbol_timings)),
                "rate_limit_count": provider_summary.get("rate_limit_count", 0),
                "provider_warning_count": 1, "retry_count": provider_summary.get("retries", 0),
                "request_count": provider_summary.get("requests", 0),
                "cache_hit_count": provider_summary.get("cache_hits", 0),
                "scan_duration_seconds": duration_seconds, **timing_summary,
                "opportunities_generated": len(results), "actionable_opportunities": 0,
                "watch_count": 0, "wait_count": 0, "open_count": 0,
                "top_ranked_count": 0,
                "opportunity_density": opportunity_density(len(results), len(results)),
                "partial_scan": 1, "scan_status": "FAILURE",
                "utilization_percent": utilization,
                "capacity_health": failure_health,
                "overlap_detected": 0, "overlap_count": 0,
                "schedule_delay_seconds": schedule_delay_seconds(intended_start, started),
                "intended_scan_start": intended_start,
                "metadata_json": {"error_type": type(exc).__name__},
            })
        except Exception:
            LOGGER.exception("Could not persist failed scan capacity metrics")
        LOGGER.info(json.dumps({
            "event": "scanner_capacity_summary", "scanner_id": scanner_id,
            "configured_symbols": available_symbol_count,
            "successful_symbols": len(results), "failed_symbols": max(1, failures),
            "duration_seconds": duration_seconds,
            "utilization_percent": utilization,
            "rate_limit_count": provider_summary.get("rate_limit_count", 0),
            "retries": provider_summary.get("retries", 0),
            "opportunity_count": len(results), "capacity_health": failure_health,
        }, sort_keys=True))
        repository.record_scan_error(
            f"{type(exc).__name__}: scanner failed",
            scanner_id,
            code_version=build["commit"],
        )
        return 1
    finally:
        if provider_summary is None:
            end_market_data_scan_cycle()
        repository.release_scan_lock(scanner_id, owner)


def main() -> int:
    configure_worker_logging()
    try:
        return run_scan_once()
    except RepositoryUnavailable as exc:
        LOGGER.exception("Scanner repository initialization failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
