import json
from datetime import datetime, timezone

from execution_config import ExecutionConfig
from option_position_tracker import position_from_trade
from option_trade_engine import PaperOptionTrade
from paper_execution_repository import PaperExecutionRepository
from trade_repository import TradeRepository


NOW = datetime(2026, 8, 3, 18, tzinfo=timezone.utc)


def captured():
    return PaperOptionTrade(
        trade_id="trade-1", source_signal_id="signal-1", created_timestamp=NOW,
        ticker="SPY", direction="Bullish", underlying_entry_price=600, confidence=95,
        historical_grade="A", scanner_score=95, entry_reason="test", expiration="2026-08-07",
        strike=600, option_type="call", option_symbol="SPY-C", delta=.5,
        implied_volatility=.2, bid=.9, ask=1.1, mid=1, spread_percent=20,
        open_interest=100, volume=100,
    )


def test_sql_repository_restores_positions_and_deduplicates(tmp_path):
    repository = PaperExecutionRepository(TradeRepository(tmp_path / "state.db", database_url=""))
    trade = repository.append_once(captured())
    assert repository.append_once(captured()).trade_id == trade.trade_id
    position = position_from_trade(trade, execution_time=NOW, fill_price=1.05, quantity=2)
    repository.save([position])
    restarted = PaperExecutionRepository(TradeRepository(tmp_path / "state.db", database_url=""))
    assert len(restarted.get_open_positions()) == 1
    assert restarted.get_open_positions()[0].total_entry_cost == 210
    assert restarted.counts() == {"positions": 1, "trades": 1, "journal": 0}


def test_closed_trade_is_persisted_once(tmp_path):
    from dataclasses import replace
    repository = PaperExecutionRepository(TradeRepository(tmp_path / "state.db", database_url=""))
    trade = repository.append_once(captured())
    position = position_from_trade(trade, execution_time=NOW, fill_price=1, quantity=1)
    closed = replace(position, status="CLOSED", exit_time=NOW, exit_mid=1.5,
                     exit_return_percent=50, exit_reason="PROFIT_TARGET")
    repository.save([closed])
    repository.save([closed])
    assert len(repository.get_trade_history()) == 1
    with repository.repository.connection() as connection:
        row = repository.repository._fetchone(connection, "SELECT realized_pnl_dollars,exit_reason FROM paper_execution_trades WHERE trade_id=?", (trade.trade_id,))
    assert row == {"realized_pnl_dollars": 50.0, "exit_reason": "PROFIT_TARGET"}


def test_execution_disabled_by_default_and_unsupported_modes_rejected():
    assert not ExecutionConfig.from_environment({}).trading_enabled
    assert ExecutionConfig.from_environment({"OPTIONBEACON_EXECUTION_MODE": "AUTO"}).mode == "AUTO"


def test_ui_source_reads_sql_and_does_not_refresh_lifecycle():
    from pathlib import Path
    source = Path("app.py").read_text(encoding="utf-8")
    assert "PaperExecutionRepository" in source
    assert "OptionPositionStore().load()" not in source
    assert "refresh_option_positions_safely" not in source
