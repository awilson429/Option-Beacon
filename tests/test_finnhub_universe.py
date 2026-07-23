import os

from finnhub_universe import (
    DEFAULT_TOP_MOVER_COUNT,
    MARKET_CONTEXT_SYMBOLS,
    MAX_TOP_MOVER_COUNT,
    active_symbol_groups,
    top_mover_count,
)


def test_top_mover_count_uses_default_when_missing():
    original = os.environ.pop("OPTION_BEACON_TOP_MOVER_COUNT", None)
    try:
        assert top_mover_count() == DEFAULT_TOP_MOVER_COUNT
    finally:
        if original is not None:
            os.environ["OPTION_BEACON_TOP_MOVER_COUNT"] = original


def test_top_mover_count_is_capped():
    original = os.environ.get("OPTION_BEACON_TOP_MOVER_COUNT")
    os.environ["OPTION_BEACON_TOP_MOVER_COUNT"] = "500"
    try:
        assert top_mover_count() == MAX_TOP_MOVER_COUNT
    finally:
        if original is None:
            os.environ.pop("OPTION_BEACON_TOP_MOVER_COUNT", None)
        else:
            os.environ["OPTION_BEACON_TOP_MOVER_COUNT"] = original


def test_top_mover_count_has_floor():
    original = os.environ.get("OPTION_BEACON_TOP_MOVER_COUNT")
    os.environ["OPTION_BEACON_TOP_MOVER_COUNT"] = "2"
    try:
        assert top_mover_count() == 10
    finally:
        if original is None:
            os.environ.pop("OPTION_BEACON_TOP_MOVER_COUNT", None)
        else:
            os.environ["OPTION_BEACON_TOP_MOVER_COUNT"] = original


def test_active_symbol_groups_includes_market_context_when_movers_available(monkeypatch):
    def fake_rank_daily_movers(api_key=None):
        return {
            "bullish": [{"symbol": "NVDA"}],
            "bearish": [{"symbol": "JPM"}],
        }, ""

    monkeypatch.setattr("finnhub_universe.load_cached_movers", lambda: None)
    monkeypatch.setattr("finnhub_universe.rank_daily_movers", fake_rank_daily_movers)
    monkeypatch.setattr("finnhub_universe.save_cached_movers", lambda movers: None)

    groups, source, error = active_symbol_groups(api_key="test")

    assert source == "Finnhub daily movers"
    assert error == ""
    assert groups["Market Context"] == MARKET_CONTEXT_SYMBOLS
    assert groups["Top Bullish Movers"] == ["NVDA"]
    assert groups["Top Bearish Movers"] == ["JPM"]
