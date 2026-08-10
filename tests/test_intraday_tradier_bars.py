from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import pytest

import optionbeacon.worker.intraday as worker
import tradier_options
from intraday_strategy import aggregate_bars, detect_candidate, ema, session_vwap


ET = ZoneInfo("America/New_York")
NOW = datetime(2026, 8, 7, 14, 0, tzinfo=ET)


def canonical_rows(count=30):
    start = datetime(2026, 8, 7, 9, 30, tzinfo=ET)
    return [{"timestamp": start + timedelta(minutes=index),
             "open": 600 + index * .1 - .03, "high": 600 + index * .1 + .08,
             "low": 600 + index * .1 - .08, "close": 600 + index * .1,
             "volume": 1000 + index * 20} for index in range(count)]


def tradier_rows(rows):
    return [{"time": row["timestamp"].replace(tzinfo=None).isoformat(),
             "timestamp": int(row["timestamp"].timestamp()), "price": row["close"],
             "open": row["open"], "high": row["high"], "low": row["low"],
             "close": row["close"], "volume": row["volume"],
             "vwap": 1.0} for row in rows]


@pytest.mark.parametrize("symbol", ["SPY", "QQQ"])
def test_tradier_one_minute_bars_normalize_to_canonical_schema(monkeypatch, symbol):
    expected = canonical_rows(2)
    monkeypatch.setattr(worker, "time_sales",
                        lambda *args, **kwargs: (tradier_rows(expected), ""))

    actual = worker.tradier_minute_bars(symbol, now=NOW)

    assert actual == [{**row, "open": float(row["open"]), "high": float(row["high"]),
                       "low": float(row["low"]), "close": float(row["close"]),
                       "volume": float(row["volume"])} for row in expected]
    assert all(row["timestamp"].tzinfo == ET for row in actual)


def test_tradier_request_uses_shared_transport_and_regular_session(monkeypatch):
    captured = {}
    provider_calls = []

    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def read(self): return b'{"series":{"data":[]}}'

    monkeypatch.setattr(tradier_options, "_secret_value",
                        lambda name: "TOKEN" if name == tradier_options.TOKEN_ENV_NAME
                        else "https://api.tradier.test/v1")
    def respond(request, timeout):
        captured["request"] = request
        return Response()
    monkeypatch.setattr(tradier_options, "urlopen", respond)
    monkeypatch.setattr(tradier_options, "record_provider_call",
                        lambda *args, **kwargs: provider_calls.append((args, kwargs)))

    rows, error = tradier_options.time_sales(
        "SPY", "2026-08-07 09:30", "2026-08-07 14:00"
    )

    request = captured["request"]
    query = parse_qs(urlparse(request.full_url).query)
    assert rows == [] and error == ""
    assert urlparse(request.full_url).path == "/v1/markets/timesales"
    assert query == {"symbol": ["SPY"], "interval": ["1min"],
                     "start": ["2026-08-07 09:30"], "end": ["2026-08-07 14:00"],
                     "session_filter": ["open"]}
    assert request.get_header("Authorization") == "Bearer TOKEN"
    assert "TOKEN" not in request.full_url
    assert provider_calls[0][0][:2] == ("Tradier", "minute_bars")
    assert provider_calls[0][1]["success"] is True


def test_tradier_normalization_preserves_aggregation_vwap_ema_and_candidate(monkeypatch):
    canonical = canonical_rows()
    canonical[-2]["close"] = 599
    canonical[-1].update(open=599, low=598.9, high=603.2, close=603.1, volume=5000)
    monkeypatch.setattr(worker, "time_sales",
                        lambda *args, **kwargs: (tradier_rows(canonical), ""))
    normalized = worker.tradier_minute_bars("SPY", now=NOW)

    assert aggregate_bars(normalized, 3) == aggregate_bars(canonical, 3)
    assert aggregate_bars(normalized, 5) == aggregate_bars(canonical, 5)
    assert session_vwap(normalized) == pytest.approx(session_vwap(canonical))
    assert ema([row["close"] for row in normalized], 9) == pytest.approx(
        ema([row["close"] for row in canonical], 9))
    assert ema([row["close"] for row in normalized], 21) == pytest.approx(
        ema([row["close"] for row in canonical], 21))
    assert detect_candidate("SPY", normalized, normalized) == detect_candidate(
        "SPY", canonical, canonical)
    opening_normalized = normalized[:15]
    opening_canonical = canonical[:15]
    assert (max(row["high"] for row in opening_normalized),
            min(row["low"] for row in opening_normalized)) == (
        max(row["high"] for row in opening_canonical),
        min(row["low"] for row in opening_canonical))


@pytest.mark.parametrize("error,status,exception_class", [
    ("Tradier request failed: HTTP Error 403: Forbidden", 403, "HTTPError"),
    ("Tradier request failed: HTTP Error 429: Too Many Requests", 429, "HTTPError"),
    ("Tradier request failed: operation timed out", None, "TimeoutError"),
])
def test_tradier_minute_bar_failures_are_classified(
        monkeypatch, error, status, exception_class):
    monkeypatch.setattr(worker, "time_sales", lambda *args, **kwargs: ([], error))

    with pytest.raises(worker.ProviderRequestFailure) as raised:
        worker.tradier_minute_bars("SPY", now=NOW)

    assert raised.value.provider == "Tradier"
    assert raised.value.stage == "minute_bars"
    assert raised.value.endpoint_path == "/markets/timesales"
    assert raised.value.http_status == status
    assert raised.value.exception_class == exception_class


@pytest.mark.parametrize("rows", [[], [{}], [{"timestamp": 1}]])
def test_missing_or_malformed_tradier_bars_fail_closed(monkeypatch, rows):
    monkeypatch.setattr(worker, "time_sales", lambda *args, **kwargs: (rows, ""))

    with pytest.raises(worker.ProviderRequestFailure):
        worker.tradier_minute_bars("QQQ", now=NOW)


def test_provider_replacement_is_intraday_only():
    intraday = Path("optionbeacon/worker/intraday.py").read_text(encoding="utf-8")
    broad = Path("optionbeacon/worker/scan_once.py").read_text(encoding="utf-8")

    assert "finnhub" not in intraday.lower()
    assert "time_sales" in intraday
    assert "from finnhub_universe import active_symbol_groups" in broad
