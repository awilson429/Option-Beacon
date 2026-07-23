from optionbeacon_alerts import format_trade_coach_alert


def test_trade_coach_alert_includes_action_change_and_profit():
    position = {
        "symbol": "SPY",
        "direction": "Bullish",
    }
    recommendation = {
        "coach_action": "Take partial profit",
        "exit_score": 35,
        "current_profit_percent": 31.25,
        "peak_profit_percent": 31.25,
        "coach_next_step": "Consider selling 25% of the position.",
    }

    message = format_trade_coach_alert(
        position,
        recommendation,
        previous_action="Hold",
    )

    assert "SPY Bullish Hold -> Take partial profit" in message
    assert "Exit score 35/100" in message
    assert "P/L 31.25%" in message
