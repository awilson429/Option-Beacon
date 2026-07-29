"""Paper-only lifecycle transitions for structured Trade Plans."""

from __future__ import annotations

from datetime import datetime, time, timezone
import hashlib
import logging
from zoneinfo import ZoneInfo

from trade_plan_config import DEFAULT_TRADE_PLAN_CONFIG, TradePlanConfig
from trade_plan_models import (
    ExitReason,
    FinalOutcome,
    LifecycleEvent,
    LifecycleEventType,
    PlanStatus,
    TradePlan,
)


LOGGER = logging.getLogger(__name__)


def _timestamp(value):
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _directional_return(plan, price):
    entry = plan.current_status.get("entry_underlying_price") or plan.confirmation_level
    change = ((price - entry) / entry) * 100 if entry else 0.0
    return change if plan.direction == "Bullish" else -change


def _reached(plan, price, level):
    return price >= level if plan.direction == "Bullish" else price <= level


def _append_event(plan, event_type, timestamp, market_timestamp, price, reason, prior=None, new=None, metadata=None):
    identity = f"{plan.trade_plan_id}:{event_type.value}:{timestamp.isoformat()}:{len(plan.lifecycle_events)}"
    event = LifecycleEvent(
        event_id=hashlib.sha256(identity.encode()).hexdigest()[:24],
        trade_plan_id=plan.trade_plan_id,
        timestamp=timestamp,
        market_timestamp=market_timestamp,
        underlying_price=price,
        event_type=event_type,
        reason=reason,
        prior_value=prior,
        new_value=new,
        metadata=metadata or {},
    )
    plan.lifecycle_events.append(event)
    LOGGER.info("Trade plan %s event %s", plan.trade_plan_id[:12], event_type.value)
    return event


def _close(plan, price, now, market_time, reason, event_type):
    plan.status = PlanStatus.CLOSED
    plan.current_status["state"] = PlanStatus.CLOSED.value
    plan.current_status["exit_timestamp"] = now.isoformat()
    _append_event(plan, event_type, now, market_time, price, reason.value)
    entry_time = _timestamp(plan.current_status.get("entry_timestamp") or now)
    hold_minutes = max(0.0, (now - entry_time).total_seconds() / 60)
    plan.final_outcome = FinalOutcome(
        exit_timestamp=now,
        exit_underlying_price=price,
        exit_reason=reason,
        realized_return_estimate=round(_directional_return(plan, price), 4),
        hold_time_minutes=round(hold_minutes, 2),
        hold_time_candles=int(plan.current_status.get("hold_candles") or 0),
        maximum_favorable_excursion=round(float(plan.current_status.get("mfe") or 0), 4),
        maximum_adverse_excursion=round(float(plan.current_status.get("mae") or 0), 4),
    )
    return plan


