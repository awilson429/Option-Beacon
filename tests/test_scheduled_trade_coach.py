from pathlib import Path

from scheduled_trade_coach import run_active_trade_coaching
from trade_storage import (
    create_position,
    load_recommendations,
    update_position_premium,
)


def spy_context(price=102):
    return {
        "symbol": "SPY",
        "signal": "BULLISH SETUP",
        "price": price,
        "vwap": 101,
        "ema20": 101,
        "ema50": 100,
        "relative_volume": 1.2,
        "macd_hist": 0.1,
        "rsi": 55,
    }


def create_spy_trade(db_file):
    return create_position(
        symbol="SPY",
        direction="Bullish",
        option_type="CALL",
        strike=600,
        expiration="2026-08-21",
        entry_premium=4.0,
        contracts=1,
        entry_underlying_price=101,
        current_stop=99,
        target_1=104,
        target_2=106,
        target_3=108,
        original_plan={"trigger_price": 101},
        db_file=str(db_file),
    )


def test_scheduled_trade_coach_records_recommendations(tmp_path):
    db_file = Path(tmp_path) / "trades.db"
    position_id = create_spy_trade(db_file)

    rows = run_active_trade_coaching(
        latest_results={"SPY": spy_context()},
        db_file=str(db_file),
        alerts_enabled=False,
    )

    recommendations = load_recommendations(position_id, db_file=str(db_file))

    assert len(rows) == 1
    assert rows[0]["symbol"] == "SPY"
    assert rows[0]["coach_action"] == "Hold"
    assert len(recommendations) == 1


def test_scheduled_trade_coach_logs_action_change(tmp_path):
    db_file = Path(tmp_path) / "trades.db"
    position_id = create_spy_trade(db_file)
    run_active_trade_coaching(
        latest_results={"SPY": spy_context()},
        db_file=str(db_file),
        alerts_enabled=False,
    )
    update_position_premium(position_id, 5.25, db_file=str(db_file))

    rows = run_active_trade_coaching(
        latest_results={"SPY": spy_context()},
        db_file=str(db_file),
        alerts_enabled=False,
    )

    recommendations = load_recommendations(position_id, db_file=str(db_file))

    assert rows[0]["previous_action"] == "Hold"
    assert rows[0]["coach_action"] == "Take first partial profit"
    assert len(recommendations) == 2
