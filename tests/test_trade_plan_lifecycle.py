from datetime import datetime, timedelta, timezone

from trade_plan_engine import build_structured_trade_plan
from trade_plan_lifecycle import update_trade_plan
from trade_plan_models import ExitReason, LifecycleEventType, PlanStatus


NOW = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)


def ready(direction="Bullish"):
    values = {
        "symbol": "SPY" if direction == "Bullish" else "QQQ",
        "bias": direction,
        "price": 101 if direction == "Bullish" else 99,
        "support": 98 if direction == "Bullish" else 99.5,
        "resistance": 100.5 if direction == "Bullish" else 102,
        "atr": 2,
        "relative_volume": 1.5,
        "confidence": 85,
        "confirmation_reached": True,
        "timestamp": NOW,
        "last_candle_at": NOW,
    }
    return build_structured_trade_plan(values, evaluation_timestamp=NOW)


def active(direction="Bullish"):
    plan = ready(direction)
    return update_trade_plan(
        plan,
        current_price=plan.confirmation_level,
        current_timestamp=NOW + timedelta(minutes=1),
    )


def events(plan):
    return [event.event_type for event in plan.lifecycle_events]


def test_creation_confirmation_ready_and_activation():
    plan = active()

    assert plan.status == PlanStatus.ACTIVE
    assert LifecycleEventType.CREATED in events(plan)
    assert LifecycleEventType.ENTRY_READY in events(plan)
    assert LifecycleEventType.ENTRY_TRIGGERED in events(plan)


def test_bullish_and_bearish_stop():
    bullish = active()
    bearish = active("Bearish")
    update_trade_plan(bullish, current_price=bullish.initial_stop, current_timestamp=NOW + timedelta(minutes=5))
    update_trade_plan(bearish, current_price=bearish.initial_stop, current_timestamp=NOW + timedelta(minutes=5))

    assert bullish.final_outcome.exit_reason == ExitReason.STOP_HIT
    assert bearish.final_outcome.exit_reason == ExitReason.STOP_HIT


def test_target_1_is_management_event_and_moves_to_breakeven():
    plan = active()
    original = plan.original_signal_snapshot
    update_trade_plan(plan, current_price=plan.target_1, current_timestamp=NOW + timedelta(minutes=5))

    assert plan.status == PlanStatus.ACTIVE
    assert plan.current_status["target_1_reached"] is True
    assert plan.current_status["breakeven_active"] is True
    assert LifecycleEventType.TARGET_1_REACHED in events(plan)
    assert LifecycleEventType.STOP_MOVED_TO_BREAKEVEN in events(plan)
    assert plan.original_signal_snapshot == original


def test_breakeven_stop_closes():
    plan = active()
    update_trade_plan(plan, current_price=plan.target_1, current_timestamp=NOW + timedelta(minutes=5))
    update_trade_plan(
        plan,
        current_price=plan.current_status["entry_underlying_price"],
        current_timestamp=NOW + timedelta(minutes=10),
    )

    assert plan.final_outcome.exit_reason == ExitReason.BREAKEVEN_STOP_HIT


def test_trailing_stop_activation_update_and_hit():
    plan = active()
    update_trade_plan(plan, current_price=plan.trailing_stop_activation, current_timestamp=NOW + timedelta(minutes=5))
    trailed_stop = plan.current_stop
    update_trade_plan(plan, current_price=trailed_stop, current_timestamp=NOW + timedelta(minutes=10))

    assert LifecycleEventType.TRAILING_STOP_ACTIVATED in events(plan)
    assert LifecycleEventType.TRAILING_STOP_UPDATED in events(plan)
    assert plan.final_outcome.exit_reason == ExitReason.TRAILING_STOP_HIT


def test_target_2_closes_and_records_outcome():
    plan = active()
    update_trade_plan(plan, current_price=plan.target_2, current_timestamp=NOW + timedelta(minutes=15))

    assert plan.status == PlanStatus.CLOSED
    assert plan.final_outcome.exit_reason == ExitReason.TARGET_2_HIT
    assert plan.final_outcome.realized_return_estimate > 0


def test_maximum_hold_time_and_candles():
    by_time = active()
    by_candles = active()
    update_trade_plan(by_time, current_price=by_time.confirmation_level, current_timestamp=NOW + timedelta(minutes=121))
    update_trade_plan(by_candles, current_price=by_candles.confirmation_level, current_timestamp=NOW + timedelta(minutes=30), candles_elapsed=24)

    assert by_time.final_outcome.exit_reason == ExitReason.MAX_HOLD_TIME
    assert by_candles.final_outcome.exit_reason == ExitReason.MAX_HOLD_CANDLES


def test_end_of_day_exit():
    plan = active()
    update_trade_plan(plan, current_price=plan.confirmation_level, current_timestamp=NOW.replace(hour=19, minute=51))

    assert plan.final_outcome.exit_reason == ExitReason.END_OF_DAY


def test_technical_invalidation_and_manual_close():
    invalid = active()
    manual = active()
    update_trade_plan(invalid, current_price=invalid.confirmation_level, current_timestamp=NOW + timedelta(minutes=5), technical_valid=False)
    update_trade_plan(manual, current_price=manual.confirmation_level, current_timestamp=NOW + timedelta(minutes=5), manual_close=True)

    assert invalid.final_outcome.exit_reason == ExitReason.TECHNICAL_INVALIDATION
    assert manual.final_outcome.exit_reason == ExitReason.MANUAL_CLOSE


def test_unentered_plan_invalidates_or_expires():
    invalid = ready()
    expired = ready()
    invalid.status = PlanStatus.WATCH
    expired.status = PlanStatus.WATCH
    update_trade_plan(invalid, current_price=invalid.invalidation_level, current_timestamp=NOW + timedelta(minutes=5))
    update_trade_plan(expired, current_price=expired.confirmation_level - 0.5, current_timestamp=NOW + timedelta(minutes=121))

    assert invalid.status == PlanStatus.INVALIDATED
    assert expired.status == PlanStatus.EXPIRED


def test_closed_plan_never_changes():
    plan = active()
    update_trade_plan(plan, current_price=plan.target_2, current_timestamp=NOW + timedelta(minutes=5))
    snapshot = plan.to_dict()
    update_trade_plan(plan, current_price=1, current_timestamp=NOW + timedelta(minutes=10))

    assert plan.to_dict() == snapshot
