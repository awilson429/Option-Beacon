"""Typed, serializable records for OptionBeacon's shadow intelligence layer."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


INTELLIGENCE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class MarketRegimeSnapshot:
    regime: str
    confidence_band: str
    contributing_factors: tuple[str, ...]
    timestamp: datetime
    data_quality_status: str


@dataclass(frozen=True)
class SectorContextSnapshot:
    sector: str
    sector_benchmark: str | None
    sector_rank: int | None
    sector_trend: str
    relative_strength_score: float | None
    alignment_status: str
    reason_codes: tuple[str, ...]
    timestamp: datetime


@dataclass(frozen=True)
class SetupFeatureSnapshot:
    opportunity_id: str
    trade_plan_id: str | None
    symbol: str
    direction: str
    setup_type: str
    scanner_id: str
    generated_timestamp: datetime
    entry_timestamp: datetime | None
    eastern_trading_date: str
    session_segment: str
    features: dict[str, Any]
    scoring: dict[str, Any]
    market_regime: dict[str, Any]
    sector_context: dict[str, Any]
    data_quality: dict[str, Any]
    schema_version: int = INTELLIGENCE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _encode(asdict(self))


@dataclass(frozen=True)
class OutcomeLabel:
    opportunity_id: str
    entered: bool
    never_entered: bool
    entry_price: float | None
    entry_timestamp: datetime | None
    exit_price: float | None
    exit_timestamp: datetime | None
    exit_reason: str | None
    realized_return: float | None
    maximum_favorable_excursion: float | None
    maximum_adverse_excursion: float | None
    time_to_mfe_minutes: float | None
    time_to_mae_minutes: float | None
    target_1_reached: bool
    target_2_reached: bool
    stop_reached: bool
    invalidation_reached: bool
    end_of_day_exit: bool
    maximum_hold_exit: bool
    duration_minutes: float | None
    result_class: str
    best_available_return: float | None
    worst_available_return: float | None
    favorable_before_failure: bool | None
    failed_immediately: bool | None
    setup_quality: str
    entry_quality: str
    management_quality: str
    missing_fields: tuple[str, ...] = field(default_factory=tuple)
    schema_version: int = INTELLIGENCE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _encode(asdict(self))


def _encode(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_encode(item) for item in value]
    if isinstance(value, list):
        return [_encode(item) for item in value]
    if isinstance(value, dict):
        return {key: _encode(item) for key, item in value.items()}
    return value
