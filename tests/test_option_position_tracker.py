from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from option_position_tracker import (
    OptionPositionStore,
    completed_position_rows,
    normalize_live_quote,
    open_position_rows,
    option_return_percent,
    position_from_trade,
    refresh_option_positions,
    update_position,
)
from option_trade_engine import OptionTradeLedger, PaperOptionTrade


NOW = datetime(2026, 7, 28, 15, 0, tzinfo=timezone.utc)


def trade(*, trade_id="trade-1", symbol="SPY_CALL", expiration="2026-08-07"):
    return PaperOptionTrade(
        trade_id=trade_id,
        source_signal_id=f"signal-{trade_id}",
        created_timestamp=NOW - timedelta(minutes=30),
        ticker="SPY",
        direction="Bullish",
        underlying_entry_price=500,
        confidence=80,
        historical_grade="POSITIVE",
        scanner_score=82,
        entry_reason="Qualified",
        expiration=expiration,
        strike=500,
        option_type="call",
        option_symbol=symbol,
        delta=0.5,
        implied_volatility=0.25,
        bid=4.9,
        ask=5.1,
        mid=5,
        spread_percent=4,
        open_interest=1000,
        volume=500,
    )


class Provider:
    def __init__(self, quote=None, error=""):
        self.value = quote if quote is not None else {"bid": 5.4, "ask": 5.6}
        self.error = error
        self.calls = []

    def quote(self, symbol):
        self.calls.append(symbol)
        return self.value, self.error


def position():
    return position_from_trade(trade())


def test_quote_update_and_return_calculation():
    updated = update_position(
        position(),
        {"bid": 5.4, "ask": 5.6, "underlying_price": 502},
        current_time=NOW,
        profit_target_percent=100,
    )
    assert updated.current_mid == 5.5
    assert updated.current_return_percent == 10
    assert updated.last_underlying_price == 502
    assert updated.last_option_quote_time == NOW


def test_missing_quote_and_market_closed_leave_position_unchanged(tmp_path):
    original = position()
    assert update_position(original, None, current_time=NOW) == original
    store = OptionPositionStore(tmp_path / "positions.json")
    store.save([original])
    updated = refresh_option_positions(
        position_store=store,
        trade_ledger=OptionTradeLedger(tmp_path / "missing-ledger.jsonl"),
        provider=Provider(error="market closed"),
        current_time=NOW,
    )
    assert updated == [original]


def test_expired_contract_closes_without_quote():
    original = position_from_trade(trade(expiration="2026-07-27"))
    expired = update_position(original, None, current_time=NOW)
    assert expired.status == "EXPIRED"
    assert expired.exit_reason == "EXPIRATION"
    assert expired.exit_mid == original.current_mid


def test_zero_midpoint_is_rejected_and_divide_by_zero_is_safe():
    assert normalize_live_quote({"bid": 0, "ask": 0}) is None
    assert option_return_percent(0, 5) is None
    assert option_return_percent(None, 5) is None


def test_mfe_and_mae_preserve_prior_extremes():
    favorable = update_position(
        position(),
        {"bid": 5.9, "ask": 6.1},
        current_time=NOW,
        profit_target_percent=100,
    )
    adverse = update_position(
        favorable,
        {"bid": 3.9, "ask": 4.1},
        current_time=NOW + timedelta(minutes=5),
        profit_target_percent=100,
        stop_loss_percent=-100,
    )
    recovered = update_position(
        adverse,
        {"bid": 4.9, "ask": 5.1},
        current_time=NOW + timedelta(minutes=10),
        profit_target_percent=100,
        stop_loss_percent=-100,
    )
    assert favorable.max_favorable_excursion_percent == 20
    assert adverse.max_adverse_excursion_percent == -20
    assert recovered.max_favorable_excursion_percent == 20
    assert recovered.max_adverse_excursion_percent == -20
    assert recovered.highest_mid == 6
    assert recovered.lowest_mid == 4


def test_profit_target_and_stop_loss_close_and_freeze():
    winner = update_position(
        position(),
        {"bid": 7.4, "ask": 7.6},
        current_time=NOW,
        profit_target_percent=50,
    )
    assert winner.status == "CLOSED"
    assert winner.exit_reason == "PROFIT_TARGET"
    assert winner.exit_return_percent == 50
    assert update_position(
        winner, {"bid": 9, "ask": 10}, current_time=NOW + timedelta(minutes=1)
    ) == winner

    loser = update_position(
        position(),
        {"bid": 3.4, "ask": 3.6},
        current_time=NOW,
        stop_loss_percent=-30,
    )
    assert loser.status == "CLOSED"
    assert loser.exit_reason == "STOP_LOSS"
    assert loser.exit_return_percent == -30


def test_position_persistence_and_reload(tmp_path):
    store = OptionPositionStore(tmp_path / "positions.json")
    original = position()
    store.save([original])
    assert store.load() == [original]


def test_refresh_synchronizes_multiple_positions_and_deduplicates_quotes(tmp_path):
    ledger = OptionTradeLedger(tmp_path / "trades.jsonl")
    ledger.append_once(trade(trade_id="one", symbol="SAME"))
    ledger.append_once(trade(trade_id="two", symbol="SAME"))
    provider = Provider()
    positions = refresh_option_positions(
        position_store=OptionPositionStore(tmp_path / "positions.json"),
        trade_ledger=ledger,
        provider=provider,
        current_time=NOW,
        profit_target_percent=100,
    )
    assert len(positions) == 2
    assert provider.calls == ["SAME"]
    assert all(item.current_return_percent == 10 for item in positions)


def test_closed_positions_are_not_quoted(tmp_path):
    closed = replace(
        position(),
        status="CLOSED",
        exit_time=NOW,
        exit_reason="PROFIT_TARGET",
        exit_mid=7.5,
        exit_return_percent=50,
    )
    store = OptionPositionStore(tmp_path / "positions.json")
    store.save([closed])
    provider = Provider()
    refreshed = refresh_option_positions(
        position_store=store,
        trade_ledger=OptionTradeLedger(tmp_path / "missing.jsonl"),
        provider=provider,
        current_time=NOW,
    )
    assert refreshed == [closed]
    assert provider.calls == []


def test_open_and_completed_display_rows():
    original = position()
    closed = replace(
        original,
        trade_id="closed",
        status="CLOSED",
        exit_time=NOW,
        exit_reason="PROFIT_TARGET",
        exit_mid=7.5,
        exit_return_percent=50,
    )
    assert open_position_rows([original, closed], NOW)[0]["Current Return"] == "0.00%"
    completed = completed_position_rows([original, closed])
    assert completed[0]["Return"] == "+50.00%"
    assert completed[0]["Reason"] == "PROFIT_TARGET"
