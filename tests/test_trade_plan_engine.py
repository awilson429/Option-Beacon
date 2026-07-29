from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from trade_plan_config import TradePlanConfig
from trade_plan_engine import build_structured_trade_plan, calculate_late_entry_risk
from trade_plan_models import EntryType, LateEntryRisk, PlanStatus, TradePlan


NOW = datetime(2026, 7, 29, 14, 0, tzinfo=timezone.utc)


def market(**overrides):
    result = {
        "symbol": "SPY",
        "bias": "Bullish",
        "price": 501,
        "support": 498,
        "resistance": 500.5,
        "atr": 2,
        "vwap": 500,
        "ema9": 500.2,
        "ema21": 499.8,
        "rsi": 58,
        "relative_volume": 1.5,
        "confidence": 82,
        "confirmation_reached": True,
        "timestamp": NOW,
        "last_candle_at": NOW,
    }
    result.update(overrides)
    return result


def test_model_enums_serialization_and_deserialization():
    plan = build_structured_trade_plan(market(), evaluation_timestamp=NOW)
    restored = TradePlan.from_dict(plan.to_dict())

    assert plan.status == PlanStatus.READY
    assert restored == plan
    assert restored.entry_type == EntryType.BREAKOUT


def test_original_signal_is_frozen():
    plan = build_structured_trade_plan(market(), evaluation_timestamp=NOW)

    with pytest.raises(FrozenInstanceError):
        plan.original_signal_snapshot.initial_stop = 1


@pytest.mark.parametrize(
    ("name", "direction", "expected"),
    [
        ("Bullish breakout", "Bullish", EntryType.BREAKOUT),
        ("Pullback entry", "Bullish", EntryType.PULLBACK),
        ("VWAP reclaim", "Bullish", EntryType.VWAP_RECLAIM),
        ("EMA continuation", "Bullish", EntryType.EMA_CONTINUATION),
        ("Support bounce", "Bullish", EntryType.SUPPORT_BOUNCE),
        ("Momentum continuation", "Bullish", EntryType.MOMENTUM_CONTINUATION),
        ("Bearish breakdown", "Bearish", EntryType.BREAKOUT),
        ("Pullback rejection", "Bearish", EntryType.PULLBACK),
        ("VWAP rejection", "Bearish", EntryType.VWAP_REJECTION),
        ("EMA continuation", "Bearish", EntryType.EMA_CONTINUATION),
        ("Resistance rejection", "Bearish", EntryType.RESISTANCE_REJECTION),
        ("Momentum continuation", "Bearish", EntryType.MOMENTUM_CONTINUATION),
    ],
)
def test_supported_setup_types(name, direction, expected):
    values = market(setup_name=name, bias=direction)
    if direction == "Bearish":
        values.update(symbol="QQQ", price=449, support=449.5, resistance=452)
    plan = build_structured_trade_plan(values, evaluation_timestamp=NOW)

    assert plan.entry_type == expected
    assert plan.option_bias == ("CALL" if direction == "Bullish" else "PUT")


def test_entry_stop_target_and_risk_calculations_are_directional():
    bullish = build_structured_trade_plan(market(), evaluation_timestamp=NOW)
    bearish = build_structured_trade_plan(
        market(symbol="QQQ", bias="Bearish", price=449, support=449.5, resistance=452),
        evaluation_timestamp=NOW,
    )

    assert bullish.entry_zone_low < bullish.entry_zone_high
    assert bullish.initial_stop < bullish.confirmation_level < bullish.target_1 < bullish.target_2
    assert bearish.target_2 < bearish.target_1 < bearish.confirmation_level < bearish.initial_stop
    assert bullish.maximum_acceptable_entry > bullish.confirmation_level
    assert bearish.maximum_acceptable_entry < bearish.confirmation_level
    assert bullish.risk_reward_target_1 >= 1
    assert bullish.risk_reward_target_2 >= 2


def test_entry_zone_changes_with_volatility():
    low = build_structured_trade_plan(market(atr=1), evaluation_timestamp=NOW)
    high = build_structured_trade_plan(market(atr=4), evaluation_timestamp=NOW)

    assert high.entry_zone_high - high.entry_zone_low > low.entry_zone_high - low.entry_zone_low


def test_supplied_target_with_insufficient_room_returns_wait():
    plan = build_structured_trade_plan(market(target_1=500.6), evaluation_timestamp=NOW)

    assert plan.status == PlanStatus.WAIT
    assert "Minimum risk/reward to Target 1" in plan.missing_requirements


