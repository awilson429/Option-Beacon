from trade_management import coach_recommendation


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
