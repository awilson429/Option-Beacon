from datetime import datetime, timedelta, timezone

import pytest

from open_trade_quotes import (
    enrich_open_trade_prices,
    open_trade_symbols,
)
from signal_history import create_trade_record
from trade_journal_dashboard import active_edge_analytics, opened_alerts_analytics


NOW = datetime(2026, 7, 28, 16, 0, tzinfo=timezone.utc)


def record(symbol="NVDA", *, direction="Bullish", closed=False):
    outcome = create_trade_record(
        symbol=symbol,
        direction=direction,
        setup=f"{direction} setup",
        confidence=80,
        entry=100,
        stop=95 if direction == "Bullish" else 105,
        target_1=110 if direction == "Bullish" else 90,
        target_2=120 if direction == "Bullish" else 80,
        timestamp=NOW - timedelta(minutes=35),
        entry_time=NOW - timedelta(minutes=30),
    )
    if closed:
        outcome.exit_time = NOW
        outcome.exit_reason = "TARGET_1"
        outcome.realized_return = 10
    return outcome


def test_open_symbol_absent_from_scanner_is_added_to_quote_request():
    requested = []

    def fetch(symbol):
        requested.append(symbol)
        return {"price": 102}, "Finnhub quote"

    prices, status = enrich_open_trade_prices([record()], {}, fetch)

    assert requested == ["NVDA"]
    assert prices["NVDA"] == 102
    assert status == {}


def test_existing_scanner_price_is_reused_without_request():
    def unexpected_fetch(symbol):
        raise AssertionError(f"unexpected quote request for {symbol}")

    prices, status = enrich_open_trade_prices(
        [record()],
        {"NVDA": {"price": 103}},
        unexpected_fetch,
    )

    assert prices == {"NVDA": 103}
    assert status == {}


def test_multiple_open_trades_for_same_symbol_request_one_quote():
    requested = []

    def fetch(symbol):
        requested.append(symbol)
        return {"price": 102}, "Finnhub quote"

    enrich_open_trade_prices([record(), record()], {}, fetch)

    assert requested == ["NVDA"]


def test_closed_trade_is_not_added_to_quote_watchlist():
    closed = record(closed=True)

    assert open_trade_symbols([closed]) == set()
    prices, status = enrich_open_trade_prices(
        [closed],
        {},
        lambda symbol: (_ for _ in ()).throw(AssertionError(symbol)),
    )
    assert prices == {}
    assert status == {}


def test_fetched_quote_populates_active_edge_and_coach_fields():
    prices, status = enrich_open_trade_prices(
        [record()],
        {},
        lambda symbol: ({"price": 105}, "Finnhub quote"),
    )

    active = active_edge_analytics([record()], prices, NOW, status)

    assert active["rows"][0]["Current Price"] == "$105.00"
    assert active["rows"][0]["Open Return"] == "+5.00%"
    assert active["rows"][0]["Target 1 Progress"] == "50.00%"
    assert active["rows"][0]["Risk Remaining"] == "200.00%"
    assert active["rows"][0]["Coach Status"] == "HOLD"


def test_fetched_quote_populates_opened_alerts():
    prices, status = enrich_open_trade_prices(
        [record()],
        {},
        lambda symbol: ({"price": 105}, "Finnhub quote"),
    )

    row = opened_alerts_analytics([record()], prices, NOW, status)["rows"][0]

    assert row["Current Price"] == "$105.00"
    assert row["Open Return"] == "+5.00%"
    assert row["Coach Status"] == "HOLD"


def test_quote_failure_keeps_trade_visible_and_logs_warning(caplog):
    prices, status = enrich_open_trade_prices(
        [record()],
        {},
        lambda symbol: (None, "provider timeout"),
    )

    active = active_edge_analytics([record()], prices, NOW, status)
    row = active["rows"][0]

    assert active["open_positions"] == 1
    assert row["Current Price"] == "—"
    assert row["Open Return"] == "—"
    assert row["Coach Status"] == "UNAVAILABLE"
    assert row["Quote Status"] == "Live quote unavailable"
    assert "Live quote unavailable for NVDA: provider timeout" in caplog.text


def test_quote_exception_does_not_crash():
    def fail(symbol):
        raise RuntimeError("provider unavailable")

    prices, status = enrich_open_trade_prices([record()], {}, fail)

    assert prices == {}
    assert status == {"NVDA": "Live quote unavailable"}


@pytest.mark.parametrize(
    ("direction", "price", "expected"),
    [
        ("Bullish", 102, 2),
        ("Bearish", 98, 2),
    ],
)
def test_direction_aware_returns_remain_unchanged(direction, price, expected):
    trade = record(direction=direction)
    active = active_edge_analytics([trade], {"NVDA": price}, NOW)

    assert active["average_open_return"] == expected
