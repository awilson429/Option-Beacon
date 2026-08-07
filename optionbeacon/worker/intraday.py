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
from intraday_strategy import UNIVERSE, detect_candidate, market_context, trigger_crossed
from optionbeacon.worker.logging_config import configure_worker_logging
from trade_state_service import repository_for_runtime
from tradier_options import option_chain, option_expirations, option_quote


LOGGER = logging.getLogger(__name__)
EASTERN = ZoneInfo("America/New_York")
SCANNER_ID = "index-intraday-paper"
DEFAULT_INTERVAL_SECONDS = 60


def _event(event, **fields):
    LOGGER.info(json.dumps({"event": event, "scanner_id": SCANNER_ID, **fields},
                           sort_keys=True, default=str))


def _quote_result(provider, option_symbol):
    result = provider(option_symbol)
    if isinstance(result, tuple):
        quote, error = result
    else:
        quote, error = result, ""
    return quote, error


def _mirror_exit_reason(position, symbol_bars, now, config):
    if config.forced_eod_close and now.astimezone(EASTERN).time() >= config.forced_exit_time:
        return "EOD_CLOSE"
    context = market_context(symbol_bars)
    if position.get("direction") == "CALL" and context == "BEARISH":
        return "UNDERLYING_SIGNAL_CLOSED"
    if position.get("direction") == "PUT" and context == "BULLISH":
        return "UNDERLYING_SIGNAL_CLOSED"
    return None


def _manage_positions(ledger, positions, bars, quote_provider, now):
    calls = 0
    quote_cache = {}
    for position in positions:
        trade_id = position["trade_id"]
        contract = position["option_symbol"]
        variant = position["variant"]
        before_protection = bool(position.get("protection_armed"))
        before_trailing = bool(position.get("trailing_active"))
        try:
            if contract not in quote_cache:
                quote_cache[contract] = _quote_result(quote_provider, contract)
                calls += 1
            quote, error = quote_cache[contract]
            if error or not quote:
                ledger.record_update_failure(trade_id, error or "Option quote unavailable", now=now)
                _event("intraday_position_update_failed", opportunity_id=position["opportunity_id"],
                       trade_id=trade_id, symbol=position["symbol"], execution_variant=variant,
                       contract=contract, reason=error or "Option quote unavailable")
                continue
            if variant == "INTRADAY_MANAGED":
                updated = ledger.update_managed(
                    trade_id, quote, now=now, config=ledger.config_for(position)
                )
            else:
                reason = _mirror_exit_reason(
                    position, bars.get(position["symbol"], []), now, ledger.config_for(position)
                )
                updated = ledger.update_mirror(trade_id, quote, close_reason=reason, now=now)
            if not updated:
                continue
            payload = dict(opportunity_id=updated["opportunity_id"], trade_id=trade_id,
                           symbol=updated["symbol"], execution_variant=variant, contract=contract,
                           option_mark=updated.get("current_mark"),
                           unrealized_pnl=updated.get("unrealized_pnl"))
            ledger.journal("intraday_position_updated", opportunity_id=updated["opportunity_id"],
                           trade_id=trade_id, now=now, payload=payload)
            _event("intraday_position_updated", **payload)
            if not before_protection and bool(updated.get("protection_armed")):
                ledger.journal("intraday_profit_protection_armed",
                    opportunity_id=updated["opportunity_id"], trade_id=trade_id, now=now, payload=payload)
                _event("intraday_profit_protection_armed", **payload)
            if not before_trailing and bool(updated.get("trailing_active")):
                ledger.journal("intraday_trailing_activated",
                    opportunity_id=updated["opportunity_id"], trade_id=trade_id, now=now, payload=payload)
                _event("intraday_trailing_activated", **payload)
            if updated.get("status") == "CLOSED":
                close_payload = {**payload, "realized_pnl": updated.get("realized_pnl"),
                                 "exit_reason": updated.get("exit_reason")}
                ledger.journal("intraday_trade_closed", opportunity_id=updated["opportunity_id"],
                               trade_id=trade_id, now=now, payload=close_payload)
                _event("intraday_trade_closed", **close_payload)
            signal = ledger.signal(updated["opportunity_id"])
            if signal and signal.get("state") == "PAPER_OPENED":
                ledger.transition_signal(updated["opportunity_id"], "PAPER_OPENED", "MANAGED", now=now)
        except Exception as exc:
            ledger.record_update_failure(trade_id, type(exc).__name__, now=now)
            _event("intraday_position_update_failed", opportunity_id=position["opportunity_id"],
                   trade_id=trade_id, symbol=position["symbol"], execution_variant=variant,
                   contract=contract, reason=type(exc).__name__)
    # Close strategy opportunities only after both independently managed variants are closed.
    open_opportunities = {row["opportunity_id"] for row in ledger.list_trades(status="OPEN", limit=10000)}
    for signal in ledger.list_signals(limit=10000):
        if signal["opportunity_id"] not in open_opportunities and signal.get("state") in {"PAPER_OPENED", "MANAGED"}:
            ledger.transition_signal(signal["opportunity_id"], signal["state"], "CLOSED",
                                     reason="ALL_PAPER_VARIANTS_CLOSED", now=now)
    return calls


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


