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
)
from optionbeacon_snapshot import save_latest_results
from optionbeacon.worker.logging_config import configure_worker_logging
from optionbeacon.worker.lock_lease import (
    DEFAULT_LOCK_RENEWAL_SECONDS,
    DEFAULT_LOCK_TTL_SECONDS,
    ScannerLockLease,
)
from execution_config import ExecutionConfig, execution_config_log_record
from paper_execution import (
    pending_authoritative_entries,
    refresh_paper_positions,
    run_paper_execution,
)
from paper_execution_repository import PaperExecutionRepository
from trade_repository import DEFAULT_SCANNER_ID, RepositoryUnavailable
from trade_state_service import (
    list_trade_outcomes,
    process_scanner_result,
    repository_for_runtime,
)
from scanner_performance import (
    RunTiming,
    activate_run_timing,
    performance_warnings,
    record_retry_wait,
    reset_run_timing,
    symbol_timing,
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
    run_number=None,
    paper_executor=run_paper_execution,
    lock_owner_id=None,
    lock_ttl_seconds=DEFAULT_LOCK_TTL_SECONDS,
    lock_renewal_seconds=DEFAULT_LOCK_RENEWAL_SECONDS,
    lease_factory=ScannerLockLease,
    monotonic=time.perf_counter,
) -> int:
    repository = repository or repository_for_runtime()
    scanner_id = scanner_id or os.getenv(
        "OPTIONBEACON_SCANNER_ID", DEFAULT_SCANNER_ID
    )
    performance = RunTiming(scanner_id, run_number, monotonic=monotonic)
    with performance.measure("configuration_resolution"):
        eod_exit_time = configured_eod_exit_time(eod_exit_time)
    LOGGER.info(json.dumps({
        "event": "scanner_lock_acquisition_attempt",
        "scanner_id": scanner_id,
        "requested_owner_id": lock_owner_id,
        "lease_duration_seconds": lock_ttl_seconds,
        "process_run_identifier": lock_owner_id,
    }, sort_keys=True))
    with performance.measure("lock_acquisition"):
        owner = repository.acquire_scan_lock(
            scanner_id, owner_id=lock_owner_id, ttl_seconds=lock_ttl_seconds
        )
    if owner is None:
        lock = repository.get_scan_lock(scanner_id) or {}
        LOGGER.warning(json.dumps({
            "event": "scanner_lock_contention",
            "scanner_id": scanner_id,
            "requested_owner_id": lock_owner_id,
            "lock_owner_id": lock.get("owner_id"),
            "persisted_owner_id": lock.get("owner_id"),
            "lock_acquired_at": lock.get("acquired_at"),
            "lock_expires_at": lock.get("expires_at"),
        }, sort_keys=True))
        return 2
    run_timing_token = activate_run_timing(performance)
    LOGGER.info(json.dumps({
        "event": "scanner_lock_acquired",
        "scanner_id": scanner_id,
        "requested_owner_id": owner,
        "persisted_owner_id": owner,
        "acquired_at": (repository.get_scan_lock(scanner_id) or {}).get("acquired_at"),
        "expires_at": (repository.get_scan_lock(scanner_id) or {}).get("expires_at"),
        "lease_duration_seconds": lock_ttl_seconds,
        "process_run_identifier": owner,
    }, sort_keys=True))
    lease = lease_factory(
        repository, scanner_id, owner,
        ttl_seconds=lock_ttl_seconds,
        renewal_seconds=lock_renewal_seconds,
        logger=LOGGER,
    ).start()
    started = clock()
    build = build_information(streamlit_version="not-applicable")
    repository.start_scan_run(
        scanner_id, run_number=run_number, owner_id=owner,
        started_at=started, code_version=build["commit"],
    )
    results = {}
    failures = 0
    symbols_attempted = 0
    symbol_count = 0
    failed_symbols = []
    provider_summary = None
    scan_phase_error = None
    stage = "market_data_cycle_start"
    LOGGER.info(
        json.dumps(
            {"event": "scan_started", "scanner_id": scanner_id},
            sort_keys=True,
        )
    )
    try:
        stage = "market_data_cycle_start"
        with performance.measure("market_data_cycle_start"):
            begin_market_data_scan_cycle()
        stage = "paper_repository_initialization"
        with performance.measure("configuration_resolution"):
            paper_repository = PaperExecutionRepository(repository)
            paper_config = ExecutionConfig.from_environment()
        config_record = execution_config_log_record(paper_config)
        config_record.update(scanner_id=scanner_id, run_number=run_number)
        LOGGER.info(json.dumps(config_record, sort_keys=True))
        stage = "paper_runtime_config_persistence"
        with performance.measure("configuration_persistence"):
            paper_repository.save_runtime_config(scanner_id, paper_config)
        stage = "paper_state_refresh"
        with performance.measure("paper_state_restore"):
            refreshed_paper_positions = refresh_paper_positions(
                config=paper_config,
                now=clock(),
                trade_ledger=paper_repository,
                position_store=paper_repository,
                journal=paper_repository,
                scanner_id=scanner_id,
                run_number=run_number,
            )
        LOGGER.info(json.dumps({
            "event": "paper_handoff_waiting_for_scan", "scanner_id": scanner_id,
            "run_number": run_number, "open_positions": len(refreshed_paper_positions),
        }, sort_keys=True))
        try:
            stage = "universe_loading"
            with performance.measure("universe_loading"):
                groups, source, universe_error = symbol_groups_loader()
            stage = "authoritative_open_trade_loading"
            with performance.measure("authoritative_open_trade_loading"):
                open_records = [
                    record
                    for record in list_trade_outcomes(repository)
                    if record.entry_time is not None and record.exit_time is None
                ]
            open_symbols = {record.symbol.upper() for record in open_records}
            eod_due_symbols = {
                record.symbol.upper()
                for record in open_records
                if intraday_trade_exit_due(record.entry_time, clock(), eod_exit_time)
            }
            symbols = list(
                dict.fromkeys([*flatten_symbol_groups(groups), *sorted(open_symbols)])
            )
            symbol_count = len(symbols)
            with performance.measure("scanner_health_progress"):
                repository.record_scan_progress(
                    scanner_id, run_number=run_number, owner_id=owner,
                    symbols_attempted=0, symbol_count=symbol_count,
                    results=0, failures=0, at=clock(),
                )
            LOGGER.info(json.dumps({
                "event": "scanner_universe_ready", "scanner_id": scanner_id,
                "run_number": run_number, "symbol_count": len(symbols), "source": source,
            }, sort_keys=True))
            if universe_error:
                LOGGER.warning("Scanner universe warning: %s", universe_error)
            stage = "symbol_scan"

            def log_scan_progress(symbol_index):
                if symbol_index % 10 == 0 or symbol_index == len(symbols):
                    with performance.measure("scanner_health_progress"):
                        repository.record_scan_progress(
                            scanner_id, run_number=run_number, owner_id=owner,
                            symbols_attempted=symbol_index,
                            symbol_count=len(symbols), results=len(results),
                            failures=failures, at=clock(),
                        )
                    LOGGER.info(json.dumps({
                        "event": "scanner_progress", "scanner_id": scanner_id,
                        "run_number": run_number, "symbols_attempted": symbol_index,
                        "symbol_count": len(symbols), "results": len(results),
                        "failures": failures,
                    }, sort_keys=True))

            with performance.measure("symbol_scan"):
                for symbol_index, symbol in enumerate(symbols, 1):
                    symbols_attempted = symbol_index
                    symbol_started_at = clock()
                    result = None
                    failure = None
                    with symbol_timing(
                        symbol, symbol_index, len(symbols), monotonic=monotonic
                    ) as timing:
                        attempts = EOD_QUOTE_ATTEMPTS if symbol in eod_due_symbols else 1
                        for attempt in range(attempts):
                            try:
                                result = signal_generator(symbol)
                                price = float((result or {}).get("price"))
                                if price > 0:
                                    failure = None
                                    break
                                failure = ValueError("latest quote was unavailable")
                            except Exception as exc:
                                failure = exc
                            if attempt < attempts - 1:
                                delay = EOD_QUOTE_BACKOFF_SECONDS[attempt]
                                LOGGER.warning(
                                    "EOD quote unavailable; retrying: %s",
                                    json.dumps({
                                        "symbol": symbol, "attempt": attempt + 1,
                                        "delay_seconds": delay,
                                    }, sort_keys=True),
                                )
                                record_retry_wait(delay)
                                sleep(delay)
                        if failure is not None:
                            failures += 1
                            failed_symbols.append(symbol)
                            if symbol in eod_due_symbols:
                                LOGGER.error("EOD exit quote unavailable: %s", json.dumps({
                                    "event": "eod_exit_quote_unavailable", "symbol": symbol,
                                    "error": type(failure).__name__, "eod_exit_pending": True,
                                }, sort_keys=True))
                        if result is not None:
                            results[symbol] = result
                            lease.ensure_owned()
                            with timing.measure("authoritative_persistence"):
                                process_scanner_result(
                                    repository, result, source_version=build["commit"],
                                    current_timestamp=clock(), eod_exit_time=eod_exit_time,
                                )
                        symbol_completed_at = clock()
                        symbol_record = timing.finish(
                            success=result is not None and failure is None,
                            exception_type=type(failure).__name__ if failure else None,
                            completed_wall_time=symbol_completed_at,
                        )
                        symbol_record["started_wall_time"] = symbol_started_at
                    performance.add_symbol(symbol_record)
                    LOGGER.info(json.dumps({
                        "event": "scanner_symbol_timing",
                        "scanner_id": scanner_id,
                        "run_number": run_number,
                        "symbol_started_at": symbol_started_at.isoformat(),
                        "symbol_completed_at": symbol_completed_at.isoformat(),
                        **{key: value for key, value in symbol_record.items()
                           if key not in {"completed_wall_time", "started_wall_time"}},
                    }, sort_keys=True))
                    log_scan_progress(symbol_index)
            stage = "provider_summary"
            with performance.measure("provider_summary"):
                provider_summary = end_market_data_scan_cycle()
            if failed_symbols or provider_summary["rate_limited_symbols"]:
                LOGGER.warning(json.dumps({
                    "event": "provider_warning_summary",
                    "provider": provider_summary["provider"],
                    "failed_symbols": sorted(set(failed_symbols)),
                    "rate_limited_symbols": provider_summary["rate_limited_symbols"],
                    "request_count": provider_summary["requests"],
                    "cache_hits": provider_summary["cache_hits"],
                }, sort_keys=True))
            stage = "snapshot_write"
            with performance.measure("snapshot_write"):
                snapshot_writer(results)
        except Exception as exc:
            scan_phase_error = exc
            LOGGER.exception(json.dumps({
                "event": "scanner_phase_failed", "scanner_id": scanner_id,
                "run_number": run_number, "stage": stage,
                "error": type(exc).__name__, "paper_handoff_will_run": True,
            }, sort_keys=True))
        finally:
            if provider_summary is None:
                try:
                    with performance.measure("provider_summary"):
                        provider_summary = end_market_data_scan_cycle()
                except Exception as exc:
                    if scan_phase_error is None:
                        scan_phase_error = exc
                    LOGGER.exception(json.dumps({
                        "event": "provider_summary_failed", "scanner_id": scanner_id,
                        "run_number": run_number, "error": type(exc).__name__,
                        "paper_handoff_will_run": True,
                    }, sort_keys=True))

        stage = "authoritative_entry_query"
        lease.ensure_owned()
        with performance.measure("paper_handoff_query"):
            paper_candidates = pending_authoritative_entries(
                repository, results, paper_repository
            )
            authoritative_entries_generated = len([
                event for event in repository.list_trade_events(limit=5000)
                if event.get("event_type") == "TRADE_ENTERED"
                and event.get("event_timestamp") >= started.isoformat()
            ])
        LOGGER.info(json.dumps({
            "event": "paper_authoritative_handoff", "scanner_id": scanner_id,
            "run_number": run_number,
            "authoritative_entries_generated": authoritative_entries_generated,
            "paper_candidates_received": len(paper_candidates),
            "candidate_ids": [
                item.get("_authoritative_entry_id") for item in paper_candidates[:20]
            ],
            "candidate_ids_truncated": max(0, len(paper_candidates) - 20),
        }, sort_keys=True))
        stage = "paper_execution"
        lease.ensure_owned()
        with performance.measure("paper_cycle"):
            paper_executor(
                paper_candidates,
                config=paper_config,
                now=clock(),
                market_open=True,
                trade_ledger=paper_repository,
                position_store=paper_repository,
                journal=paper_repository,
                scanner_id=scanner_id,
                run_number=run_number,
                refreshed_positions=refreshed_paper_positions,
            )
        if scan_phase_error is not None:
            completed = clock()
            with performance.measure("health_completion"):
                repository.finish_scan_run(
                    scanner_id, run_number=run_number, owner_id=owner,
                    completed_at=completed, symbols_attempted=symbols_attempted,
                    symbol_count=symbol_count, results=len(results), failures=failures,
                    scan_duration=(completed - started).total_seconds(),
                    code_version=build["commit"], market_data_state="ERROR",
                    error_message=f"{type(scan_phase_error).__name__}: scanner phase failed",
                )
            return 1
        completed = clock()
        lease.ensure_owned()
        with performance.measure("health_completion"):
            repository.finish_scan_run(
                scanner_id, run_number=run_number, owner_id=owner,
                completed_at=completed, symbols_attempted=symbols_attempted,
                symbol_count=symbol_count, results=len(results), failures=failures,
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
        if stage in {
            "paper_repository_initialization", "paper_runtime_config_persistence",
            "paper_state_refresh",
            "authoritative_entry_query", "paper_execution",
        }:
            LOGGER.exception(json.dumps({
                "event": "paper_cycle_failed", "scanner_id": scanner_id,
                "run_number": run_number, "stage": stage,
                "error": type(exc).__name__,
            }, sort_keys=True))
        else:
            LOGGER.exception(json.dumps({
                "event": "scanner_cycle_failed", "scanner_id": scanner_id,
                "run_number": run_number, "stage": stage,
                "error": type(exc).__name__,
            }, sort_keys=True))
        completed = clock()
        with performance.measure("health_completion"):
            repository.finish_scan_run(
                scanner_id, run_number=run_number, owner_id=owner,
                completed_at=completed, symbols_attempted=symbols_attempted,
                symbol_count=symbol_count, results=len(results), failures=failures,
                scan_duration=(completed - started).total_seconds(),
                code_version=build["commit"], market_data_state="ERROR",
                error_message=f"{type(exc).__name__}: scanner failed",
            )
        return 1
    finally:
        lease.stop()
        if provider_summary is None:
            try:
                end_market_data_scan_cycle()
            except Exception as exc:
                LOGGER.exception(json.dumps({
                    "event": "provider_cleanup_failed", "scanner_id": scanner_id,
                    "run_number": run_number, "error": type(exc).__name__,
                }, sort_keys=True))
        with performance.measure("lock_release"):
            try:
                current = repository.get_scan_lock(scanner_id) or {}
                LOGGER.info(json.dumps({
                    "event": "scanner_lock_release_attempt",
                    "scanner_id": scanner_id,
                    "requested_owner_id": owner,
                    "persisted_owner_id": current.get("owner_id"),
                    "expires_at": current.get("expires_at"),
                    "process_run_identifier": owner,
                }, sort_keys=True))
                released = repository.release_scan_lock(scanner_id, owner)
                LOGGER.info(json.dumps({
                    "event": "scanner_lock_released" if released else "scanner_lock_release_rejected",
                    "scanner_id": scanner_id,
                    "requested_owner_id": owner,
                    "persisted_owner_id": current.get("owner_id"),
                    "reason": "exact_owner" if released else "owner_mismatch_or_missing",
                }, sort_keys=True))
            except RepositoryUnavailable as exc:
                LOGGER.error(json.dumps({
                    "event": "scanner_lock_release_failed",
                    "scanner_id": scanner_id,
                    "owner_id": owner,
                    "error": type(exc).__name__,
                    "stale_recovery": "lease_expiry",
                }, sort_keys=True))
        summary = performance.summary(
            symbol_count=symbol_count, symbols_attempted=symbols_attempted,
            results=len(results), failures=failures,
        )
        LOGGER.info(json.dumps(summary, sort_keys=True))
        for warning in performance_warnings(summary):
            LOGGER.warning(json.dumps(warning, sort_keys=True))
        reset_run_timing(run_timing_token)


def main() -> int:
    configure_worker_logging()
    try:
        return run_scan_once()
    except RepositoryUnavailable as exc:
        LOGGER.exception("Scanner repository initialization failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
