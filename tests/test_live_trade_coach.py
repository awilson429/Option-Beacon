from live_trade_coach import ACTION_AVOID, ACTION_ENTER, ACTION_WATCH, coach_live_setup


def test_live_coach_marks_triggered_setup_as_entry_zone_active():
    result = {
        "signal": "BULLISH SETUP",
        "bias": "Bullish",
        "confidence": 91,
        "price": 600,
        "entry_timing": "Trigger confirmed",
        "setup_stage": "Triggered",
        "trade_plan": {
            "trigger_price": 599.5,
            "invalidation_level": 597,
            "target_1": 603,
            "target_2": 606,
            "max_entry_price": 601,
        },
    }

    coach = coach_live_setup(result)

    assert coach["action"] == ACTION_ENTER
    assert coach["contract"] == "CALL"


def test_live_coach_marks_armed_setup_as_watch_for_trigger():
    result = {
        "signal": "WATCHLIST",
        "bias": "Bearish",
        "confidence": 84,
        "price": 500,
        "entry_timing": "Watch closely",
        "setup_stage": "Armed",
        "trade_plan": {
            "trigger_price": 499,
            "invalidation_level": 503,
        },
    }

    coach = coach_live_setup(result)

    assert coach["action"] == ACTION_WATCH
    assert coach["contract"] == "PUT"


def test_live_coach_warns_when_setup_is_extended():
    result = {
        "signal": "BULLISH SETUP",
        "bias": "Bullish",
        "confidence": 88,
        "price": 610,
        "entry_timing": "Do not chase",
        "setup_stage": "Extended",
        "trade_plan": {
            "max_entry_price": 604,
            "invalidation_level": 597,
        },
    }

    coach = coach_live_setup(result)

    assert coach["action"] == ACTION_AVOID
