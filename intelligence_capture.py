"""Pure builders for immutable setup features and evolving outcome labels."""

from __future__ import annotations

import math
from dataclasses import asdict
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from intelligence_models import OutcomeLabel, SetupFeatureSnapshot
from market_regime import classify_market_regime
from sector_context import build_sector_context


EASTERN = ZoneInfo("America/New_York")
FEATURE_FIELDS = (
    "price", "entry", "entry_zone", "confirmation_level", "maximum_acceptable_entry",
    "stop", "target_1", "target_2", "risk_reward", "distance_from_vwap",
    "distance_from_support", "distance_from_resistance", "distance_from_day_high",
    "distance_from_day_low", "gap_percent", "opening_range_position",
    "breakout_distance", "ema9", "ema21", "ema20", "ema50", "ema200",
    "ema_alignment", "ema9_slope", "ema21_slope", "rsi", "vwap",
    "vwap_relationship", "volume_ratio", "relative_volume", "candle_body_percent",
    "range_expansion", "atr", "volatility", "consolidation_duration",
    "trend_alignment", "momentum_direction", "momentum_acceleration",
)
SCORE_FIELDS = (
    "confidence", "quality", "bullish_score", "bearish_score", "trend_score",
    "momentum_score", "volume_score", "volatility_score", "price_action_score",
    "signal", "status", "eligibility_reason", "reasons", "missing_requirements",
)


def eastern_session_segment(timestamp: datetime) -> str:
    local = _aware(timestamp).astimezone(EASTERN).time()
    if local < time(9, 30): return "PREMARKET"
    if local < time(10, 0): return "OPENING_DRIVE"
    if local < time(11, 30): return "MORNING"
    if local < time(13, 30): return "MIDDAY"
    if local < time(15, 30): return "AFTERNOON"
    return "CLOSING_PERIOD"


def setup_feature_snapshot(result: dict, outcome, *, scanner_id="optionbeacon-scanner") -> SetupFeatureSnapshot:
    timestamp = _timestamp(result.get("last_candle_at") or result.get("timestamp") or outcome.timestamp)
    plan = result.get("trade_plan") or {}
    feature_values = {name: _feature_value(result, plan, name) for name in FEATURE_FIELDS}
    feature_values.update(
        {
            "entry": feature_values.get("entry") or outcome.entry,
            "stop": feature_values.get("stop") or outcome.stop,
            "target_1": feature_values.get("target_1") or outcome.target_1,
            "target_2": feature_values.get("target_2") or outcome.target_2,
        }
    )
    market_inputs = dict(result.get("market_context") or {})
    for name in ("spy_direction", "qqq_direction", "market_breadth", "normalized_volatility", "atr_percent", "directional_efficiency"):
        if name in result: market_inputs[name] = result[name]
    regime = classify_market_regime(market_inputs, timestamp=timestamp)
    sector = build_sector_context(
        outcome.symbol, outcome.direction,
        symbol_return=result.get("symbol_session_return"),
        sector_return=result.get("sector_session_return"),
        sector_rank=result.get("sector_rank"), timestamp=timestamp,
    )
    missing = sorted(name for name, value in feature_values.items() if value is None)
    data_quality = {
        "provider": result.get("provider") or result.get("data_source"),
        "freshness": result.get("data_freshness") or result.get("market_data_freshness"),
        "partial_scan": bool(result.get("partial_scan", False)),
        "fallback_state": result.get("fallback_state"),
        "rate_limit_state": result.get("rate_limit_state"),
        "scanner_version": result.get("source_version") or result.get("scanner_version"),
        "missing_feature_flags": missing,
    }
    return SetupFeatureSnapshot(
        opportunity_id=outcome.trade_id,
        trade_plan_id=_trade_plan_id(result), symbol=outcome.symbol,
        direction=outcome.direction, setup_type=outcome.setup,
        scanner_id=scanner_id, generated_timestamp=timestamp,
        entry_timestamp=outcome.entry_time,
        eastern_trading_date=timestamp.astimezone(EASTERN).date().isoformat(),
        session_segment=eastern_session_segment(timestamp), features=feature_values,
        scoring={name: result.get(name) for name in SCORE_FIELDS},
        market_regime=asdict(regime), sector_context=asdict(sector),
        data_quality=data_quality,
    )