def update_trade_plan(
    plan: TradePlan,
    *,
    current_price: float,
    current_timestamp,
    market_timestamp=None,
    candles_elapsed: int = 0,
    technical_valid: bool = True,
    manual_close: bool = False,
    config: TradePlanConfig = DEFAULT_TRADE_PLAN_CONFIG,
) -> TradePlan:
    """Advance one plan deterministically without changing its frozen original signal."""
    if plan.status in {PlanStatus.CLOSED, PlanStatus.INVALIDATED, PlanStatus.EXPIRED}:
        return plan
    price = float(current_price)
    now = _timestamp(current_timestamp)
    market_time = _timestamp(market_timestamp or current_timestamp)
    plan.current_underlying_price = price
    plan.market_timestamp = market_time
    plan.current_status["hold_candles"] = int(candles_elapsed)
    if plan.status in {PlanStatus.WAIT, PlanStatus.WATCH, PlanStatus.READY}:
        invalid = (
            price <= plan.invalidation_level
            if plan.direction == "Bullish"
            else price >= plan.invalidation_level
        )
        if invalid or not technical_valid:
            plan.status = PlanStatus.INVALIDATED
            plan.current_status["state"] = PlanStatus.INVALIDATED.value
            _append_event(plan, LifecycleEventType.TECHNICALLY_INVALIDATED, now, market_time, price, "Setup invalidated before entry")
            return plan
        age_minutes = max(0.0, (now - plan.signal_timestamp).total_seconds() / 60)
        if age_minutes >= plan.maximum_hold_minutes or candles_elapsed >= plan.maximum_hold_candles:
            plan.status = PlanStatus.EXPIRED
            plan.current_status["state"] = PlanStatus.EXPIRED.value
            _append_event(plan, LifecycleEventType.EXPIRED, now, market_time, price, "Setup did not trigger within its permitted window")
            return plan
        confirmation = _reached(plan, price, plan.confirmation_level)
        within_max = (
            price <= plan.maximum_acceptable_entry
            if plan.direction == "Bullish"
            else price >= plan.maximum_acceptable_entry
        )
        if confirmation and within_max:
            if plan.status != PlanStatus.READY:
                _append_event(plan, LifecycleEventType.CONFIRMATION_REACHED, now, market_time, price, "Confirmation reached")
                _append_event(plan, LifecycleEventType.ENTRY_READY, now, market_time, price, "Price is inside the acceptable entry range")
            plan.status = PlanStatus.READY
            plan.current_status["state"] = PlanStatus.READY.value
        if plan.status == PlanStatus.READY and confirmation and within_max:
            plan.status = PlanStatus.ACTIVE
            plan.current_status.update(
                {
                    "state": PlanStatus.ACTIVE.value,
                    "entry_timestamp": now.isoformat(),
                    "entry_underlying_price": price,
                    "mfe": 0.0,
                    "mae": 0.0,
                    "target_1_reached": False,
                    "breakeven_active": False,
                    "trailing_active": False,
                }
            )
            _append_event(plan, LifecycleEventType.ENTRY_TRIGGERED, now, market_time, price, "Paper entry triggered")
        return plan

    if plan.status != PlanStatus.ACTIVE:
        return plan
    current_return = _directional_return(plan, price)
    plan.current_status["mfe"] = max(float(plan.current_status.get("mfe") or 0), current_return)
    plan.current_status["mae"] = min(float(plan.current_status.get("mae") or 0), current_return)
    entry_time = _timestamp(plan.current_status["entry_timestamp"])
    hold_minutes = max(0.0, (now - entry_time).total_seconds() / 60)
    if manual_close:
        return _close(plan, price, now, market_time, ExitReason.MANUAL_CLOSE, LifecycleEventType.MANUALLY_CLOSED)
    if not technical_valid:
        return _close(plan, price, now, market_time, ExitReason.TECHNICAL_INVALIDATION, LifecycleEventType.TECHNICALLY_INVALIDATED)
    market_now = now.astimezone(ZoneInfo(config.market_timezone))
    if market_now.time() >= time.fromisoformat(plan.end_of_day_cutoff):
        return _close(plan, price, now, market_time, ExitReason.END_OF_DAY, LifecycleEventType.END_OF_DAY_EXIT)
    if hold_minutes >= plan.maximum_hold_minutes:
        return _close(plan, price, now, market_time, ExitReason.MAX_HOLD_TIME, LifecycleEventType.MAX_HOLD_REACHED)
    if candles_elapsed >= plan.maximum_hold_candles:
        return _close(plan, price, now, market_time, ExitReason.MAX_HOLD_CANDLES, LifecycleEventType.MAX_HOLD_REACHED)
    if _reached(plan, price, plan.target_2):
        return _close(plan, plan.target_2, now, market_time, ExitReason.TARGET_2_HIT, LifecycleEventType.TARGET_2_REACHED)
    if _reached(plan, price, plan.target_1) and not plan.current_status.get("target_1_reached"):
        plan.current_status["target_1_reached"] = True
        _append_event(plan, LifecycleEventType.TARGET_1_REACHED, now, market_time, price, "Target 1 reached; paper position remains active")
        if config.breakeven_trigger_method == "TARGET_1":
            prior = plan.current_stop
            plan.current_stop = float(plan.current_status["entry_underlying_price"])
            plan.current_status["breakeven_active"] = True
            _append_event(plan, LifecycleEventType.STOP_MOVED_TO_BREAKEVEN, now, market_time, price, "Stop moved to breakeven", prior, plan.current_stop)
    if _reached(plan, price, plan.trailing_stop_activation) and not plan.current_status.get("trailing_active"):
        plan.current_status["trailing_active"] = True
        _append_event(plan, LifecycleEventType.TRAILING_STOP_ACTIVATED, now, market_time, price, plan.trailing_stop_method)
    if plan.current_status.get("trailing_active"):
        proposed = (
            price - config.trailing_stop_atr_multiplier * abs(plan.confirmation_level - plan.initial_stop)
            if plan.direction == "Bullish"
            else price + config.trailing_stop_atr_multiplier * abs(plan.confirmation_level - plan.initial_stop)
        )
        improves = proposed > plan.current_stop if plan.direction == "Bullish" else proposed < plan.current_stop
        if improves:
            prior = plan.current_stop
            plan.current_stop = round(proposed, 4)
            _append_event(plan, LifecycleEventType.TRAILING_STOP_UPDATED, now, market_time, price, "Trailing stop advanced", prior, plan.current_stop)
    stopped = price <= plan.current_stop if plan.direction == "Bullish" else price >= plan.current_stop
    if stopped:
        if plan.current_status.get("trailing_active"):
            reason, event = ExitReason.TRAILING_STOP_HIT, LifecycleEventType.STOPPED_OUT
        elif plan.current_status.get("breakeven_active"):
            reason, event = ExitReason.BREAKEVEN_STOP_HIT, LifecycleEventType.BREAKEVEN_STOPPED
        else:
            reason, event = ExitReason.STOP_HIT, LifecycleEventType.STOPPED_OUT
        return _close(plan, plan.current_stop, now, market_time, reason, event)
    return plan
