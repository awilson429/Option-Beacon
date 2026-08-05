import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

import optionbeacon_live
import tradier_options
import false_breakout_experiment
import regime_selection_experiment
import signal_funnel_experiment
from optionbeacon.worker.scan_once import run_scan_once
from scanner_performance import (
    RunTiming,
    performance_warnings,
    percentile,
    symbol_timing,
)
from trade_repository import TradeRepository


NOW = datetime(2026, 8, 6, 14, tzinfo=timezone.utc)


class Monotonic:
    def __init__(self, step=.1):
        self.value = 0.0
        self.step = step

    def __call__(self):
        value = self.value
        self.value += self.step
        return value


def _timing_record(symbol, total_ms, completed_at, *, success=True):
    return {
        "symbol": symbol, "attempt_index": 1, "symbol_count": 3,
        "total_ms": total_ms, "success": success, "exception_type": None,
        "stages_ms": {"indicator_calculation": 10},
        "provider_time_ms": {"Yahoo Finance via yfinance:historical_bars": total_ms / 2},
        "provider_calls": {"Yahoo Finance via yfinance:historical_bars": 1},
        "provider_status_counts": {}, "retry_count": 0,
        "provider_outcomes": {"Yahoo Finance via yfinance:historical_bars:success": 1},
        "rate_limit_count": 0, "timeout_count": 0, "retry_backoff_ms": 0,
        "intentional_throttle_ms": 0,
        "completed_wall_time": completed_at,
        "started_wall_time": completed_at - timedelta(milliseconds=total_ms),
    }


def test_percentiles_slowest_order_and_rotation_skew_are_deterministic():
    clock = Monotonic()
    run = RunTiming("scanner", 12, monotonic=clock)
    run.add_symbol(_timing_record("SPY", 1000, NOW + timedelta(seconds=1)))
    run.add_symbol(_timing_record("QQQ", 9000, NOW + timedelta(seconds=10)))
    run.add_symbol(_timing_record("IWM", 5000, NOW + timedelta(seconds=15)))
    summary = run.summary(symbol_count=3, symbols_attempted=3, results=3, failures=0)
    assert percentile([1000, 9000, 5000], 90) == 9000
    assert summary["median_symbol_ms"] == 5000
    assert summary["p90_symbol_ms"] == 9000
    assert summary["slowest_symbols"][0] == {"symbol": "QQQ", "total_ms": 9000}
    assert summary["rotation_skew_ms"] == 15000
    assert summary["first_symbols"] == ["SPY", "QQQ", "IWM"]


def test_generate_signal_aggregates_real_stages_without_changing_result(monkeypatch):
    frame = pd.DataFrame(
        {"Close": range(40)},
        index=pd.date_range("2026-08-06", periods=40, freq="5min"),
    )
    expected = {"symbol": "SPY", "signal": "WAIT", "price": 500}
    monkeypatch.setattr(optionbeacon_live, "get_data", lambda symbol: frame)
    monkeypatch.setattr(optionbeacon_live, "add_indicators", lambda data: data)
    monkeypatch.setattr(optionbeacon_live, "score_candle", lambda *args: dict(expected))
    monkeypatch.setattr(optionbeacon_live, "enrich_with_trade_plan", lambda result: result)
    monkeypatch.setattr(optionbeacon_live, "enrich_with_option_liquidity", lambda result: result)
    monkeypatch.setattr(optionbeacon_live, "process_scanner_trade_plan", lambda result: None)
    monkeypatch.setattr(optionbeacon_live, "update_trade_outcomes_from_result", lambda result: None)
    monkeypatch.setattr(optionbeacon_live, "record_scanner_result", lambda result: None)
    monkeypatch.setattr(false_breakout_experiment, "record_live_shadow", lambda *args: None)
    monkeypatch.setattr(regime_selection_experiment, "record_live_shadow", lambda *args: None)
    monkeypatch.setattr(signal_funnel_experiment, "record_live_shadow", lambda *args: None)
    with symbol_timing("SPY", 1, 68, monotonic=Monotonic()) as timing:
        result = optionbeacon_live.generate_signal("SPY")
        record = timing.finish(success=True, completed_wall_time=NOW)
    assert {key: result[key] for key in expected} == expected
    assert {
        "market_data", "indicator_calculation", "scoring",
        "trade_plan_enrichment", "option_liquidity", "trade_plan_persistence",
        "legacy_outcome_persistence", "scanner_result_persistence",
    } <= record["stages_ms"].keys()


