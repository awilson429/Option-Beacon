"""Typed models for immutable signals and mutable paper-trade lifecycle state."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


SCHEMA_VERSION = 1


class PlanStatus(str, Enum):
    WAIT = "WAIT"
    WATCH = "WATCH"
    READY = "READY"
    ACTIVE = "ACTIVE"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"
    CLOSED = "CLOSED"


class EntryType(str, Enum):
    BREAKOUT = "Breakout entry"
    PULLBACK = "Pullback entry"
    VWAP_RECLAIM = "VWAP reclaim"
    VWAP_REJECTION = "VWAP rejection"
    EMA_CONTINUATION = "EMA continuation"
    SUPPORT_BOUNCE = "Support bounce"
    RESISTANCE_REJECTION = "Resistance rejection"
    MOMENTUM_CONTINUATION = "Momentum continuation"


class LateEntryRisk(str, Enum):
    LOW = "Low"
    MODERATE = "Moderate"
    HIGH = "High"


class LifecycleEventType(str, Enum):
    CREATED = "CREATED"
    WATCH_STARTED = "WATCH_STARTED"
    CONFIRMATION_REACHED = "CONFIRMATION_REACHED"
    ENTRY_READY = "ENTRY_READY"
    ENTRY_TRIGGERED = "ENTRY_TRIGGERED"
    TARGET_1_REACHED = "TARGET_1_REACHED"
    STOP_MOVED_TO_BREAKEVEN = "STOP_MOVED_TO_BREAKEVEN"
    TRAILING_STOP_ACTIVATED = "TRAILING_STOP_ACTIVATED"
    TRAILING_STOP_UPDATED = "TRAILING_STOP_UPDATED"
    TARGET_2_REACHED = "TARGET_2_REACHED"
    STOPPED_OUT = "STOPPED_OUT"
    BREAKEVEN_STOPPED = "BREAKEVEN_STOPPED"
    TECHNICALLY_INVALIDATED = "TECHNICALLY_INVALIDATED"
    MAX_HOLD_REACHED = "MAX_HOLD_REACHED"
    END_OF_DAY_EXIT = "END_OF_DAY_EXIT"
    EXPIRED = "EXPIRED"
    MANUALLY_CLOSED = "MANUALLY_CLOSED"


class ExitReason(str, Enum):
    STOP_HIT = "STOP_HIT"
    TARGET_1_HIT = "TARGET_1_HIT"
    TARGET_2_HIT = "TARGET_2_HIT"
    TRAILING_STOP_HIT = "TRAILING_STOP_HIT"
    BREAKEVEN_STOP_HIT = "BREAKEVEN_STOP_HIT"
    TECHNICAL_INVALIDATION = "TECHNICAL_INVALIDATION"
    MAX_HOLD_TIME = "MAX_HOLD_TIME"
    MAX_HOLD_CANDLES = "MAX_HOLD_CANDLES"
    END_OF_DAY = "END_OF_DAY"
    MANUAL_CLOSE = "MANUAL_CLOSE"


@dataclass(frozen=True)
class OriginalSignal:
    signal_timestamp: datetime
    market_timestamp: datetime
    underlying_price_at_signal: float
    confidence_score: float
    setup_name: str
    entry_zone_low: float
    entry_zone_high: float
    confirmation_level: float
    maximum_acceptable_entry: float
    initial_stop: float
    target_1: float
    target_2: float
    breakeven_trigger: float
    trailing_stop_activation: float
    trailing_stop_method: str
    maximum_hold_minutes: int
    maximum_hold_candles: int
    reasons_for_trade: tuple[str, ...]
    reasons_to_avoid: tuple[str, ...]
    market_snapshot: dict[str, Any]


@dataclass(frozen=True)
class LifecycleEvent:
    event_id: str
    trade_plan_id: str
    timestamp: datetime
    market_timestamp: datetime
    underlying_price: float
    event_type: LifecycleEventType
    reason: str
    prior_value: Any = None
    new_value: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class FinalOutcome:
    exit_timestamp: datetime
    exit_underlying_price: float
    exit_reason: ExitReason
    realized_return_estimate: float
    hold_time_minutes: float
    hold_time_candles: int
    maximum_favorable_excursion: float
    maximum_adverse_excursion: float


@dataclass
class TradePlan:
    trade_plan_id: str
    symbol: str
    direction: str
    option_bias: str
    setup_name: str
    status: PlanStatus
    signal_timestamp: datetime
    market_timestamp: datetime
    underlying_price_at_signal: float
    current_underlying_price: float
    timeframe: str
    entry_type: EntryType
    ideal_entry: float
    entry_zone_low: float
    entry_zone_high: float
    confirmation_level: float
    maximum_acceptable_entry: float
    initial_stop: float
    stop_method: str
    current_stop: float
    target_1: float
    target_2: float
    breakeven_trigger: float
    trailing_stop_activation: float
    trailing_stop_method: str
    maximum_hold_minutes: int
    maximum_hold_candles: int
    end_of_day_cutoff: str
    confidence_score: float
    late_entry_risk: LateEntryRisk
    late_entry_explanation: str
    risk_reward_target_1: float
    risk_reward_target_2: float
    remaining_reward_target_1: float
    remaining_reward_target_2: float
    original_reward_target_1: float
    original_reward_target_2: float
    invalidation_level: float
    distance_from_trigger: float
    distance_from_vwap: float
    distance_from_ema9: float
    distance_from_ema21: float
    atr_extension: float
    candles_elapsed_since_trigger: int
    reasons_for_trade: list[str]
    reasons_to_avoid: list[str]
    missing_requirements: list[str]
    activation_requirements: list[str]
    invalidation_conditions: list[str]
    market_data_freshness: dict[str, Any]
    original_signal_snapshot: OriginalSignal
    current_status: dict[str, Any]
    lifecycle_events: list[LifecycleEvent] = field(default_factory=list)
    final_outcome: Optional[FinalOutcome] = None
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _encode(asdict(self))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TradePlan":
        values = dict(payload)
        for name in ("signal_timestamp", "market_timestamp"):
            values[name] = _datetime(values[name])
        values["status"] = PlanStatus(values["status"])
        values["entry_type"] = EntryType(values["entry_type"])
        values["late_entry_risk"] = LateEntryRisk(values["late_entry_risk"])
        original = dict(values["original_signal_snapshot"])
        for name in ("signal_timestamp", "market_timestamp"):
            original[name] = _datetime(original[name])
        original["reasons_for_trade"] = tuple(original.get("reasons_for_trade") or ())
        original["reasons_to_avoid"] = tuple(original.get("reasons_to_avoid") or ())
        values["original_signal_snapshot"] = OriginalSignal(**original)
        values["lifecycle_events"] = [
            LifecycleEvent(
                **{
                    **event,
                    "timestamp": _datetime(event["timestamp"]),
                    "market_timestamp": _datetime(event["market_timestamp"]),
                    "event_type": LifecycleEventType(event["event_type"]),
                }
            )
            for event in values.get("lifecycle_events") or []
        ]
        if values.get("final_outcome"):
            outcome = dict(values["final_outcome"])
            outcome["exit_timestamp"] = _datetime(outcome["exit_timestamp"])
            outcome["exit_reason"] = ExitReason(outcome["exit_reason"])
            values["final_outcome"] = FinalOutcome(**outcome)
        return cls(**values)


def _datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _encode(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_encode(item) for item in value]
    if isinstance(value, list):
        return [_encode(item) for item in value]
    if isinstance(value, dict):
        return {key: _encode(item) for key, item in value.items()}
    return value
