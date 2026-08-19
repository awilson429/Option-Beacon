"""Opt-in Railway single-writer worker for the paper-only SPY/QQQ lane.

Run separately with ``python -m optionbeacon.worker.intraday``. It is deliberately
not invoked by the authoritative broad scanner worker.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from intraday_execution import IntradayRepository, ManagedConfig, select_contracts
from intraday_strategy import UNIVERSE, detect_candidate, market_context, trigger_crossed
from optionbeacon.worker.logging_config import configure_worker_logging
from trade_state_service import repository_for_runtime
from tradier_options import option_chain, option_expirations, option_quote, time_sales


LOGGER = logging.getLogger(__name__)
EASTERN = ZoneInfo("America/New_York")
SCANNER_ID = "index-intraday-paper"
DEFAULT_INTERVAL_SECONDS = 60


class ProviderRequestFailure(RuntimeError):
    def __init__(self, provider, stage, symbol, endpoint_path, *, http_status=None,
                 exception_class="ProviderError"):
        super().__init__(f"{provider} request failed during {stage}")
        self.provider = provider
        self.stage = stage
        self.symbol = symbol
        self.endpoint_path = endpoint_path
        self.http_status = http_status
        self.exception_class = exception_class


def _event(event, **fields):
    LOGGER.info(json.dumps({"event": event, "scanner_id": SCANNER_ID, **fields},
                           sort_keys=True, default=str))


def _status_from_error(error):
    status = getattr(error, "code", None)
    if status is not None:
        return int(status)
    match = re.search(r"HTTP Error\s+(\d{3})", str(error), re.IGNORECASE)
    return int(match.group(1)) if match else None


def _provider_failure(provider, stage, symbol, endpoint_path, error):
    status = _status_from_error(error)
    exception_class = "HTTPError" if isinstance(error, str) and status else type(error).__name__
    failure = error if isinstance(error, ProviderRequestFailure) else ProviderRequestFailure(
        provider, stage, symbol, endpoint_path,
        http_status=status, exception_class=exception_class,
    )
    _event("intraday_provider_request_failed", provider=failure.provider,
           stage=failure.stage, symbol=failure.symbol,
           endpoint_path=failure.endpoint_path, http_status=failure.http_status,
           exception_class=failure.exception_class)
    return failure


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
                if error:
                    _provider_failure("Tradier", "option_quote", position["symbol"],
                                      "/markets/quotes", error)
                ledger.record_update_failure(trade_id, error or "Option quote unavailable", now=now)
                _event("intraday_position_update_failed", opportunity_id=position["opportunity_id"],
                       trade_id=trade_id, symbol=position["symbol"], execution_variant=variant,
                       contract=contract, reason=error or "Option quote unavailable")
                continue
            if str(position.get("symbol")).upper() == "QQQ":
                try:
                    mark_id=ledger.record_position_mark(trade_id,quote,now=now,
                        underlying_price=(bars.get("QQQ") or [{}])[-1].get("close"))
                    _event("qqq_position_mark_persisted" if mark_id else "qqq_position_mark_duplicate_prevented",
                           trade_id=trade_id,execution_variant=variant)
                except Exception as exc:
                    _event("qqq_position_mark_persistence_failed",trade_id=trade_id,exception_class=type(exc).__name__)
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
                try: ledger.sync_shadow_outcome(trade_id,now=now)
                except Exception as exc: _event("qqq_first_two_shadow_sync_failed",trade_id=trade_id,exception_class=type(exc).__name__)
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
    open_opportunities = {row["opportunity_id"] for row in ledger.list_trades(status="OPEN", limit=500)}
    for signal in ledger.active_signal_states():
        if signal["opportunity_id"] not in open_opportunities and signal.get("state") in {"PAPER_OPENED", "MANAGED"}:
            ledger.transition_signal(signal["opportunity_id"], signal["state"], "CLOSED",
                                     reason="ALL_PAPER_VARIANTS_CLOSED", now=now)
    return calls


def tradier_minute_bars(symbol, *, now=None, lookback_minutes=240):
    now = now or datetime.now(timezone.utc)
    local_end = now.astimezone(EASTERN)
    local_start = (now - timedelta(minutes=lookback_minutes)).astimezone(EASTERN)
    rows, error = time_sales(
        symbol, local_start.strftime("%Y-%m-%d %H:%M"),
        local_end.strftime("%Y-%m-%d %H:%M"), interval="1min", session_filter="open",
    )
    if error:
        status = _status_from_error(error)
        exception_class = ("HTTPError" if status else "TimeoutError"
                           if "timed out" in str(error).lower() else "ProviderError")
        raise ProviderRequestFailure(
            "Tradier", "minute_bars", symbol, "/markets/timesales",
            http_status=status, exception_class=exception_class,
        )
    normalized = []
    seen = set()
    required = ("timestamp", "open", "high", "low", "close", "volume")
    for row in rows:
        if not isinstance(row, dict) or any(row.get(field) is None for field in required):
            raise ProviderRequestFailure(
                "Tradier", "minute_bars", symbol, "/markets/timesales",
                exception_class="ProviderDataError",
            )
        try:
            stamp = datetime.fromtimestamp(float(row["timestamp"]), timezone.utc).astimezone(EASTERN)
            bar = {"timestamp": stamp, **{field: float(row[field])
                   for field in ("open", "high", "low", "close", "volume")}}
        except (TypeError, ValueError, OSError, OverflowError) as exc:
            raise ProviderRequestFailure(
                "Tradier", "minute_bars", symbol, "/markets/timesales",
                exception_class="ProviderDataError",
            ) from exc
        if stamp in seen:
            raise ProviderRequestFailure(
                "Tradier", "minute_bars", symbol, "/markets/timesales",
                exception_class="ProviderDataError",
            )
        seen.add(stamp)
        normalized.append(bar)
    if not normalized:
        raise ProviderRequestFailure(
            "Tradier", "minute_bars", symbol, "/markets/timesales",
            exception_class="ProviderDataUnavailable",
        )
    return sorted(normalized, key=lambda bar: bar["timestamp"])


def run_intraday_cycle(repository, *, bar_provider=tradier_minute_bars,
                       quote_provider=option_quote, now=None):
    now = now or datetime.now(timezone.utc)
    started = time.perf_counter()
    owner = repository.acquire_scan_lock(SCANNER_ID, ttl_seconds=55)
    if not owner:
        return 0
    ledger = None
    calls = 0
    failure_stage = "intraday_repository_initialization"
    try:
        ledger = IntradayRepository(repository)
        _event("intraday_cycle_started")
        failure_stage = "open_positions_query"
        open_positions = ledger.list_trades(status="OPEN", limit=500)
        failure_stage = "minute_bars"
        bars = {}
        provider_failures = []
        for symbol in UNIVERSE:
            calls += 1
            try:
                bars[symbol] = bar_provider(symbol, now=now)
            except Exception as exc:
                provider_failures.append(_provider_failure(
                    "Tradier", "minute_bars", symbol, "/markets/timesales", exc
                ))
        if provider_failures:
            raise provider_failures[0]
        failure_stage = "position_management"
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
            failure_stage = "option_expirations"
            expirations, error = option_expirations(symbol); calls += 1
            if error:
                raise _provider_failure("Tradier", "option_expirations", symbol,
                                        "/markets/options/expirations", error)
            chains = []
            for expiration in expirations:
                try: dte = (datetime.fromisoformat(expiration).date() - now.astimezone(EASTERN).date()).days
                except ValueError: continue
                if dte in (0, 1):
                    failure_stage = "option_chain"
                    rows, chain_error = option_chain(symbol, expiration); calls += 1
                    if chain_error:
                        raise _provider_failure("Tradier", "option_chain", symbol,
                                                "/markets/options/chains", chain_error)
                    chains.extend(rows)
            opened_any = False
            for contract in select_contracts(chains, candidate.option_type, candidate.price, now.astimezone(EASTERN).date()):
                opened = ledger.open_variants(candidate, contract, now=now, config=ManagedConfig())
                opened_any = opened_any or bool(opened)
                for trade_id in sorted(opened):
                    row = ledger.trade(trade_id)
                    payload = {"opportunity_id": candidate.opportunity_id, "trade_id": trade_id,
                               "symbol": symbol, "execution_variant": row["variant"],
                               "contract": contract["option_symbol"], "option_mark": row["entry_fill"]}
                    ledger.journal("intraday_paper_opened", opportunity_id=candidate.opportunity_id,
                                   trade_id=trade_id, now=now, payload=payload)
                    _event("intraday_paper_opened", **payload)
                    if symbol == "QQQ":
                        try:
                            shadow=ledger.record_first_two_shadow(trade_id,now=now)
                            _event("qqq_first_two_shadow_evaluated",source_trade_id=trade_id,session_trade_number=(shadow or {}).get("session_trade_number"))
                            _event("qqq_first_two_shadow_accepted" if (shadow or {}).get("shadow_status")=="SHADOW_ACCEPTED" else "qqq_first_two_shadow_rejected",source_trade_id=trade_id)
                        except Exception as exc:
                            _event("qqq_first_two_shadow_persistence_failed",source_trade_id=trade_id,exception_class=type(exc).__name__)
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
        failure = exc if isinstance(exc, ProviderRequestFailure) else None
        if ledger is not None:
            try:
                ledger.save_runtime_state(SCANNER_ID, status="ERROR", symbols_processed=0,
                                          call_count=calls, duration_ms=duration,
                                          error=(failure.exception_class if failure
                                                 else type(exc).__name__), now=now)
            except Exception:
                LOGGER.exception("Could not persist intraday runtime failure state")
        failure_payload = json.dumps({
            "event": "intraday_cycle_failed", "scanner_id": SCANNER_ID,
            "error": failure.exception_class if failure else type(exc).__name__,
            "failure_stage": failure.stage if failure else failure_stage,
            "provider": failure.provider if failure else None,
            "http_status": failure.http_status if failure else None,
        }, sort_keys=True)
        if failure:
            # Provider tracebacks can expose credential-bearing request details.
            LOGGER.error(failure_payload)
        else:
            LOGGER.exception(failure_payload)
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
