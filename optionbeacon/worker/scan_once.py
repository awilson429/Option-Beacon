"""Run one locked, idempotent OptionBeacon scan."""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

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
from authoritative_entry_funnel import AuthoritativeEntryFunnelRepository
from paper_execution import (
    pending_authoritative_entries,
    refresh_paper_positions,
    run_paper_execution,
)
from paper_execution_repository import PaperExecutionRepository
from capital_readiness import lane_configs
from capital_repository import CapitalRepository
from mirror_execution import (
    MirrorExecutionRepository,
    mirror_enabled,
    mirror_experiment_start,
    pending_mirror_entries,
    run_mirror_execution,
)
from mirror_v2_shadow import (
    CachedChainProvider,
    MirrorV2Repository,
    mirror_v2_enabled,
    mirror_v2_experiment_start,
    run_mirror_v2_shadow,
)
from filtered_execution import FilteredExecutionRepository, filtered_enabled, run_filtered_execution
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
from decision_provenance import (
    SUPPORTED_PROVENANCE_SYMBOLS,
    build_observation,
    scan_cycle_identity,
)


LOGGER = logging.getLogger(__name__)
EOD_QUOTE_ATTEMPTS = 3
EOD_QUOTE_BACKOFF_SECONDS = (1, 2)


def _safe_funnel_error_message(exc):
    message = str(exc or "").splitlines()[0][:160]
    lowered = message.lower()
    if any(value in lowered for value in ("postgres://", "postgresql://", "token", "password", "secret")):
        return "Authoritative funnel diagnostic stage failed; sensitive detail redacted."
    return message or "Authoritative funnel diagnostic stage failed."


def _mark_provenance_failure(repository, scan_cycle_id, *, stage, exc, symbol=None):
    LOGGER.error(json.dumps({
        "event": "decision_provenance_persistence_failed",
        "scan_cycle_id": scan_cycle_id, "stage": stage, "symbol": symbol,
        "exception_type": type(exc).__name__,
    }, sort_keys=True))
    try:
        repository.mark_provenance_degraded(
            scan_cycle_id, f"{stage}: {type(exc).__name__}"
        )
    except Exception:
        LOGGER.exception("Could not mark decision provenance degraded")


def _finish_provenance_cycle(repository, scan_cycle_id, *, completed_at,
                             cycle_status, provider_state, symbols_evaluated,
                             data_freshness, failure_reason=None):
    try:
        return repository.finish_provenance_cycle(
            scan_cycle_id, completed_at=completed_at, cycle_status=cycle_status,
            provider_state=provider_state, symbols_evaluated=symbols_evaluated,
            data_freshness=data_freshness, failure_reason=failure_reason,
        )
    except Exception as exc:
        _mark_provenance_failure(
            repository, scan_cycle_id, stage="cycle_completion", exc=exc
        )
        return None


