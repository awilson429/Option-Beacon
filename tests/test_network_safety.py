import os

import pytest

import finnhub_universe
import optionbeacon_live
from option_trade_engine import TradierOptionChainProvider
from trade_repository import TradeRepository


def test_default_suite_clears_production_configuration(tmp_path):
    assert os.getenv("DATABASE_URL") is None
    assert os.getenv("TRADIER_ACCESS_TOKEN") is None
    assert os.getenv("FINNHUB_API_KEY") is None
    repository = TradeRepository(tmp_path / "isolated.db")
    assert repository.backend == "sqlite"


def test_default_suite_blocks_market_provider_networks():
    with pytest.raises(AssertionError, match="Tradier"):
        TradierOptionChainProvider().expirations("SPY")
    with pytest.raises(AssertionError, match="Yahoo/yfinance"):
        optionbeacon_live.download_data("SPY", "5d")
    with pytest.raises(AssertionError, match="Finnhub"):
        finnhub_universe.urlopen("https://example.invalid")


def test_default_suite_blocks_neon_connection():
    with pytest.raises(Exception) as error:
        TradeRepository(database_url="postgresql://test.invalid/db")
    assert "password" not in str(error.value).lower()
