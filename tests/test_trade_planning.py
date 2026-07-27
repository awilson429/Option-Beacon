from trade_planning import (
    build_trade_plan,
    enrich_with_trade_plan,
    timing_label,
    trade_plan_view,
)


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


def test_timing_labels_cover_setup_lifecycle():
    assert timing_label({"setup_stage": "Developing"}) == "EARLY"
    assert timing_label({"setup_stage": "Armed"}) == "EARLY"
    assert timing_label({"setup_stage": "Triggered"}) == "ENTERABLE"
    assert timing_label({"setup_stage": "Extended"}) == "EXTENDED"
    assert timing_label({"setup_stage": "Failed"}) == "INVALID"


def test_trade_plan_preserves_existing_risk_reward_calculation():
    plan = build_trade_plan(base_result())["trade_plan"]

    assert plan["trigger_price"] == 101.0
    assert plan["technical_stop"] == 98.0
    assert plan["target_2"] == 103.5
    assert plan["risk_reward"] == 0.83


def test_maximum_chase_respects_direction():
    bullish = build_trade_plan(base_result())["trade_plan"]
    bearish = build_trade_plan(
        base_result(
            bias="Bearish",
            price=99.25,
            support=99.0,
            resistance=102.0,
        )
    )["trade_plan"]

    assert bullish["max_entry_price"] == 101.7
    assert bullish["do_not_chase_price"] == 101.7
    assert bearish["max_entry_price"] == 98.3
    assert bearish["do_not_chase_price"] == 98.3


def test_trade_plan_view_labels_missing_values_as_unavailable():
    view = trade_plan_view({"symbol": "TEST", "trade_plan": {}})

    assert view["direction"] == "Unavailable"
    assert view["confidence"] == "Unavailable"
    assert view["entry_zone"] == "Unavailable"
    assert view["risk_reward"] == "Unavailable"
    assert view["maximum_chase_price"] == "Unavailable"
    assert view["invalidation_condition"] == "Unavailable"
    assert len(view["reasons"]) == 3
    assert all(reason == "Supporting reason unavailable." for reason in view["reasons"])
