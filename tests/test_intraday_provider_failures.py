import json
import logging
from datetime import datetime, timezone
from urllib.error import HTTPError

import optionbeacon.worker.intraday as worker
from intraday_strategy import Candidate
from trade_repository import TradeRepository


NOW = datetime(2026, 8, 7, 18, 0, tzinfo=timezone.utc)


def events(caplog):
    return [json.loads(record.message) for record in caplog.records
            if record.message.startswith("{")]


def http_403(url):
    return HTTPError(url, 403, "Forbidden", {}, None)


def test_finnhub_403_identifies_both_symbols_and_fails_closed(tmp_path, caplog):
    repository = TradeRepository(tmp_path / "state.db")
    secret = "secret-finnhub-token"

    def denied(symbol, **kwargs):
        raise http_403(f"https://finnhub.io/api/v1/stock/candle?token={secret}&symbol={symbol}")

    with caplog.at_level(logging.INFO):
        result = worker.run_intraday_cycle(repository, bar_provider=denied, now=NOW)

    payloads = events(caplog)
    failures = [row for row in payloads if row["event"] == "intraday_provider_request_failed"]
    assert [(row["provider"], row["stage"], row["symbol"], row["endpoint_path"],
             row["http_status"], row["exception_class"]) for row in failures] == [
        ("Finnhub", "minute_bars", "SPY", "/stock/candle", 403, "HTTPError"),
        ("Finnhub", "minute_bars", "QQQ", "/stock/candle", 403, "HTTPError"),
    ]
    cycle = next(row for row in payloads if row["event"] == "intraday_cycle_failed")
    assert (cycle["failure_stage"], cycle["provider"], cycle["http_status"]) == (
        "minute_bars", "Finnhub", 403
    )
    assert result == 1
    assert secret not in caplog.text
    assert not any(row["event"] == "intraday_symbol_evaluated" for row in payloads)


def test_real_finnhub_request_403_never_logs_token(tmp_path, monkeypatch, caplog):
    repository = TradeRepository(tmp_path / "state.db")
    secret = "real-request-secret-token"
    monkeypatch.setattr(worker, "finnhub_api_key", lambda: secret)

    def denied(request, timeout):
        raise http_403(request.full_url)

    monkeypatch.setattr(worker, "urlopen", denied)
    with caplog.at_level(logging.INFO):
        result = worker.run_intraday_cycle(repository, now=NOW)

    assert result == 1
    assert secret not in caplog.text
    assert "token=" not in caplog.text
    failures = [row for row in events(caplog)
                if row["event"] == "intraday_provider_request_failed"]
    assert len(failures) == 2
    assert all(row["endpoint_path"] == "/stock/candle" for row in failures)


def test_tradier_403_is_sanitized_and_fails_before_contract_selection(
        tmp_path, monkeypatch, caplog):
    repository = TradeRepository(tmp_path / "state.db")
    secret = "secret-tradier-token"
    setup = Candidate("existing-armed", "SPY", "CALL", "VWAP RECLAIM", 78,
                      600.0, 600.5, NOW, "AFTERNOON", "TRENDING UP")
    monkeypatch.setattr(worker, "detect_candidate",
                        lambda symbol, *args, **kwargs: setup if symbol == "SPY" else None)
    monkeypatch.setattr(worker, "trigger_crossed", lambda *args: True)
    monkeypatch.setattr(worker, "option_expirations",
                        lambda symbol: ([], f"Tradier request failed: HTTP Error 403: {secret}"))
    ledger = worker.IntradayRepository(repository)
    ledger.save_signal(setup, state="SETUP_DETECTED")
    ledger.transition_signal(setup.opportunity_id, "SETUP_DETECTED", "ARMED", now=NOW)
    bars = [{"timestamp": NOW, "close": 599.0}, {"timestamp": NOW, "close": 601.0}]

    with caplog.at_level(logging.INFO):
        result = worker.run_intraday_cycle(
            repository, bar_provider=lambda symbol, **kwargs: bars, now=NOW
        )

    payloads = events(caplog)
    failure = next(row for row in payloads if row["event"] == "intraday_provider_request_failed")
    assert (failure["provider"], failure["stage"], failure["symbol"],
            failure["endpoint_path"], failure["http_status"], failure["exception_class"]) == (
        "Tradier", "option_expirations", "SPY", "/markets/options/expirations", 403,
        "HTTPError",
    )
    cycle = next(row for row in payloads if row["event"] == "intraday_cycle_failed")
    assert (cycle["failure_stage"], cycle["provider"], cycle["http_status"]) == (
        "option_expirations", "Tradier", 403
    )
    assert result == 1
    assert secret not in caplog.text
    assert ledger.list_trades() == []


def test_successful_bar_provider_behavior_is_unchanged(tmp_path, monkeypatch, caplog):
    repository = TradeRepository(tmp_path / "state.db")
    monkeypatch.setattr(worker, "detect_candidate", lambda *args, **kwargs: None)
    bars = [{"timestamp": NOW, "close": 600.0}, {"timestamp": NOW, "close": 601.0}]

    with caplog.at_level(logging.INFO):
        result = worker.run_intraday_cycle(
            repository, bar_provider=lambda symbol, **kwargs: bars, now=NOW
        )

    payloads = events(caplog)
    assert result == 0
    assert [row["symbol"] for row in payloads
            if row["event"] == "intraday_symbol_evaluated"] == ["SPY", "QQQ"]
    assert not any(row["event"] == "intraday_provider_request_failed" for row in payloads)
