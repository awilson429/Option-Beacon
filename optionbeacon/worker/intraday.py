"""Opt-in Railway single-writer worker for the paper-only SPY/QQQ lane.

Run separately with ``python -m optionbeacon.worker.intraday``. It is deliberately
not invoked by the authoritative broad scanner worker.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from finnhub_universe import FINNHUB_BASE_URL, finnhub_api_key
from intraday_execution import IntradayRepository, ManagedConfig, select_contracts
from intraday_strategy import UNIVERSE, detect_candidate, trigger_crossed
from optionbeacon.worker.logging_config import configure_worker_logging
from trade_state_service import repository_for_runtime
from tradier_options import option_chain, option_expirations


LOGGER = logging.getLogger(__name__)
EASTERN = ZoneInfo("America/New_York")
SCANNER_ID = "index-intraday-paper"
DEFAULT_INTERVAL_SECONDS = 60


def finnhub_minute_bars(symbol, *, now=None, lookback_minutes=240):
    now = now or datetime.now(timezone.utc)
    params = {"symbol": symbol, "resolution": "1",
              "from": int((now - timedelta(minutes=lookback_minutes)).timestamp()),
              "to": int(now.timestamp()), "token": finnhub_api_key()}
    with urlopen(f"{FINNHUB_BASE_URL}/stock/candle?{urlencode(params)}", timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return [{"timestamp": datetime.fromtimestamp(stamp, timezone.utc).astimezone(EASTERN),
             "open": opened, "high": high, "low": low, "close": close, "volume": volume}
            for stamp, opened, high, low, close, volume in zip(payload.get("t", []), payload.get("o", []),
            payload.get("h", []), payload.get("l", []), payload.get("c", []), payload.get("v", []))]


def run_intraday_cycle(repository, *, bar_provider=finnhub_minute_bars, now=None):
    now = now or datetime.now(timezone.utc)
    ledger = IntradayRepository(repository)
    started = time.perf_counter()
    LOGGER.info(json.dumps({"event": "intraday_cycle_started", "scanner_id": SCANNER_ID}, sort_keys=True))
    owner = repository.acquire_scan_lock(SCANNER_ID, ttl_seconds=55)
    if not owner:
        return 0
    calls = 0
    try:
        bars = {symbol: bar_provider(symbol, now=now) for symbol in UNIVERSE}; calls += 2
        for symbol, peer in (("SPY", "QQQ"), ("QQQ", "SPY")):
            candidate = detect_candidate(symbol, bars[symbol], bars[peer], now=now)
            if not candidate: continue
            existing = ledger.signal(candidate.opportunity_id)
            ledger.save_signal(candidate)
            LOGGER.info(json.dumps({"event": "intraday_setup_armed", "opportunity_id": candidate.opportunity_id,
                "symbol": symbol, "setup": candidate.setup, "direction": candidate.direction}, sort_keys=True))
            # Detection arms a setup; execution only occurs on a later observed crossing.
            if not existing or existing.get("state") != "ARMED" or not trigger_crossed(
                candidate, float(bars[symbol][-2]["close"]), float(bars[symbol][-1]["close"])
            ):
                continue
            ledger.transition_signal(candidate.opportunity_id, "ARMED", "TRIGGERED")
            expirations, error = option_expirations(symbol); calls += 1
            if error: continue
            chains = []
            for expiration in expirations:
                try: dte = (datetime.fromisoformat(expiration).date() - now.astimezone(EASTERN).date()).days
                except ValueError: continue
                if dte in (0, 1):
                    rows, chain_error = option_chain(symbol, expiration); calls += 1
                    if not chain_error: chains.extend(rows)
            opened_any = False
            for contract in select_contracts(chains, candidate.option_type, candidate.price, now.astimezone(EASTERN).date()):
                opened = ledger.open_variants(candidate, contract, now=now, config=ManagedConfig())
                opened_any = opened_any or bool(opened)
                for trade_id in opened:
                    LOGGER.info(json.dumps({"event": "intraday_paper_opened", "opportunity_id": candidate.opportunity_id,
                        "trade_id": trade_id, "symbol": symbol, "contract": contract["option_symbol"]}, sort_keys=True))
            if opened_any:
                ledger.transition_signal(candidate.opportunity_id, "TRIGGERED", "PAPER_OPENED")
        duration = (time.perf_counter() - started) * 1000
        LOGGER.info(json.dumps({"event": "intraday_cycle_completed", "symbols_processed": 2,
                               "provider_calls": calls, "duration_ms": duration}, sort_keys=True))
        return 0
    except Exception as exc:
        LOGGER.exception(json.dumps({"event": "intraday_cycle_failed", "error": type(exc).__name__}, sort_keys=True))
        return 1
    finally:
        repository.release_scan_lock(SCANNER_ID, owner)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval-seconds", type=int, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--max-runs", type=int)
    args = parser.parse_args(argv)
    if not 30 <= args.interval_seconds <= 300:
        parser.error("interval must be between 30 and 300 seconds")
    configure_worker_logging()
    repository = repository_for_runtime(database_url=os.getenv("DATABASE_URL", ""))
    completed = 0
    while args.max_runs is None or completed < args.max_runs:
        run_intraday_cycle(repository); completed += 1
        if args.max_runs is None or completed < args.max_runs: time.sleep(args.interval_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
