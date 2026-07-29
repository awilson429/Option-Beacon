"""Deterministic, volatility-aware Trade Plan Engine for SPY and QQQ."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import math
from zoneinfo import ZoneInfo

from trade_plan_config import DEFAULT_TRADE_PLAN_CONFIG, TradePlanConfig
from trade_plan_models import (
    EntryType,
    LateEntryRisk,
    LifecycleEvent,
    LifecycleEventType,
    OriginalSignal,
    PlanStatus,
    TradePlan,
)


LOGGER = logging.getLogger(__name__)
SUPPORTED_SYMBOLS = frozenset({"SPY", "QQQ"})


def _number(result, *keys, default=None):
    for key in keys:
        value = result.get(key)
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            return number
    return default


def _time(value, fallback=None):
    if isinstance(value, datetime):
        parsed = value
    elif value:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    else:
        parsed = fallback or datetime.now(timezone.utc)
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _entry_type(result, direction):
    text = str(
        result.get("entry_type")
        or result.get("setup_name")
        or (result.get("trade_plan") or {}).get("setup_type")
        or result.get("setup")
        or ""
    ).lower()
    if "vwap" in text:
        return EntryType.VWAP_RECLAIM if direction == "Bullish" else EntryType.VWAP_REJECTION
    if "pullback" in text:
        return EntryType.PULLBACK
    if "ema" in text:
        return EntryType.EMA_CONTINUATION
    if "support" in text or "bounce" in text:
        return EntryType.SUPPORT_BOUNCE
    if "resistance" in text or "rejection" in text:
        return EntryType.RESISTANCE_REJECTION
    if "momentum" in text or "continuation" in text:
        return EntryType.MOMENTUM_CONTINUATION
    return EntryType.BREAKOUT


def _directional_distance(direction, start, end):
    return end - start if direction == "Bullish" else start - end


def _crossed(direction, price, level):
    return price >= level if direction == "Bullish" else price <= level


def market_data_freshness(market_timestamp, evaluation_timestamp, config):
    age = max(0.0, (evaluation_timestamp - market_timestamp).total_seconds())
    return {
        "market_timestamp": market_timestamp.isoformat(),
        "evaluation_timestamp": evaluation_timestamp.isoformat(),
        "data_age_seconds": round(age, 1),
        "status": "FRESH" if age <= config.market_data_stale_seconds else "STALE",
    }


def calculate_late_entry_risk(
    result,
    *,
    direction,
    current_price,
    confirmation_level,
    target_1,
    target_2,
    atr,
    config=DEFAULT_TRADE_PLAN_CONFIG,
):
    ema9 = _number(result, "ema9", "ema20", default=current_price)
    ema21 = _number(result, "ema21", "ema20", default=current_price)
    vwap = _number(result, "vwap", default=current_price)
    rsi = _number(result, "rsi", default=50)
    candles = int(_number(result, "candles_since_trigger", default=0) or 0)
    extension = max(0.0, _directional_distance(direction, confirmation_level, current_price) / atr)
    projected = max(abs(target_1 - confirmation_level), atr)
    completed = max(0.0, _directional_distance(direction, confirmation_level, current_price) / projected)
    remaining_t1 = max(0.0, _directional_distance(direction, current_price, target_1))
    reasons = []
    severity = 0
    if extension >= config.maximum_late_entry_atr_extension:
        severity = 2
        reasons.append(f"price is {extension:.2f} ATR beyond confirmation")
    elif extension >= config.moderate_late_entry_atr_extension:
        severity = max(severity, 1)
        reasons.append(f"price is {extension:.2f} ATR beyond confirmation")
    if candles > config.maximum_candles_after_trigger:
        severity = 2
        reasons.append(f"{candles} candles have elapsed since confirmation")
    if completed >= config.maximum_projected_move_completed:
        severity = 2
        reasons.append(f"{completed:.0%} of the projected move is complete")
    if remaining_t1 < atr * config.minimum_remaining_distance_target_1_atr:
        severity = 2
        reasons.append("too little reward remains to Target 1")
    if (direction == "Bullish" and rsi >= config.bullish_rsi_overextension) or (
        direction == "Bearish" and rsi <= config.bearish_rsi_overextension
    ):
        severity = max(severity, 1)
        reasons.append(f"RSI is extended at {rsi:.1f}")
    momentum = str(result.get("momentum") or result.get("momentum_state") or "").lower()
    if any(word in momentum for word in ("weak", "exhaust", "fade")):
        severity = max(severity, 1)
        reasons.append("momentum is weakening")
    if result.get("volume_exhausted"):
        severity = max(severity, 1)
        reasons.append("volume shows exhaustion")
    distances = {
        "distance_from_confirmation": round(_directional_distance(direction, confirmation_level, current_price), 4),
        "distance_from_vwap": round(current_price - vwap, 4),
        "distance_from_ema9": round(current_price - ema9, 4),
        "distance_from_ema21": round(current_price - ema21, 4),
        "atr_extension": round(extension, 3),
        "candles_elapsed": candles,
        "projected_move_completed": round(completed, 3),
        "remaining_target_1": round(remaining_t1, 4),
        "remaining_target_2": round(max(0.0, _directional_distance(direction, current_price, target_2)), 4),
    }
    risk = (LateEntryRisk.LOW, LateEntryRisk.MODERATE, LateEntryRisk.HIGH)[severity]
    explanation = (
        "Entry timing remains acceptable."
        if not reasons
        else "Trade timing risk: " + ", ".join(reasons) + "."
    )
    return risk, explanation, distances


def _event(plan_id, event_type, timestamp, market_timestamp, price, reason):
    identity = f"{plan_id}:{event_type.value}:{timestamp.isoformat()}"
    return LifecycleEvent(
        event_id=hashlib.sha256(identity.encode()).hexdigest()[:24],
        trade_plan_id=plan_id,
        timestamp=timestamp,
        market_timestamp=market_timestamp,
        underlying_price=price,
        event_type=event_type,
        reason=reason,
    )


def build_structured_trade_plan(
    result: dict,
    *,
    evaluation_timestamp=None,
    config: TradePlanConfig = DEFAULT_TRADE_PLAN_CONFIG,
) -> TradePlan:
    """Build a complete paper-only plan while preserving the original snapshot."""
    errors = config.validate()
    if errors:
        raise ValueError("; ".join(errors))
    result = dict(result or {})
    symbol = str(result.get("symbol") or "").upper()
    if symbol not in SUPPORTED_SYMBOLS:
        raise ValueError("Trade Plan Engine supports SPY and QQQ only")
    direction = str(result.get("bias") or result.get("direction") or "Neutral")
    if direction not in {"Bullish", "Bearish"}:
        direction = "Bullish" if _number(result, "bullish_score", default=0) >= _number(result, "bearish_score", default=0) else "Bearish"
    multiplier = 1 if direction == "Bullish" else -1
    price = _number(result, "price", "current_underlying_price")
    if not price or price <= 0:
        raise ValueError("A positive current underlying price is required")
    signal_time = _time(result.get("timestamp") or result.get("signal_timestamp"))
    market_time = _time(result.get("last_candle_at") or result.get("market_timestamp"), signal_time)
    evaluated_at = _time(evaluation_timestamp, signal_time)
    supplied_atr = _number(result, "atr", default=0) or 0
    atr = max(supplied_atr, price * config.entry_zone_percentage_fallback, config.minimum_atr)
    entry_type = _entry_type(result, direction)
    setup_name = str(result.get("setup_name") or (result.get("trade_plan") or {}).get("setup_type") or entry_type.value)
    confirmation = _number(
        result,
        "confirmation_level",
        "resistance" if direction == "Bullish" else "support",
        default=price,
    )
    width = (
        supplied_atr * config.entry_zone_atr_width
        if supplied_atr >= config.minimum_atr
        else price * config.entry_zone_percentage_fallback
    )
    entry_low = confirmation - width if direction == "Bullish" else confirmation - width
    entry_high = confirmation + width
    maximum_entry = confirmation + multiplier * max(width * 1.75, atr * config.moderate_late_entry_atr_extension)
    structural = _number(result, "support" if direction == "Bullish" else "resistance")
    if structural is None:
        structural = confirmation - multiplier * atr
    initial_stop = structural - multiplier * atr * config.stop_atr_buffer
    risk = max(abs(confirmation - initial_stop), atr * 0.25)
    supplied_t1 = _number(result, "target_1")
    supplied_t2 = _number(result, "target_2")
    target_1 = supplied_t1 or confirmation + multiplier * max(
        atr * config.target_1_atr_multiplier,
        risk * config.minimum_risk_reward_target_1,
    )
    target_2 = supplied_t2 or confirmation + multiplier * max(
        atr * config.target_2_atr_multiplier,
        risk * config.preferred_risk_reward_target_2,
    )
    rr1 = max(0.0, _directional_distance(direction, confirmation, target_1)) / risk
    rr2 = max(0.0, _directional_distance(direction, confirmation, target_2)) / risk
    remaining1 = _directional_distance(direction, price, target_1)
    remaining2 = _directional_distance(direction, price, target_2)
    freshness = market_data_freshness(market_time, evaluated_at, config)
    if freshness["status"] == "STALE":
        LOGGER.warning(
            "Trade Plan market data is stale for %s (%s seconds)",
            symbol,
            freshness["data_age_seconds"],
        )
    late_risk, late_explanation, late_metrics = calculate_late_entry_risk(
        result,
        direction=direction,
        current_price=price,
        confirmation_level=confirmation,
        target_1=target_1,
        target_2=target_2,
        atr=atr,
        config=config,
    )
    relative_volume = _number(result, "relative_volume", "volume_ratio", default=1.0)
    setup_quality = _number(result, "setup_quality_score", "score", "confidence", default=50)
    option_spread = _number(
        result.get("option_liquidity") or {},
        "spread_percent",
        default=0,
    )
    trend = str(result.get("trend_alignment") or result.get("trend") or "aligned").lower()
    confirmed = bool(
        result.get("confirmation_reached")
        if "confirmation_reached" in result
        else _crossed(direction, price, confirmation)
    )
    missing = []
    avoid = []
    activation = []
    invalidation = [
        (
            f"Price falls below {initial_stop:.2f}"
            if direction == "Bullish"
            else f"Price rises above {initial_stop:.2f}"
        ),
        f"Setup exceeds {config.maximum_candles_after_trigger} candles after confirmation",
    ]
    if not result.get("provider_data_available", True):
        missing.append("Required provider data is unavailable")
        activation.append("Required read-only market data becomes available")
    if freshness["status"] == "STALE":
        missing.append("Market data is stale")
        avoid.append(f"Market data is {freshness['data_age_seconds']:.0f} seconds old")
    if relative_volume < config.volume_confirmation_threshold:
        missing.append("Volume confirmation")
        activation.append(f"Relative volume reaches {config.volume_confirmation_threshold:.2f}")
    if any(word in trend for word in ("conflict", "against", "bearish" if direction == "Bullish" else "bullish")):
        missing.append("Trend alignment")
        avoid.append("Trend indicators conflict with the proposed direction")
    if result.get("inside_consolidation"):
        missing.append("Price must leave consolidation")
        activation.append("Price closes outside the consolidation range")
    if setup_quality < config.minimum_setup_quality:
        missing.append("Setup quality is below the configured threshold")
        activation.append(f"Setup quality reaches {config.minimum_setup_quality:.0f}")
    if option_spread > config.maximum_data_quality_spread_percent:
        missing.append("Option data quality is unsuitable")
        avoid.append(f"Observed spread exceeds {config.maximum_data_quality_spread_percent:.0f}%")
    if not confirmed:
        missing.append("Confirmation level has not been reached")
        activation.append(
            f"Price {'closes above' if direction == 'Bullish' else 'closes below'} {confirmation:.2f}"
        )
    if rr1 < config.minimum_risk_reward_target_1:
        missing.append("Minimum risk/reward to Target 1")
        avoid.append(f"Risk/reward to Target 1 is only {rr1:.2f}:1")
    if late_risk == LateEntryRisk.HIGH:
        missing.append("Entry is no longer timely")
        avoid.append(late_explanation)
    if remaining1 <= 0:
        missing.append("Target 1 has already been reached")
    market_evaluation = evaluated_at.astimezone(ZoneInfo(config.market_timezone))
    cutoff_time = datetime.strptime(config.end_of_day_cutoff, "%H:%M").time()
    cutoff = datetime.combine(
        market_evaluation.date(),
        cutoff_time,
        tzinfo=market_evaluation.tzinfo,
    )
    if market_evaluation >= cutoff - timedelta(minutes=config.minimum_minutes_before_end_of_day):
        missing.append("End-of-day cutoff is too close")
        avoid.append("Insufficient time remains for a new intraday entry")
    invalidated = bool(result.get("setup_invalidated")) or (
        (price <= initial_stop)
        if direction == "Bullish"
        else (price >= initial_stop)
    )
    expired = bool(result.get("setup_expired")) or (
        int(late_metrics["candles_elapsed"]) > config.maximum_candles_after_trigger
        and not confirmed
    )
    max_entry_breached = (
        price > maximum_entry if direction == "Bullish" else price < maximum_entry
    )
    if max_entry_breached:
        missing.append("Price is beyond the maximum acceptable entry")
        avoid.append("Trigger has passed; do not chase")
    status = PlanStatus.WAIT
    if invalidated:
        status = PlanStatus.INVALIDATED
        avoid.append("Technical invalidation level has failed")
    elif expired:
        status = PlanStatus.EXPIRED
        avoid.append("The setup exceeded its permitted confirmation window")
    elif not missing:
        status = PlanStatus.READY
    elif confirmed:
        status = PlanStatus.WAIT
    elif result.get("setup_confirmed", True) and freshness["status"] == "FRESH":
        status = PlanStatus.WATCH
    base_confidence = _number(result, "confidence", "score", default=50)
    confidence = base_confidence
    if rr1 < config.minimum_risk_reward_target_1:
        confidence -= config.poor_risk_reward_penalty
    if late_risk == LateEntryRisk.MODERATE:
        confidence -= config.late_entry_moderate_penalty
    elif late_risk == LateEntryRisk.HIGH:
        confidence -= config.late_entry_high_penalty
    if freshness["status"] == "STALE":
        confidence -= config.stale_data_penalty
    if "Trend alignment" in missing:
        confidence -= config.trend_conflict_penalty
    confidence = round(max(0.0, min(100.0, confidence)), 1)
    if confidence < config.minimum_confidence and status == PlanStatus.READY:
        status = PlanStatus.WAIT
        missing.append(f"Confidence must reach {config.minimum_confidence:.0f}")
    reasons = list(dict.fromkeys(result.get("reasons") or []))
    reasons.extend(
        [
            f"{direction} {setup_name} structure identified",
            f"Target 1 risk/reward is {rr1:.2f}:1",
        ]
    )
    plan_identity = {
        "symbol": symbol,
        "direction": direction,
        "setup": setup_name,
        "signal_timestamp": signal_time.isoformat(),
        "confirmation": round(confirmation, 4),
    }
    plan_id = hashlib.sha256(json.dumps(plan_identity, sort_keys=True).encode()).hexdigest()
    breakeven = confirmation + multiplier * risk * config.breakeven_r_multiple
    trailing_activation = confirmation + multiplier * risk * config.trailing_stop_activation_r_multiple
    snapshot_values = {
        key: value
        for key, value in result.items()
        if key not in {"api_key", "token", "authorization", "headers"}
        and isinstance(value, (str, int, float, bool, type(None), list, dict))
    }
    original = OriginalSignal(
        signal_timestamp=signal_time,
        market_timestamp=market_time,
        underlying_price_at_signal=price,
        confidence_score=confidence,
        setup_name=setup_name,
        entry_zone_low=round(entry_low, 4),
        entry_zone_high=round(entry_high, 4),
        confirmation_level=round(confirmation, 4),
        maximum_acceptable_entry=round(maximum_entry, 4),
        initial_stop=round(initial_stop, 4),
        target_1=round(target_1, 4),
        target_2=round(target_2, 4),
        breakeven_trigger=round(breakeven, 4),
        trailing_stop_activation=round(trailing_activation, 4),
        trailing_stop_method="ATR trailing stop",
        maximum_hold_minutes=config.maximum_hold_minutes,
        maximum_hold_candles=config.maximum_hold_candles,
        reasons_for_trade=tuple(reasons),
        reasons_to_avoid=tuple(avoid),
        market_snapshot=snapshot_values,
    )
    created_event = _event(
        plan_id,
        LifecycleEventType.CREATED,
        evaluated_at,
        market_time,
        price,
        f"Plan created in {status.value} state",
    )
    events = [created_event]
    if status == PlanStatus.WATCH:
        events.append(_event(plan_id, LifecycleEventType.WATCH_STARTED, evaluated_at, market_time, price, "Setup is developing"))
    if status == PlanStatus.READY:
        events.extend(
            [
                _event(plan_id, LifecycleEventType.CONFIRMATION_REACHED, evaluated_at, market_time, price, "Confirmation conditions are satisfied"),
                _event(plan_id, LifecycleEventType.ENTRY_READY, evaluated_at, market_time, price, "Price remains within the acceptable entry range"),
            ]
        )
    LOGGER.info("Trade plan %s created for %s in %s", plan_id[:12], symbol, status.value)
    return TradePlan(
        trade_plan_id=plan_id,
        symbol=symbol,
        direction=direction,
        option_bias="CALL" if direction == "Bullish" else "PUT",
        setup_name=setup_name,
        status=status,
        signal_timestamp=signal_time,
        market_timestamp=market_time,
        underlying_price_at_signal=price,
        current_underlying_price=price,
        timeframe=str(result.get("timeframe") or "5m"),
        entry_type=entry_type,
        ideal_entry=round(confirmation, 4),
        entry_zone_low=round(entry_low, 4),
        entry_zone_high=round(entry_high, 4),
        confirmation_level=round(confirmation, 4),
        maximum_acceptable_entry=round(maximum_entry, 4),
        initial_stop=round(initial_stop, 4),
        stop_method="Structure with ATR buffer",
        current_stop=round(initial_stop, 4),
        target_1=round(target_1, 4),
        target_2=round(target_2, 4),
        breakeven_trigger=round(breakeven, 4),
        trailing_stop_activation=round(trailing_activation, 4),
        trailing_stop_method="ATR trailing stop",
        maximum_hold_minutes=config.maximum_hold_minutes,
        maximum_hold_candles=config.maximum_hold_candles,
        end_of_day_cutoff=config.end_of_day_cutoff,
        confidence_score=confidence,
        late_entry_risk=late_risk,
        late_entry_explanation=late_explanation,
        risk_reward_target_1=round(rr1, 3),
        risk_reward_target_2=round(rr2, 3),
        remaining_reward_target_1=round(remaining1, 4),
        remaining_reward_target_2=round(remaining2, 4),
        original_reward_target_1=round(_directional_distance(direction, confirmation, target_1), 4),
        original_reward_target_2=round(_directional_distance(direction, confirmation, target_2), 4),
        invalidation_level=round(initial_stop, 4),
        distance_from_trigger=late_metrics["distance_from_confirmation"],
        distance_from_vwap=late_metrics["distance_from_vwap"],
        distance_from_ema9=late_metrics["distance_from_ema9"],
        distance_from_ema21=late_metrics["distance_from_ema21"],
        atr_extension=late_metrics["atr_extension"],
        candles_elapsed_since_trigger=late_metrics["candles_elapsed"],
        reasons_for_trade=reasons,
        reasons_to_avoid=avoid,
        missing_requirements=list(dict.fromkeys(missing)),
        activation_requirements=list(dict.fromkeys(activation)),
        invalidation_conditions=invalidation,
        market_data_freshness=freshness,
        original_signal_snapshot=original,
        current_status={"state": status.value, "late_metrics": late_metrics, "entry_timestamp": None, "hold_candles": 0},
        lifecycle_events=events,
    )
