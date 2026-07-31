"""Persistent Railway-compatible scanner worker."""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import threading

from build_information import build_information
from finnhub_universe import DEFAULT_SYMBOL_GROUPS, flatten_symbol_groups
from optionbeacon.worker.scan_once import run_scan_once
from trade_repository import DEFAULT_SCANNER_ID, RepositoryUnavailable
from trade_state_service import repository_for_runtime


LOGGER = logging.getLogger(__name__)
DEFAULT_SCAN_SECONDS = 300
MIN_SCAN_SECONDS = 30
MAX_SCAN_SECONDS = 3600
MAX_FAILURE_BACKOFF_SECONDS = 900


class WorkerConfigurationError(ValueError):
    pass


def configuration_error_record(exc):
    """Build a sanitized startup failure record without exposing credentials."""
    durable_required = (
        os.getenv("OPTIONBEACON_REQUIRE_DURABLE_STORAGE", "").strip().lower()
        in {"1", "true", "yes"}
        or os.getenv("OPTIONBEACON_ENVIRONMENT", "").strip().lower()
        == "production"
    )
    return {
        "event": "worker_configuration_error",
        "error": type(exc).__name__,
        "message": str(exc),
        "database_url_configured": bool(os.getenv("DATABASE_URL", "").strip()),
        "durable_storage_required": durable_required,
    }


def configured_scan_seconds(value=None) -> int:
    raw = value if value is not None else os.getenv(
        "OPTIONBEACON_SCAN_SECONDS", str(DEFAULT_SCAN_SECONDS)
    )
    try:
        seconds = int(raw)
    except (TypeError, ValueError) as exc:
        raise WorkerConfigurationError(
            "OPTIONBEACON_SCAN_SECONDS must be an integer."
        ) from exc
    if not MIN_SCAN_SECONDS <= seconds <= MAX_SCAN_SECONDS:
        raise WorkerConfigurationError(
            f"OPTIONBEACON_SCAN_SECONDS must be between "
            f"{MIN_SCAN_SECONDS} and {MAX_SCAN_SECONDS}."
        )
    return seconds


def failure_backoff_seconds(consecutive_failures, interval_seconds):
    if consecutive_failures <= 0:
        return interval_seconds
    return min(
        MAX_FAILURE_BACKOFF_SECONDS,
        max(interval_seconds, 30 * (2 ** (consecutive_failures - 1))),
    )


def startup_record(repository, interval_seconds, scanner_id):
    build = build_information(streamlit_version="not-applicable")
    return {
        "event": "worker_start",
        "application_version": build["commit"],
        "storage_backend": repository.backend,
        "scanner_interval_seconds": interval_seconds,
        "configured_symbols": len(flatten_symbol_groups(DEFAULT_SYMBOL_GROUPS)),
        "environment": os.getenv(
            "OPTIONBEACON_ENVIRONMENT", build["environment"]
        ),
        "scanner_id": scanner_id,
    }


def run(
    *,
    repository,
    interval_seconds,
    scanner_id,
    max_runs=None,
    scan_once=run_scan_once,
    stop_event=None,
):
    completed = 0
    failures = 0
    stopping = stop_event or threading.Event()

    def stop(signum, _frame):
        LOGGER.info(
            json.dumps(
                {"event": "worker_stop_requested", "signal": signum},
                sort_keys=True,
            )
        )
        stopping.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    LOGGER.info(json.dumps(startup_record(repository, interval_seconds, scanner_id), sort_keys=True))
    while not stopping.is_set() and (max_runs is None or completed < max_runs):
        result = scan_once(repository=repository, scanner_id=scanner_id)
        completed += 1
        failures = failures + 1 if result == 1 else 0
        LOGGER.info(
            json.dumps(
                {
                    "event": "scan_complete",
                    "exit_code": result,
                    "run_number": completed,
                    "consecutive_failures": failures,
                },
                sort_keys=True,
            )
        )
        if not stopping.is_set() and (max_runs is None or completed < max_runs):
            delay = failure_backoff_seconds(failures, interval_seconds)
            stopping.wait(delay)
    LOGGER.info(
        json.dumps(
            {"event": "worker_stopped", "completed_runs": completed},
            sort_keys=True,
        )
    )
    return completed


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval-seconds")
    parser.add_argument("--max-runs", type=int)
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        interval = configured_scan_seconds(args.interval_seconds)
        scanner_id = os.getenv(
            "OPTIONBEACON_SCANNER_ID", DEFAULT_SCANNER_ID
        ).strip()
        if not scanner_id:
            raise WorkerConfigurationError(
                "OPTIONBEACON_SCANNER_ID cannot be empty."
            )
        repository = repository_for_runtime()
    except (RepositoryUnavailable, WorkerConfigurationError) as exc:
        LOGGER.exception(
            json.dumps(configuration_error_record(exc), sort_keys=True)
        )
        return 2
    run(
        repository=repository,
        interval_seconds=interval,
        scanner_id=scanner_id,
        max_runs=args.max_runs,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
