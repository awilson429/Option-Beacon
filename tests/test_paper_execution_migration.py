import json
from dataclasses import asdict
from datetime import datetime, timezone

from option_position_tracker import _serialize, position_from_trade
from option_trade_engine import PaperOptionTrade
from optionbeacon.migrations.paper_execution_to_postgres import migrate
from trade_repository import TradeRepository


def test_migration_is_idempotent_and_skips_malformed(tmp_path):
    now = datetime(2026, 8, 3, 18, tzinfo=timezone.utc)
    trade = PaperOptionTrade(
        trade_id="t", source_signal_id="s", created_timestamp=now, ticker="SPY",
        direction="Bullish", underlying_entry_price=1, confidence=95, historical_grade="A",
        scanner_score=95, entry_reason="x", expiration="2026-08-07", strike=1,
        option_type="call", option_symbol="SPY-C", delta=.5, implied_volatility=.2,
        bid=.9, ask=1.1, mid=1, spread_percent=20, open_interest=100, volume=100,
    )
    values = asdict(trade); values["created_timestamp"] = now.isoformat()
    (tmp_path / "paper_option_trades.jsonl").write_text(json.dumps(values) + "\nnot-json\n")
    position = position_from_trade(trade, execution_time=now)
    (tmp_path / "paper_option_positions.json").write_text(json.dumps({"positions": [_serialize(position), {"bad": True}]}))
    repository = TradeRepository(tmp_path / "state.db", database_url="")
    first = migrate(repository=repository, base_path=tmp_path)
    second = migrate(repository=repository, base_path=tmp_path)
    assert first["final_counts"]["positions"] == 1
    assert first["malformed"] == 2
    assert second["duplicates"] >= 2