def test_yahoo_retry_backoff_and_provider_calls_are_accounted(monkeypatch):
    calls = []
    sleeps = []

    def download(symbol, period):
        calls.append(symbol)
        if len(calls) == 1:
            raise RuntimeError("HTTP 429 rate limit")
        return pd.DataFrame({"Close": [1]})

    monkeypatch.setattr(optionbeacon_live, "download_data", download)
    optionbeacon_live.begin_market_data_scan_cycle()
    with symbol_timing("SPY", 1, 68, monotonic=Monotonic()) as timing:
        result = optionbeacon_live._download_market_data(
            "SPY", "5d", sleep=sleeps.append, jitter=lambda *_: 0,
        )
        record = timing.finish(success=True, completed_wall_time=NOW)
    optionbeacon_live.end_market_data_scan_cycle()
    assert not result.empty and sleeps == [.5]
    assert record["retry_count"] == 1
    assert record["retry_backoff_ms"] == 500
    assert record["rate_limit_count"] == 1
    assert record["provider_calls"]["Yahoo Finance via yfinance:historical_bars"] == 2


def test_tradier_provider_timing_is_structured_and_redacts_credentials(monkeypatch):
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def read(self): return b'{"expirations":{"date":["2026-08-07"]}}'

    monkeypatch.setattr(
        tradier_options, "_secret_value",
        lambda name: "https://tradier.test" if name == tradier_options.BASE_URL_ENV_NAME else "TOP-SECRET",
    )
    monkeypatch.setattr(tradier_options, "urlopen", lambda request, timeout: Response())
    with symbol_timing("SPY", 1, 68, monotonic=Monotonic()) as timing:
        payload, error = tradier_options._get_json(
            "/markets/options/expirations", {"symbol": "SPY"}
        )
        record = timing.finish(success=True, completed_wall_time=NOW)
    encoded = json.dumps({key: value for key, value in record.items() if key != "completed_wall_time"})
    assert payload and not error
    assert "TOP-SECRET" not in encoded and "Authorization" not in encoded
    assert record["provider_calls"]["Tradier:option_expirations"] == 1
    assert record["provider_status_counts"]["Tradier:option_expirations:200"] == 1
    assert record["provider_outcomes"]["Tradier:option_expirations:success"] == 1


def test_option_chain_remains_gated_until_underlying_setup_qualifies(monkeypatch):
    monkeypatch.setattr(
        tradier_options, "option_expirations",
        lambda symbol: (_ for _ in ()).throw(AssertionError("chain should not run")),
    )
    result = tradier_options.option_liquidity_for_setup({
        "symbol": "SPY", "signal": "WAIT", "bias": "Bullish", "price": 500,
    })
    assert result["label"] == "Not checked"


def test_worker_emits_success_failure_symbol_events_and_summary_without_reordering(tmp_path, caplog):
    repository = TradeRepository(tmp_path / "state.db", database_url="")
    order = []

    def signal(symbol):
        order.append(symbol)
        if symbol == "QQQ":
            raise RuntimeError("provider failed")
        return {"symbol": symbol, "signal": "WAIT", "price": 500}

    with caplog.at_level("INFO"):
        result = run_scan_once(
            repository=repository, scanner_id="scanner", run_number=7,
            symbol_groups_loader=lambda: ({"Core": ["SPY", "QQQ", "IWM"]}, "test", ""),
            signal_generator=signal, snapshot_writer=lambda values: None,
            paper_executor=lambda *args, **kwargs: None,
        )
    payloads = []
    for log in caplog.records:
        try:
            payloads.append(json.loads(log.message))
        except (TypeError, json.JSONDecodeError):
            continue
    timings = [row for row in payloads if row.get("event") == "scanner_symbol_timing"]
    summary = next(row for row in payloads if row.get("event") == "scanner_performance_summary")
    assert result == 0
    assert order == ["SPY", "QQQ", "IWM"]
    assert len(timings) == 3
    assert timings[1]["success"] is False
    assert timings[1]["exception_type"] == "RuntimeError"
    assert summary["symbol_count"] == 3
    assert summary["results"] == 2 and summary["failures"] == 1
    assert summary["first_symbols"] == order
    assert "paper_cycle" in summary["phases_ms"]


def test_zero_symbol_summary_and_warnings_do_not_fabricate_percentiles():
    summary = RunTiming("scanner", 1, monotonic=Monotonic()).summary(
        symbol_count=0, symbols_attempted=0, results=0, failures=0,
    )
    assert summary["avg_symbol_ms"] is None
    assert summary["p90_symbol_ms"] is None
    slow = {**summary, "total_run_duration_ms": 300001}
    assert any(row["reason"] == "FULL_SCAN_SLOW" for row in performance_warnings(slow))
