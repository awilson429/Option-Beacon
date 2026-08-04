from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from execution_config import ExecutionConfig
from execution_risk import evaluate_execution
from option_position_tracker import position_from_trade, update_position
from option_trade_engine import PaperOptionTrade
from paper_execution import paper_account_summary
from paper_trading_page import paper_execution_funnel


NOW = datetime(2026, 8, 4, 18, 0, tzinfo=timezone.utc)


def broad(**overrides):
    values = {
        "PAPER_SIMULATION_PROFILE": "BROAD",
        "OPTIONBEACON_EXECUTION_MODE": "PAPER",
        "OPTIONBEACON_TRADING_ENABLED": "true",
    }
    values.update(overrides)
    return ExecutionConfig.from_environment(values)


def result(score=40, trade_id="entry-1"):
    return {
        "_authoritative_entry_id": trade_id,
        "timestamp": (NOW - timedelta(minutes=5)).isoformat(),
        "symbol": "SPY",
        "score": score,
        "confidence": 80,
    }


def trade(trade_id="trade-1", **overrides):
    values = {
        "trade_id": trade_id,
        "source_signal_id": trade_id,
        "created_timestamp": NOW,
        "ticker": "SPY",
        "direction": "Bullish",
        "underlying_entry_price": 600,
        "confidence": 80,
        "historical_grade": "A",
        "scanner_score": 40,
        "entry_reason": "authoritative",
        "expiration": "2026-08-14",
        "strike": 600,
        "option_type": "call",
        "option_symbol": f"SPY-{trade_id}",
        "delta": .5,
        "implied_volatility": .2,
        "bid": .9,
        "ask": 1.1,
        "mid": 1,
        "spread_percent": 20,
        "open_interest": 100,
        "volume": 1,
    }
    values.update(overrides)
    return PaperOptionTrade(**values)


def opened(trade_id="trade-1", *, cost=200, entered=NOW - timedelta(minutes=10)):
    item = position_from_trade(
        trade(trade_id), execution_time=entered,
        fill_price=cost / 200, quantity=2,
    )
    return item


def test_broad_profile_implements_approved_values_and_safe_defaults_remain():
    config = broad()
    assert config.simulation_profile == "BROAD"
    assert config.account_size == 5000
    assert config.min_beacon_score == 40
    assert config.max_open_positions == 5
    assert config.max_trades_per_day == 20
    assert config.max_dollars_per_trade == 250
    assert config.max_total_deployed_capital == 1250
    assert config.max_daily_loss_dollars == 100
    assert config.max_consecutive_losses == 0
    assert config.loss_cooldown_minutes == 0
    assert config.max_spread_percent == 20
    assert config.min_open_interest == 50
    assert config.min_volume == 0
    assert config.stop_loss_percent == -30
    assert config.profit_target_percent == 50
    assert config.max_hold_minutes == 120
    assert config.force_close_end_of_day

    safe = ExecutionConfig.from_environment({})
    assert safe.simulation_profile == "SAFE"
    assert safe.min_beacon_score == 92
    assert safe.max_open_positions == 1
    assert safe.max_trades_per_day == 3
    assert safe.max_consecutive_losses == 2
    assert safe.loss_cooldown_minutes == 30


def test_broad_score_boundary_and_non_paper_mode():
    assert evaluate_execution(result(40), trade(), [], broad(), now=NOW).eligible
    assert evaluate_execution(result(39), trade(), [], broad(), now=NOW).reason == "SCORE_TOO_LOW"
    non_paper = replace(broad(), mode="AUTO")
    assert evaluate_execution(result(), trade(), [], non_paper, now=NOW).reason == "MODE_NOT_CONFIGURED"


@pytest.mark.parametrize(("changes", "reason"), [
    ({"spread_percent": 20.01}, "SPREAD_TOO_WIDE"),
    ({"open_interest": 49}, "INSUFFICIENT_OPEN_INTEREST"),
    ({"volume": 0}, "INSUFFICIENT_VOLUME"),
    ({"mid": None}, "CONTRACT_QUOTE_UNAVAILABLE"),
    ({"status": "DATA_UNAVAILABLE", "entry_snapshot_complete": False,
      "data_unavailable_reason": "No valid option contract available."}, "NO_VALID_CONTRACT"),
])
def test_distinct_contract_rejection_reasons(changes, reason):
    config = replace(broad(), min_volume=1)
    assert evaluate_execution(result(), trade(**changes), [], config, now=NOW).reason == reason