def outcome_label(record) -> OutcomeLabel:
    reason = record.exit_reason
    result = _number(record.realized_return)
    if result is None: result_class = "UNRESOLVED"
    elif result > 0: result_class = "WINNER"
    elif result < 0: result_class = "LOSER"
    else: result_class = "BREAKEVEN"
    missing = []
    for field in ("time_to_mfe_minutes", "time_to_mae_minutes"):
        missing.append(field)
    mfe, mae = _number(record.max_favorable_excursion), _number(record.max_adverse_excursion)
    return OutcomeLabel(
        opportunity_id=record.trade_id, entered=record.entry_time is not None,
        never_entered=reason == "NEVER_TRIGGERED", entry_price=record.entry,
        entry_timestamp=record.entry_time, exit_price=_exit_price(record),
        exit_timestamp=record.exit_time, exit_reason=reason, realized_return=result,
        maximum_favorable_excursion=mfe, maximum_adverse_excursion=mae,
        time_to_mfe_minutes=None, time_to_mae_minutes=None,
        target_1_reached=reason in {"TARGET_1", "TARGET_2", "TARGET_3"},
        target_2_reached=reason in {"TARGET_2", "TARGET_3"}, stop_reached=reason == "STOP",
        invalidation_reached=reason in {"INVALIDATED", "TECHNICAL_INVALIDATION"},
        end_of_day_exit=reason == "END_OF_DAY", maximum_hold_exit=reason in {"TIME_EXIT", "MAX_HOLD_TIME", "MAX_HOLD_CANDLES"},
        duration_minutes=record.hold_minutes, result_class=result_class,
        best_available_return=mfe, worst_available_return=mae,
        favorable_before_failure=(mfe > 0 if mfe is not None and result is not None and result < 0 else None),
        failed_immediately=(mfe <= 0 if mfe is not None and result is not None and result < 0 else None),
        setup_quality="OBSERVED" if record.exit_time else "PENDING",
        entry_quality="ENTERED" if record.entry_time else "NOT_ENTERED",
        management_quality="REALIZED" if record.exit_time and record.entry_time else "NOT_EVALUABLE",
        missing_fields=tuple(missing),
    )


def _trade_plan_id(result):
    plan = result.get("trade_plan")
    if isinstance(plan, dict):
        return plan.get("trade_plan_id") or plan.get("id")
    return getattr(plan, "trade_plan_id", None) if plan is not None else None


def _feature_value(result, plan, name):
    if result.get(name) is not None:
        return result[name]
    if not isinstance(plan, dict):
        return getattr(plan, name, None)
    aliases = {
        "entry": ("ideal_entry", "trigger_price", "entry_price"),
        "entry_zone": ("entry_zone", "entry_zone_low"),
        "confirmation_level": ("confirmation_level", "trigger_price"),
        "maximum_acceptable_entry": ("maximum_acceptable_entry", "maximum_entry"),
        "stop": ("technical_stop", "initial_stop", "current_stop"),
        "target_1": ("target_1",), "target_2": ("target_2",),
        "risk_reward": ("risk_reward_target_1", "risk_reward"),
        "distance_from_vwap": ("distance_from_vwap",),
    }
    for key in aliases.get(name, (name,)):
        if plan.get(key) is not None:
            return plan[key]
    return None


def _timestamp(value):
    if isinstance(value, datetime): return _aware(value)
    return _aware(datetime.fromisoformat(str(value).replace("Z", "+00:00")))


def _aware(value): return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _number(value):
    try: number = float(value)
    except (TypeError, ValueError): return None
    return number if math.isfinite(number) else None


def _exit_price(record):
    if record.exit_reason == "STOP": return record.stop
    target = {"TARGET_1": record.target_1, "TARGET_2": record.target_2, "TARGET_3": record.target_3}.get(record.exit_reason)
    if target is not None:
        return target
    realized = _number(record.realized_return)
    if record.exit_reason in {"TIME_EXIT", "END_OF_DAY", "MAX_HOLD_TIME", "MAX_HOLD_CANDLES"} and record.entry and realized is not None:
        return record.entry * (1 - realized / 100 if record.direction == "Bearish" else 1 + realized / 100)
    return None
