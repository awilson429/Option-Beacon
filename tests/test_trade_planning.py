from trade_planning import enrich_with_trade_plan


def base_result(**overrides):
    result = {
        "symbol": "TEST",
        "signal": "WATCHLIST",
        "bias": "Bullish",
        "confidence": 75,
        "price": 100.75,
        "atr": 2.0,
        "support": 98.0,
        "resistance": 101.0,
        "vwap": 100.0,
        "reasons": ["Price approaching resistance"],
    }
    result.update(overrides)
    return result


def test_armed_setup_gets_watch_closely_action():
    result = enrich_with_trade_plan(base_result())

    assert result["setup_stage"] == "Armed"
    assert result["entry_timing"] == "Watch closely"
    assert result["trade_plan"]["trigger_price"] == 101.0
    assert result["what_next"] == "Watch for breakout."


def test_extended_setup_gets_do_not_chase_action():
    result = enrich_with_trade_plan(base_result(price=102.2))

    assert result["setup_stage"] == "Extended"
    assert result["entry_timing"] == "Do not chase"
    assert result["what_next"] == "Do not chase."