def test_broad_buying_power_position_duplicate_and_disabled_loss_stops():
    config = broad()
    positions = [opened(f"open-{index}", cost=250) for index in range(5)]
    assert evaluate_execution(
        result(trade_id="next"), trade("next"), positions,
        replace(config, max_open_positions=10), now=NOW,
    ).reason == "INSUFFICIENT_BUYING_POWER"
    assert evaluate_execution(
        result(trade_id="next"), trade("next"), positions, config, now=NOW,
    ).reason == "MAX_OPEN_POSITIONS"
    assert evaluate_execution(
        result(trade_id="open-1"), trade("open-1"), positions, config, now=NOW,
    ).reason == "DUPLICATE_SIGNAL"

    losses = [
        replace(opened(f"loss-{index}"), status="CLOSED", exit_time=NOW - timedelta(minutes=index + 1),
                exit_mid=.9, exit_return_percent=-10)
        for index in range(2)
    ]
    assert evaluate_execution(
        result(trade_id="after-loss"), trade("after-loss"), losses,
        replace(config, max_daily_loss_dollars=1000), now=NOW,
    ).eligible


def test_stops_targets_and_eod_management_are_unchanged():
    config = broad()
    position = opened()
    stopped = update_position(
        position, {"bid": .65, "ask": .75}, current_time=NOW,
        stop_loss_percent=config.stop_loss_percent,
        profit_target_percent=config.profit_target_percent,
    )
    targeted = update_position(
        position, {"bid": 1.5, "ask": 1.6}, current_time=NOW,
        stop_loss_percent=config.stop_loss_percent,
        profit_target_percent=config.profit_target_percent,
    )
    eod = update_position(
        position, None, current_time=NOW.replace(hour=19, minute=55),
        force_close_end_of_day=config.force_close_end_of_day,
    )
    assert stopped.exit_reason == "STOP_LOSS"
    assert targeted.exit_reason == "PROFIT_TARGET"
    assert eod.exit_reason == "END_OF_DAY"


def test_performance_metrics_and_daily_funnel_reconcile():
    open_position = opened("open", cost=200)
    open_position = replace(open_position, current_mid=1.2)
    winner = replace(
        opened("winner", cost=100, entered=NOW - timedelta(hours=2)),
        status="CLOSED", exit_time=NOW - timedelta(hours=1),
        exit_mid=.75, exit_return_percent=50,
    )
    loser = replace(
        opened("loser", cost=100, entered=NOW - timedelta(hours=1)),
        status="CLOSED", exit_time=NOW - timedelta(minutes=30),
        exit_mid=.25, exit_return_percent=-50,
    )
    summary = paper_account_summary([open_position, winner, loser], config=broad(), now=NOW)
    assert summary["starting_balance"] == 5000
    assert summary["current_equity"] == pytest.approx(5040)
    assert summary["total_pnl"] == pytest.approx(40)
    assert summary["deployed_capital"] == 200
    assert summary["peak_deployed_capital"] == 200
    assert summary["trades_closed_today"] == 2
    assert summary["wins"] == summary["losses"] == 1
    assert summary["profit_factor"] == 1
    assert summary["max_intraday_drawdown"] == 50

    events = [
        {"event_type": "TRADE_ENTERED", "opportunity_id": name,
         "event_timestamp": NOW.isoformat()}
        for name in ("accepted", "rejected", "pending")
    ]
    captures = [
        SimpleNamespace(trade_id="paper-a", source_signal_id="accepted"),
        SimpleNamespace(trade_id="paper-r", source_signal_id="rejected"),
    ]
    journal = [
        {"trade_id": "paper-a", "created_at": NOW.isoformat(), "accepted": 1, "reason_code": "ELIGIBLE"},
        {"trade_id": "paper-r", "created_at": NOW.isoformat(), "accepted": 0, "reason_code": "SPREAD_TOO_WIDE"},
    ]
    funnel = paper_execution_funnel(events, journal, captures, NOW)
    assert funnel == {
        "authoritative_entries": 3, "evaluated": 2, "opened": 1,
        "rejected": 1, "pending": 1, "participation_rate": pytest.approx(100 / 3),
        "rejection_counts": {"SPREAD_TOO_WIDE": 1}, "reconciled": True,
    }
