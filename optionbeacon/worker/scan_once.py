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
) -> int:
    repository = repository or repository_for_runtime()
    scanner_id = scanner_id or os.getenv(
        "OPTIONBEACON_SCANNER_ID", DEFAULT_SCANNER_ID
    )
    eod_exit_time = configured_eod_exit_time(eod_exit_time)
    owner = repository.acquire_scan_lock(scanner_id)
    if owner is None:
        LOGGER.warning("Scanner invocation skipped because another scan owns the lock")
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
        if universe_error:
            LOGGER.warning("Scanner universe warning: %s", universe_error)
        for symbol in symbols:
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
                    continue
            if result is None:
                continue
            results[symbol] = result
            process_scanner_result(
                repository,
                result,
                source_version=build["commit"],
                current_timestamp=clock(),
                eod_exit_time=eod_exit_time,
            )
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