def run_intraday_cycle(repository, *, bar_provider=finnhub_minute_bars,
                       quote_provider=option_quote, now=None):
    now = now or datetime.now(timezone.utc)
    started = time.perf_counter()
    owner = repository.acquire_scan_lock(SCANNER_ID, ttl_seconds=55)
    if not owner:
        return 0
    ledger = None
    calls = 0
    try:
        ledger = IntradayRepository(repository)
        _event("intraday_cycle_started")
        open_positions = ledger.list_trades(status="OPEN", limit=10000)
        bars = {symbol: bar_provider(symbol, now=now) for symbol in UNIVERSE}; calls += 2
        calls += _manage_positions(ledger, open_positions, bars, quote_provider, now)
        for symbol, peer in (("SPY", "QQQ"), ("QQQ", "SPY")):
            candidate = detect_candidate(symbol, bars[symbol], bars[peer], now=now)
            _event("intraday_symbol_evaluated", symbol=symbol,
                   setup_detected=bool(candidate), bar_count=len(bars[symbol]))
            if not candidate: continue
            _event("intraday_setup_detected", opportunity_id=candidate.opportunity_id,
                   symbol=symbol, setup=candidate.setup, direction=candidate.direction)
            existing = ledger.signal(candidate.opportunity_id)
            saved = ledger.save_signal(candidate, state="SETUP_DETECTED")
            if saved.get("state") == "SETUP_DETECTED":
                ledger.transition_signal(candidate.opportunity_id, "SETUP_DETECTED", "ARMED", now=now)
            _event("intraday_setup_armed", opportunity_id=candidate.opportunity_id,
                   symbol=symbol, setup=candidate.setup, direction=candidate.direction)
            # Detection arms a setup; execution only occurs on a later observed crossing.
            if not existing or existing.get("state") != "ARMED" or not trigger_crossed(
                candidate, float(bars[symbol][-2]["close"]), float(bars[symbol][-1]["close"])
            ):
                continue
            ledger.transition_signal(candidate.opportunity_id, "ARMED", "TRIGGERED")
            _event("intraday_triggered", opportunity_id=candidate.opportunity_id,
                   symbol=symbol, setup=candidate.setup, direction=candidate.direction)
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
                    row = ledger.trade(trade_id)
                    payload = {"opportunity_id": candidate.opportunity_id, "trade_id": trade_id,
                               "symbol": symbol, "execution_variant": row["variant"],
                               "contract": contract["option_symbol"], "option_mark": row["entry_fill"]}
                    ledger.journal("intraday_paper_opened", opportunity_id=candidate.opportunity_id,
                                   trade_id=trade_id, now=now, payload=payload)
                    _event("intraday_paper_opened", **payload)
            if opened_any:
                ledger.transition_signal(candidate.opportunity_id, "TRIGGERED", "PAPER_OPENED")
        duration = (time.perf_counter() - started) * 1000
        ledger.save_runtime_state(SCANNER_ID, status="HEALTHY", symbols_processed=2,
                                  call_count=calls, duration_ms=duration, now=now)
        _event("intraday_cycle_completed", symbols_processed=2,
               provider_calls=calls, duration_ms=duration)
        return 0
    except Exception as exc:
        duration = (time.perf_counter() - started) * 1000
        if ledger is not None:
            try:
                ledger.save_runtime_state(SCANNER_ID, status="ERROR", symbols_processed=0,
                                          call_count=calls, duration_ms=duration,
                                          error=type(exc).__name__, now=now)
            except Exception:
                LOGGER.exception("Could not persist intraday runtime failure state")
        LOGGER.exception(json.dumps({"event": "intraday_cycle_failed", "scanner_id": SCANNER_ID,
                                     "error": type(exc).__name__}, sort_keys=True))
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
