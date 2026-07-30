"""Explicit scheduled worker loop for non-Streamlit process managers."""

from __future__ import annotations

import argparse
import logging
import signal
import time

from optionbeacon.worker.scan_once import run_scan_once


LOGGER = logging.getLogger(__name__)


def run(*, interval_seconds=300, max_runs=None):
    completed = 0
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    while not stopping and (max_runs is None or completed < max_runs):
        run_scan_once()
        completed += 1
        if not stopping and (max_runs is None or completed < max_runs):
            time.sleep(interval_seconds)
    return completed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--max-runs", type=int)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    run(interval_seconds=max(1, args.interval_seconds), max_runs=args.max_runs)


if __name__ == "__main__":
    main()
