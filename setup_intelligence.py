"""Historical setup context for current OptionBeacon trade plans."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Iterable

from signal_history import TradeOutcome
from trade_analytics import (
    analytics_records,
    confidence_bucket,
    overall_trade_analytics,
)


DEFAULT_MINIMUM_SAMPLE_SIZE = 10


def _finite_number(value) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _current_fields(current: dict) -> dict:
    current = current or {}
    plan = current.get("trade_plan") or current
    return {
        "setup": plan.get("setup_type")
        or plan.get("setup")
        or current.get("setup"),
        "direction": plan.get("direction")
        or current.get("direction")
        or current.get("bias"),
        "symbol": current.get("symbol") or plan.get("symbol"),
        "confidence": _finite_number(
            current.get("confidence", plan.get("confidence"))
        ),
    }


def _eligible_records(records: Iterable[TradeOutcome]) -> list[TradeOutcome]:
    return [
        record
        for record in records
        if record.exit_time is not None
        and bool(record.exit_reason)
        and record.exit_reason != "NEVER_TRIGGERED"
        and _finite_number(record.realized_return) is not None
    ]


def _select_matches(
    records: list[TradeOutcome],
    current: dict,
    minimum_sample_size: int,
) -> tuple[str, list[TradeOutcome]]:
    setup = current["setup"]
    direction = current["direction"]
    symbol = current["symbol"]
    if not setup:
        return "NO_MATCH", []

    levels = (
        (
            "LEVEL_1",
            [
                record
                for record in records
                if record.setup == setup
                and record.direction == direction
                and record.symbol == symbol
            ],
        ),
        (
            "LEVEL_2",
            [
                record
                for record in records
                if record.setup == setup and record.direction == direction
            ],
        ),
        (
            "LEVEL_3",
            [record for record in records if record.setup == setup],
        ),
    )
    for level, matches in levels:
        if len(matches) >= minimum_sample_size:
            return level, matches

    for level, matches in reversed(levels):
        if matches:
            return level, matches
    return "NO_MATCH", []


def historical_grade(
    sample_size: int,
    win_rate: float | None,
    expectancy: float | None,
    *,
    minimum_sample_size: int = DEFAULT_MINIMUM_SAMPLE_SIZE,
) -> str:
    """Grade historical evidence without changing the current signal score."""
    if sample_size < minimum_sample_size:
        return "INSUFFICIENT DATA"

    win_rate = win_rate if win_rate is not None else 0.0
    expectancy = expectancy if expectancy is not None else 0.0
    if expectancy < 0 or win_rate < 45:
        return "WEAK"
    if expectancy > 0 and win_rate >= 65:
        return "STRONG"
    if expectancy > 0 and win_rate >= 55:
        return "POSITIVE"
    return "MIXED"


def _rate(records: list[TradeOutcome], exit_reason: str) -> float | None:
    if not records:
        return None
    return (
        sum(record.exit_reason == exit_reason for record in records)
        / len(records)
        * 100
    )


def _confidence_calibration(
    records: list[TradeOutcome],
    current_confidence: float | None,
) -> dict:
    if current_confidence is None:
        return {
            "confidence_bucket": "Unknown",
            "current_confidence": None,
            "historical_confidence_win_rate": None,
            "confidence_gap": None,
        }

    bucket = confidence_bucket(current_confidence)
    bucket_records = [
        record
        for record in records
        if confidence_bucket(record.confidence) == bucket
    ]
    metrics = overall_trade_analytics(bucket_records)
    historical_win_rate = metrics["win_rate"]
    return {
        "confidence_bucket": bucket,
        "current_confidence": current_confidence,
        "historical_confidence_win_rate": historical_win_rate,
        "confidence_gap": (
            historical_win_rate - current_confidence
            if historical_win_rate is not None
            else None
        ),
    }


def setup_intelligence(
    current: dict,
    history: Iterable[TradeOutcome] | str | Path,
    *,
    minimum_sample_size: int = DEFAULT_MINIMUM_SAMPLE_SIZE,
) -> dict:
    """Compare a current result or trade plan with eligible historical outcomes."""
    current_fields = _current_fields(current)
    eligible = _eligible_records(analytics_records(history))
    match_level, matches = _select_matches(
        eligible,
        current_fields,
        minimum_sample_size,
    )
    metrics = overall_trade_analytics(matches)
    sample_size = len(matches)
    result = {
        "match_level": match_level,
        "sample_size": sample_size,
        "wins": metrics["wins"],
        "losses": metrics["losses"],
        "breakeven": metrics["breakeven"],
        "win_rate": metrics["win_rate"],
        "average_return": metrics["average_return"],
        "median_return": metrics["median_return"],
        "expectancy": metrics["expectancy"],
        "profit_factor": metrics["profit_factor"],
        "average_hold_minutes": metrics["average_hold_minutes"],
        "average_mfe": metrics["average_mfe"],
        "average_mae": metrics["average_mae"],
        "target_1_rate": _rate(matches, "TARGET_1"),
        "target_2_rate": _rate(matches, "TARGET_2"),
        "target_3_rate": _rate(matches, "TARGET_3"),
        "stop_rate": _rate(matches, "STOP"),
        "time_exit_rate": _rate(matches, "TIME_EXIT"),
    }
    result["historical_grade"] = historical_grade(
        sample_size,
        result["win_rate"],
        result["expectancy"],
        minimum_sample_size=minimum_sample_size,
    )
    result.update(
        _confidence_calibration(
            eligible,
            current_fields["confidence"],
        )
    )
    return result
