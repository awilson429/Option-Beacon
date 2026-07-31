import json
import logging

import pandas as pd

import optionbeacon_live
from optionbeacon.worker.scan_once import run_scan_once
from trade_repository import TradeRepository


def frame():
    return pd.DataFrame(
        {
            "Open": [100.0],
            "High": [101.0],
            "Low": [99.0],
            "Close": [100.5],
            "Volume": [1000],
        }
    )


def test_yfinance_429_uses_bounded_exponential_retry(monkeypatch):
    attempts = []
    delays = []

    def download(symbol, period):
        attempts.append((symbol, period))
        if len(attempts) < 3:
            raise RuntimeError("HTTP Error 429: Too Many Requests")
        return frame()

    monkeypatch.setattr(optionbeacon_live, "download_data", download)
    optionbeacon_live.begin_market_data_scan_cycle()
    result = optionbeacon_live._download_market_data(
        "IWM",
        "5d",
        sleep=delays.append,
        jitter=lambda _low, _high: 0.1,
    )
    summary = optionbeacon_live.end_market_data_scan_cycle()

    assert not result.empty
    assert attempts == [("IWM", "5d")] * 3
    assert delays == [0.6, 1.1]
    assert summary["rate_limited_symbols"] == ["IWM"]
    assert summary["requests"] == 3


def test_identical_market_request_is_reused_within_scan(monkeypatch):
    calls = []
    monkeypatch.setattr(
        optionbeacon_live,
        "download_data",
        lambda symbol, period: calls.append((symbol, period)) or frame(),
    )
    optionbeacon_live.begin_market_data_scan_cycle()
    first = optionbeacon_live._download_market_data("INTC", "5d")
    second = optionbeacon_live._download_market_data("INTC", "5d")
    summary = optionbeacon_live.end_market_data_scan_cycle()

    assert calls == [("INTC", "5d")]
    assert first.equals(second)
    assert summary["cache_hits"] == 1


def test_partial_scan_emits_one_provider_warning_summary(tmp_path, caplog):
    repository = TradeRepository(tmp_path / "state.db", database_url="")

    def generate(symbol):
        if symbol == "IEF":
            raise RuntimeError("HTTP Error 429")
        return {"symbol": symbol, "signal": "WAIT", "price": 100}

    with caplog.at_level(logging.WARNING):
        result = run_scan_once(
            repository=repository,
            symbol_groups_loader=lambda: (
                {"Core": ["IWM", "IEF", "JETS"]},
                "test",
                "",
            ),
            signal_generator=generate,
            snapshot_writer=lambda _results: None,
        )

    summaries = [
        json.loads(record.message)
        for record in caplog.records
        if '"event": "provider_warning_summary"' in record.message
    ]
    assert result == 0
    assert len(summaries) == 1
    assert summaries[0]["failed_symbols"] == ["IEF"]
    assert repository.get_scan_health()["market_data_state"] == "PARTIAL"
