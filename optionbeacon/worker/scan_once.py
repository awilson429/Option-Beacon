"""Run one locked, idempotent OptionBeacon scan."""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime, timezone

from build_information import build_information
from finnhub_universe import active_symbol_groups, flatten_symbol_groups
from optionbeacon_live import generate_signal
from optionbeacon_snapshot import save_latest_results
from signal_history import load_trade_outcomes
from trade_repository import DEFAULT_SCANNER_ID, RepositoryUnavailable
from trade_state_service import repository_for_runtime, sync_trade_outcomes


LOGGER = logging.getLogger(__name__)


def run_scan_once(
    *,
    repository=None,
    signal_generator=generate_signal,
    symbol_groups_loader=active_symbol_groups,
    snapshot_writer=save_latest_results,
) -> int:
    repository = repository or repository_for_runtime()
    owner = repository.acquire_scan_lock(DEFAULT_SCANNER_ID)
    if owner is None:
        LOGGER.warning("Scanner invocation skipped because another scan owns the lock")
        return 2
    started = datetime.now(timezone.utc)
    build = build_information()
    repository.record_scan_heartbeat(
        started_at=started,
        code_version=build["commit"],
        market_data_state="SCANNING",
    )
    results = {}
    failures = 0
    try:
        groups, source, universe_error = symbol_groups_loader()
        symbols = flatten_symbol_groups(groups)
        if universe_error:
            LOGGER.warning("Scanner universe warning: %s", universe_error)
        for symbol in symbols:
            try:
                result = signal_generator(symbol)
            except Exception as exc:
                failures += 1
                LOGGER.warning(
                    "Signal generation failed: %s",
                    json.dumps(
                        {"symbol": symbol, "error": type(exc).__name__},
                        sort_keys=True,
                    ),
                )
                continue
            if result is not None:
                results[symbol] = result
        snapshot_writer(results)
        sync_trade_outcomes(
            repository,
            load_trade_outcomes(),
            source_version=build["commit"],
        )
        completed = datetime.now(timezone.utc)
        repository.record_scan_heartbeat(
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
            code_version=build["commit"],
        )
        return 1
    finally:
        repository.release_scan_lock(DEFAULT_SCANNER_ID, owner)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        return run_scan_once()
    except RepositoryUnavailable as exc:
        LOGGER.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
