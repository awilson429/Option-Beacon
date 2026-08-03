from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

import paper_execution
from execution_config import ExecutionConfig
from execution_risk import daily_risk_state, evaluate_execution
from option_position_tracker import (
    OptionPositionStore,
    open_position_rows,
    position_from_trade,
    update_position,
)
from option_trade_engine import PaperOptionTrade


NOW = datetime(2026, 8, 3, 18, 0, tzinfo=timezone.utc)  # 2 PM ET


def trade(trade_id="t1", price=1.0):
    return PaperOptionTrade(
        trade_id=trade_id, source_signal_id=trade_id, created_timestamp=NOW - timedelta(hours=1),
        ticker="SPY", direction="Bullish", underlying_entry_price=628, confidence=95,
        historical_grade="A", scanner_score=95, entry_reason="test", expiration="2026-08-07",
        strike=628, option_type="call", option_symbol="SPY260807C00628000", delta=.5,
        implied_volatility=.2, bid=price * .9, ask=price * 1.1, mid=price,
        spread_percent=20, open_interest=500, volume=100,
    )


def result(score=95):
    return {"symbol": "SPY", "score": score, "confidence": score}


def config(**changes):
    return replace(ExecutionConfig(), trading_enabled=True, min_open_interest=0, **changes)


def open_position(trade_id="t1", **kwargs):
    return position_from_trade(trade(trade_id), execution_time=NOW - timedelta(minutes=10), **kwargs)


def test_sizing_and_dollar_limit():
    decision = evaluate_execution(result(), trade(price=1.0), [], config(), now=NOW)
    assert decision.eligible and decision.position_size == 2 and decision.maximum_cost == 210
    rejected = evaluate_execution(result(), trade(price=3.0), [], config(), now=NOW)
    assert rejected.reason == "CONTRACT_TOO_EXPENSIVE"


def test_duplicate_and_position_limits():
    position = open_position()
    assert evaluate_execution(result(), trade(), [position], config(max_open_positions=2), now=NOW).reason == "DUPLICATE_SIGNAL"
    assert evaluate_execution(result(), trade("t2"), [position], config(), now=NOW).reason == "MAX_OPEN_POSITIONS"


def test_daily_trade_limit_survives_reload(tmp_path):
    store = OptionPositionStore(tmp_path / "positions.json")
    store.save([open_position()])
    restored = store.load()
    assert daily_risk_state(restored, NOW).trades_entered == 1
    assert evaluate_execution(result(), trade("t2"), restored, config(max_open_positions=2, max_trades_per_day=1), now=NOW).reason == "DAILY_TRADE_LIMIT"


def closed_loss(trade_id="loss", minutes_ago=10):
    position = open_position(trade_id)
    return replace(position, status="CLOSED", exit_time=NOW - timedelta(minutes=minutes_ago), exit_mid=.5, exit_return_percent=-50)


def test_daily_loss_consecutive_loss_and_cooldown():
    losses = [closed_loss("l1", 20), closed_loss("l2", 10)]
    assert evaluate_execution(result(), trade("new"), losses, config(max_daily_loss_dollars=40, max_consecutive_losses=9), now=NOW).reason == "DAILY_LOSS_LIMIT"
    assert evaluate_execution(result(), trade("new"), losses, config(max_daily_loss_dollars=1000), now=NOW).reason == "CONSECUTIVE_LOSS_LIMIT"
    one = [closed_loss()]
    assert evaluate_execution(result(), trade("new"), one, config(max_consecutive_losses=9), now=NOW).reason == "LOSS_COOLDOWN"


def test_entry_time_is_execution_time_immutable_and_formats_et():
    entered = NOW - timedelta(minutes=18)
    position = position_from_trade(trade(), execution_time=entered, fill_price=1.05, quantity=2, scanner_score=94)
    updated = update_position(position, {"bid": 1.1, "ask": 1.2}, current_time=NOW)
    assert updated.entry_time == entered
    assert updated.quantity == 2 and updated.total_entry_cost == 210
    assert "1:42 PM ET" in open_position_rows([updated], NOW)[0]["Trade Entered"]


@pytest.mark.parametrize("quote,reason", [({"bid": .4, "ask": .6}, "STOP_LOSS"), ({"bid": 1.5, "ask": 1.6}, "PROFIT_TARGET")])
def test_price_exits(quote, reason):
    assert update_position(open_position(), quote, current_time=NOW).exit_reason == reason


def test_max_hold_and_eod_exits():
    old = replace(open_position(), entry_time=NOW - timedelta(minutes=121))
    assert update_position(old, None, current_time=NOW, max_hold_minutes=120).exit_reason == "MAX_HOLD_TIME"
    near_close = datetime(2026, 8, 3, 19, 55, tzinfo=timezone.utc)
    assert update_position(open_position(), None, current_time=near_close, force_close_end_of_day=True).exit_reason == "END_OF_DAY"


def test_missing_quote_and_malformed_row_are_safe(tmp_path):
    position = open_position()
    assert update_position(position, None, current_time=NOW) == position
    path = tmp_path / "positions.json"
    store = OptionPositionStore(path)
    store.save([position])
    text = path.read_text()
    path.write_text(text.replace('"positions": [', '"positions": [{"bad": true},'))
    restored = store.load()
    assert len(restored) == 1 and restored[0].trade_id == position.trade_id


def test_execution_service_does_not_duplicate(monkeypatch, tmp_path):
    selected = trade()
    monkeypatch.setattr(paper_execution, "capture_qualified_signal", lambda *args, **kwargs: selected)
    store = OptionPositionStore(tmp_path / "positions.json")
    journal = paper_execution.ExecutionJournal(tmp_path / "journal.jsonl")
    kwargs = dict(config=config(), now=NOW, chain_provider=object(), quote_provider=NoQuotes(),
                  position_store=store, journal=journal)
    first = paper_execution.run_paper_execution([result()], **kwargs)
    second = paper_execution.run_paper_execution([result()], **kwargs)
    assert len(first["opened"]) == 1 and not second["opened"]
    assert len(store.load()) == 1 and second["decisions"][0].reason == "DUPLICATE_SIGNAL"


class NoQuotes:
    def quote(self, symbol):
        return None, "missing"