def record_authoritative_entry_funnel(
    *, repository, scanner_id, run_number, started_at, completed_at,
    symbols, monotonic=time.perf_counter, candidate_records=None,
):
    """Attempt exactly one failure-isolated snapshot for one scanner-cycle identity."""
    attempt_started = monotonic()
    stage = "initialization"
    LOGGER.info(json.dumps({
        "event": "authoritative_entry_funnel_started",
        "scanner_id": scanner_id, "run_number": run_number,
        "symbol_count": len(symbols), "symbols_attempted": len(symbols),
        "timestamp": completed_at.isoformat(),
    }, sort_keys=True))
    try:
        diagnostics = AuthoritativeEntryFunnelRepository(repository)
        stage = "authoritative_entry_query"
        entered_events = repository.list_trade_event_summaries(
            limit=500, event_type="TRADE_ENTERED",
            start_at=started_at, end_at=completed_at,
        )
        stage = "persistence"
        record = diagnostics.save_cycle(
            scanner_id=scanner_id, run_number=run_number,
            started_at=started_at, completed_at=completed_at,
            symbols=symbols, entered_events=entered_events,
            candidate_records=(candidate_records if candidate_records is not None
                               else list_trade_outcomes(repository)),
        )
        LOGGER.info(json.dumps({
            "event": "authoritative_entry_funnel_completed",
            "scanner_id": scanner_id, "run_number": run_number,
            "scanned": record["scanned"],
            "valid_results": record["valid_results"],
            "directional": record["directional_candidates"],
            "confidence_qualified": record["confidence_qualified"],
            "visible_setup_qualified": record["visible_setup_qualified"],
            "ready_armed": record["armed"],
            "trigger_reached": record["trigger_reached"],
            "trade_entered": record["trade_entered"],
            "not_entered": record["not_entered"],
            "blocker_count": sum(record["blockers"].values()),
            "duration_ms": round((monotonic() - attempt_started) * 1000, 3),
        }, sort_keys=True))
        return True
    except Exception as exc:
        LOGGER.error(json.dumps({
            "event": "authoritative_entry_funnel_failed",
            "scanner_id": scanner_id, "run_number": run_number,
            "stage": stage, "exception_type": type(exc).__name__,
            "message": _safe_funnel_error_message(exc),
            "duration_ms": round((monotonic() - attempt_started) * 1000, 3),
        }, sort_keys=True))
        return False


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
    provenance_cycle_id = scan_cycle_identity(
        scanner_id=scanner_id, run_number=run_number, started_at=started
    )
    provenance_symbols = set()
    try:
        repository.start_provenance_cycle(
            scan_cycle_id=provenance_cycle_id, scanner_id=scanner_id,
            run_number=run_number, started_at=started,
            session_state="WORKER_ACTIVE", worker_source="optionbeacon.worker.scan_once",
            source_version=build["commit"],
        )
    except Exception as exc:
        _mark_provenance_failure(
            repository, provenance_cycle_id, stage="cycle_start", exc=exc
        )
    results = {}
    failures = 0
    symbols_attempted = 0
    symbol_count = 0
    failed_symbols = []
    funnel_symbols = []
    provider_summary = None
    cycle_outcomes = None
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
            capital_repository = CapitalRepository(repository, configs=lane_configs())
            mirror_repository = MirrorExecutionRepository(repository)
            mirror_is_enabled = mirror_enabled()
            mirror_v2_repository = MirrorV2Repository(repository)
            mirror_v2_is_enabled = mirror_v2_enabled()
            filtered_repository = FilteredExecutionRepository(repository)
            filtered_is_enabled = filtered_enabled()
            mirror_v2_start_date = mirror_v2_experiment_start()
            if mirror_v2_is_enabled and mirror_v2_start_date is None:
                prior_v2_state = mirror_v2_repository.runtime_state()
                try:
                    mirror_v2_start_date = datetime.fromisoformat(
                        str((prior_v2_state or {}).get("experiment_start_date"))
                    ).date()
                except (TypeError, ValueError):
                    mirror_v2_start_date = clock().astimezone(ZoneInfo("America/New_York")).date()
            mirror_start_date = mirror_experiment_start()
            if mirror_is_enabled and mirror_start_date is None:
                prior_mirror_state = mirror_repository.runtime_state()
                prior_start = (prior_mirror_state or {}).get("experiment_start_date")
                try:
                    mirror_start_date = datetime.fromisoformat(str(prior_start)).date()
                except (TypeError, ValueError):
                    mirror_start_date = clock().astimezone(ZoneInfo("America/New_York")).date()
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
                cycle_outcomes = list_trade_outcomes(repository, active_only=True)
                open_records = [
                    record
                    for record in cycle_outcomes
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
                        provenance_observation_id = None
                        if str(symbol).upper() in SUPPORTED_PROVENANCE_SYMBOLS:
                            provenance_symbols.add(str(symbol).upper())
                            try:
                                observation = build_observation(
                                    scan_cycle_id=provenance_cycle_id,
                                    symbol=symbol, observed_at=clock(), result=result,
                                    failure=failure, source_version=build["commit"],
                                )
                                stored_observation = repository.record_provenance_observation(
                                    observation
                                )
                                provenance_observation_id = stored_observation["observation_id"]
                            except Exception as exc:
                                _mark_provenance_failure(
                                    repository, provenance_cycle_id,
                                    stage="observation_write", exc=exc, symbol=symbol,
                                )
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
                                    scanner_id=scanner_id, run_number=run_number,
                                    outcome_records=cycle_outcomes,
                                    provenance_observation_id=provenance_observation_id,
                                    provenance_scan_cycle_id=provenance_cycle_id,
                                )
                        symbol_completed_at = clock()
                        symbol_record = timing.finish(
                            success=result is not None and failure is None,
                            exception_type=type(failure).__name__ if failure else None,
                            completed_wall_time=symbol_completed_at,
                        )
                        symbol_record["started_wall_time"] = symbol_started_at
                    performance.add_symbol(symbol_record)
                    funnel_symbols.append((symbol, result))
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

        stage = "authoritative_entry_funnel"
        funnel_completed_at = clock()
        with performance.measure("authoritative_entry_funnel"):
            record_authoritative_entry_funnel(
                repository=repository, scanner_id=scanner_id,
                run_number=run_number, started_at=started,
                completed_at=funnel_completed_at, symbols=funnel_symbols,
                monotonic=monotonic, candidate_records=cycle_outcomes,
            )

        stage = "authoritative_entry_query"
        lease.ensure_owned()
        with performance.measure("paper_handoff_query"):
            shared_entry_events = repository.list_trade_event_summaries(
                limit=5000, event_type="TRADE_ENTERED"
            )
            paper_candidates = pending_authoritative_entries(
                repository, results, paper_repository, entry_events=shared_entry_events
            )
            authoritative_entries_generated = repository.count_trade_events(
                event_type="TRADE_ENTERED", start_at=started,
            )
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
                capital_repository=capital_repository,
            )
        stage = "mirror_execution"
        lease.ensure_owned()
        shared_chain_provider = CachedChainProvider() if (mirror_is_enabled or mirror_v2_is_enabled) else None
        with performance.measure("mirror_handoff_query"):
            shared_exit_events = repository.list_trade_event_summaries(
                limit=5000, event_type="TRADE_CLOSED"
            ) if (mirror_is_enabled or mirror_v2_is_enabled) else []
            mirror_candidates = pending_mirror_entries(
                repository, results, mirror_repository, entry_events=shared_entry_events
            ) if mirror_is_enabled else []
            mirror_v2_candidates = pending_mirror_entries(
                repository, results, mirror_v2_repository, entry_events=shared_entry_events
            ) if mirror_v2_is_enabled else []
        with performance.measure("mirror_cycle"):
            run_mirror_execution(
                repository, mirror_repository, mirror_candidates,
                enabled=mirror_is_enabled, scanner_id=scanner_id,
                run_number=run_number, now=clock(),
                chain_provider=shared_chain_provider,
                experiment_start_date=mirror_start_date,
                entry_events=shared_entry_events, exit_events=shared_exit_events,
                underlying_prices={
                    str(result.get("symbol") or symbol): result.get("price")
                    for symbol, result in results.items() if isinstance(result, dict)
                },
            )
            run_mirror_v2_shadow(
                repository, mirror_v2_repository, mirror_v2_candidates,
                enabled=mirror_v2_is_enabled, scanner_id=scanner_id, now=clock(),
                chain_provider=shared_chain_provider, control_repository=mirror_repository,
                experiment_start_date=mirror_v2_start_date,
                entry_events=shared_entry_events, exit_events=shared_exit_events,
            )
            run_filtered_execution(
                repository, filtered_repository, paper_repository, mirror_repository,
                shared_entry_events, enabled=filtered_is_enabled,
                scanner_id=scanner_id, now=clock(),
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
            _finish_provenance_cycle(
                repository, provenance_cycle_id, completed_at=completed,
                cycle_status="ERROR", provider_state="ERROR",
                symbols_evaluated=provenance_symbols, data_freshness="unavailable",
                failure_reason=f"{type(scan_phase_error).__name__}: scanner phase failed",
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
        final_provider_state = (
            "AVAILABLE" if results and failures == 0 else
            "PARTIAL" if results else "UNAVAILABLE"
        )
        _finish_provenance_cycle(
            repository, provenance_cycle_id, completed_at=completed,
            cycle_status="COMPLETED", provider_state=final_provider_state,
            symbols_evaluated=provenance_symbols,
            data_freshness="fresh" if results else "unavailable",
        )
        return 0 if results else 1
    except Exception as exc:
        if stage in {
            "paper_repository_initialization", "paper_runtime_config_persistence",
            "paper_state_refresh",
            "authoritative_entry_query", "paper_execution", "mirror_execution",
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
        _finish_provenance_cycle(
            repository, provenance_cycle_id, completed_at=completed,
            cycle_status="ERROR", provider_state="ERROR",
            symbols_evaluated=provenance_symbols, data_freshness="unavailable",
            failure_reason=f"{type(exc).__name__}: scanner failed",
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