@pytest.mark.parametrize(
    ("overrides", "missing"),
    [
        ({"relative_volume": 0.5}, "Volume confirmation"),
        ({"trend_alignment": "conflict"}, "Trend alignment"),
        ({"inside_consolidation": True}, "Price must leave consolidation"),
        ({"provider_data_available": False}, "Required provider data is unavailable"),
        ({"confirmation_reached": False, "price": 499}, "Confirmation level has not been reached"),
    ],
)
def test_wait_and_watch_reasons(overrides, missing):
    plan = build_structured_trade_plan(market(**overrides), evaluation_timestamp=NOW)

    assert plan.status in {PlanStatus.WAIT, PlanStatus.WATCH}
    assert missing in plan.missing_requirements
    assert plan.activation_requirements or plan.reasons_to_avoid
    assert plan.invalidation_conditions


def test_stale_market_data_cannot_be_ready():
    plan = build_structured_trade_plan(
        market(last_candle_at=NOW - timedelta(minutes=20)),
        evaluation_timestamp=NOW,
    )

    assert plan.status == PlanStatus.WAIT
    assert plan.market_data_freshness["status"] == "STALE"
    assert "Market data is stale" in plan.missing_requirements


def test_near_end_of_day_and_poor_data_quality_return_wait():
    late_day = NOW.replace(hour=19, minute=40)
    plan = build_structured_trade_plan(
        market(
            timestamp=late_day,
            last_candle_at=late_day,
            setup_quality_score=40,
            option_liquidity={"spread_percent": 30},
        ),
        evaluation_timestamp=late_day,
    )

    assert plan.status == PlanStatus.WAIT
    assert "End-of-day cutoff is too close" in plan.missing_requirements
    assert "Setup quality is below the configured threshold" in plan.missing_requirements
    assert "Option data quality is unsuitable" in plan.missing_requirements


def test_initial_invalidated_and_expired_states():
    invalid = build_structured_trade_plan(
        market(setup_invalidated=True),
        evaluation_timestamp=NOW,
    )
    expired = build_structured_trade_plan(
        market(
            price=499,
            confirmation_reached=False,
            setup_expired=True,
        ),
        evaluation_timestamp=NOW,
    )

    assert invalid.status == PlanStatus.INVALIDATED
    assert expired.status == PlanStatus.EXPIRED


def test_late_entry_low_moderate_and_high():
    config = TradePlanConfig()
    low = build_structured_trade_plan(market(price=500.6), evaluation_timestamp=NOW)
    moderate = build_structured_trade_plan(market(price=501.4), evaluation_timestamp=NOW)
    high = build_structured_trade_plan(
        market(price=503, candles_since_trigger=6, rsi=78),
        evaluation_timestamp=NOW,
    )

    assert low.late_entry_risk == LateEntryRisk.LOW
    assert moderate.late_entry_risk == LateEntryRisk.MODERATE
    assert high.late_entry_risk == LateEntryRisk.HIGH
    assert high.status == PlanStatus.WAIT
    assert config.maximum_candles_after_trigger == 4


def test_late_filter_reports_exhaustion_and_target_distance():
    risk, explanation, metrics = calculate_late_entry_risk(
        market(momentum="weakening", volume_exhausted=True, rsi=80),
        direction="Bullish",
        current_price=502.4,
        confirmation_level=500.5,
        target_1=502.5,
        target_2=505,
        atr=2,
    )

    assert risk == LateEntryRisk.HIGH
    assert "momentum" in explanation
    assert metrics["remaining_target_1"] == pytest.approx(0.1)


def test_zero_structural_risk_has_safe_fallback():
    plan = build_structured_trade_plan(
        market(support=500.5),
        evaluation_timestamp=NOW,
    )

    assert plan.risk_reward_target_1 > 0
    assert plan.initial_stop != plan.confirmation_level


def test_confidence_penalties_are_bounded_and_transparent():
    clean = build_structured_trade_plan(market(confidence=95), evaluation_timestamp=NOW)
    blocked = build_structured_trade_plan(
        market(confidence=95, price=503, relative_volume=0.5, trend_alignment="conflict"),
        evaluation_timestamp=NOW,
    )

    assert 0 <= blocked.confidence_score < clean.confidence_score <= 100


def test_distance_metrics_are_explicit():
    plan = build_structured_trade_plan(market(), evaluation_timestamp=NOW)

    assert plan.ideal_entry == plan.confirmation_level
    assert plan.distance_from_trigger == 0.5
    assert plan.distance_from_vwap == 1
    assert plan.atr_extension == 0.25
    assert plan.candles_elapsed_since_trigger == 0


def test_only_spy_and_qqq_are_supported():
    with pytest.raises(ValueError, match="SPY and QQQ"):
        build_structured_trade_plan(market(symbol="IWM"), evaluation_timestamp=NOW)
