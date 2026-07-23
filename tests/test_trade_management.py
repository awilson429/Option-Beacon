from trade_management import coach_recommendation, trade_summary


def test_exit_score_flags_stop_loss():
    position = {
        "direction": "Bullish",
        "option_type": "CALL",
        "current_stop": 99,
        "target_1": 104,
        "target_2": 106,
        "entry_premium": 4,
    }
    scanner_result = {
        "price": 98.75,
        "vwap": 100,
        "ema20": 100,
        "ema50": 101,
        "relative_volume": 0.7,
        "macd_hist": -0.1,
        "rsi": 42,
    }

    recommendation = coach_recommendation(position, scanner_result)

    assert recommendation["exit_score"] >= 75
    assert recommendation["coach_action"] in ["Strong exit warning", "Exit"]


def test_exit_score_holds_clean_trade():
    position = {
        "direction": "Bullish",
        "option_type": "CALL",
        "current_stop": 99,
        "target_1": 104,
        "target_2": 106,
        "entry_underlying_price": 101,
        "entry_premium": 4,
    }
    scanner_result = {
        "price": 102,
        "vwap": 101,
        "ema20": 101,
        "ema50": 100,
        "relative_volume": 1.2,
        "macd_hist": 0.1,
        "rsi": 55,
    }

    recommendation = coach_recommendation(position, scanner_result)

    assert recommendation["exit_score"] < 25
    assert recommendation["coach_action"] == "Hold"


def test_trade_coach_recommends_partial_profit_at_30_percent():
    position = {
        "direction": "Bullish",
        "option_type": "CALL",
        "current_stop": 99,
        "target_1": 104,
        "target_2": 106,
        "entry_underlying_price": 101,
        "entry_premium": 4,
        "current_premium": 5.25,
        "peak_premium": 5.25,
    }
    scanner_result = {
        "price": 102,
        "vwap": 101,
        "ema20": 101,
        "ema50": 100,
        "relative_volume": 1.2,
        "macd_hist": 0.1,
        "rsi": 55,
    }

    recommendation = coach_recommendation(position, scanner_result)

    assert recommendation["coach_action"] == "Take first partial profit"
    assert recommendation["current_profit_percent"] == 31.25
    assert recommendation["suggested_stop"] == 101


def test_trade_coach_recommends_second_partial_after_first_taken():
    position = {
        "direction": "Bullish",
        "option_type": "CALL",
        "current_stop": 99,
        "target_1": 104,
        "target_2": 106,
        "entry_underlying_price": 101,
        "entry_premium": 4,
        "current_premium": 6.1,
        "peak_premium": 6.1,
        "partial_1_taken": 1,
        "partial_2_taken": 0,
    }
    scanner_result = {
        "price": 102,
        "vwap": 101,
        "ema20": 101,
        "ema50": 100,
        "relative_volume": 1.2,
        "macd_hist": 0.1,
        "rsi": 55,
    }

    recommendation = coach_recommendation(position, scanner_result)

    assert recommendation["coach_action"] == "Take second partial profit"
    assert recommendation["suggested_stop"] == 104


def test_trade_coach_trails_after_both_partials_taken():
    position = {
        "direction": "Bullish",
        "option_type": "CALL",
        "current_stop": 99,
        "target_1": 104,
        "target_2": 106,
        "entry_underlying_price": 101,
        "entry_premium": 4,
        "current_premium": 6.1,
        "peak_premium": 6.1,
        "partial_1_taken": 1,
        "partial_2_taken": 1,
    }
    scanner_result = {
        "price": 102,
        "vwap": 101,
        "ema20": 101,
        "ema50": 100,
        "relative_volume": 1.2,
        "macd_hist": 0.1,
        "rsi": 55,
    }

    recommendation = coach_recommendation(position, scanner_result)

    assert recommendation["coach_action"] == "Trail remaining position"
    assert recommendation["suggested_stop"] == 106


def test_trade_coach_lowers_stop_for_bearish_winners():
    position = {
        "direction": "Bearish",
        "option_type": "PUT",
        "current_stop": 103,
        "target_1": 98,
        "target_2": 96,
        "entry_underlying_price": 101,
        "entry_premium": 4,
        "current_premium": 6.1,
        "peak_premium": 6.1,
        "partial_1_taken": 1,
        "partial_2_taken": 0,
    }
    scanner_result = {
        "price": 97,
        "vwap": 99,
        "ema20": 99,
        "ema50": 100,
        "relative_volume": 1.2,
        "macd_hist": -0.1,
        "rsi": 42,
    }

    recommendation = coach_recommendation(position, scanner_result)

    assert recommendation["coach_action"] == "Take second partial profit"
    assert recommendation["suggested_stop"] == 98


def test_trade_coach_flags_peak_profit_giveback():
    position = {
        "direction": "Bullish",
        "option_type": "CALL",
        "current_stop": 99,
        "target_1": 104,
        "target_2": 106,
        "entry_underlying_price": 101,
        "entry_premium": 4,
        "current_premium": 5.2,
        "peak_premium": 6.4,
    }
    scanner_result = {
        "price": 102,
        "vwap": 101,
        "ema20": 101,
        "ema50": 100,
        "relative_volume": 1.2,
        "macd_hist": 0.1,
        "rsi": 55,
    }

    recommendation = coach_recommendation(position, scanner_result)

    assert recommendation["coach_action"] == "Trail remaining position"
    assert recommendation["profit_giveback_percent"] == 50.0


def test_trade_summary_shows_risk_locked_and_runner_status():
    position = {
        "symbol": "SPY",
        "direction": "Bullish",
        "option_type": "CALL",
        "current_stop": 101,
        "entry_underlying_price": 101,
        "partial_1_taken": 1,
        "partial_2_taken": 0,
    }
    recommendation = {
        "current_profit_percent": 31.25,
        "coach_action": "Hold protected runner",
    }

    summary = trade_summary(position, recommendation)

    assert summary["profit_label"] == "Premium up 31.25%"
    assert summary["risk_status"] == "Risk locked"
    assert summary["runner_status"] == "First partial banked"
    assert summary["next_action"] == "Hold protected runner"
