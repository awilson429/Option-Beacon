"""Deterministic analytics for recorded OptionBeacon trade outcomes."""

from __future__ import annotations

import math
from pathlib import Path
from statistics import mean, median
from typing import Iterable

from signal_history import TradeOutcome, load_trade_outcomes


CONFIDENCE_BUCKETS = (
    ("0-69", 0, 69),
    ("70-79", 70, 79),
    ("80-89", 80, 89),
    ("90-94", 90, 94),
    ("95-100", 95, 100),
)


def analytics_records(
    source: Iterable[TradeOutcome] | str | Path,
) -> list[TradeOutcome]:
    """Return records from an in-memory collection or JSON Lines history path."""
    if isinstance(source, (str, Path)):
        return load_trade_outcomes(source)
    return list(source)


def confidence_bucket(confidence: float) -> str:
    """Return the configured inclusive bucket for a confidence value."""
    try:
        value = float(confidence)
    except (TypeError, ValueError):
        return "Unknown"
    for label, lower, upper in CONFIDENCE_BUCKETS:
        if lower <= value <= upper:
            return label
    return "Unknown"


def _closed(record: TradeOutcome) -> bool:
    return record.exit_time is not None and bool(record.exit_reason)


def _number(value) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _average(values) -> float | None:
    usable = [value for value in (_number(item) for item in values) if value is not None]
    return mean(usable) if usable else None


def _performance_records(
    records: Iterable[TradeOutcome],
    *,
    closed_only: bool,
    exclude_never_triggered: bool,
) -> list[TradeOutcome]:
    return [
        record
        for record in records
        if (not closed_only or _closed(record))
        and (
            not exclude_never_triggered
            or record.exit_reason != "NEVER_TRIGGERED"
        )
    ]


def _return_metrics(records: Iterable[TradeOutcome]) -> dict:
    records = list(records)
    returns = [
        value
        for value in (_number(record.realized_return) for record in records)
        if value is not None
    ]
    winners = [value for value in returns if value > 0]
    losers = [value for value in returns if value < 0]
    breakeven = [value for value in returns if value == 0]
    decided = len(winners) + len(losers)

    if losers:
        profit_factor = sum(winners) / abs(sum(losers))
    elif winners:
        profit_factor = math.inf
    else:
        profit_factor = None

    average_return = mean(returns) if returns else None
    return {
        "wins": len(winners),
        "losses": len(losers),
        "breakeven": len(breakeven),
        "win_rate": (len(winners) / decided * 100) if decided else None,
        "average_return": average_return,
        "median_return": median(returns) if returns else None,
        "average_winner": mean(winners) if winners else None,
        "average_loser": mean(losers) if losers else None,
        "profit_factor": profit_factor,
        "expectancy": average_return,
    }


def overall_trade_analytics(
    records: Iterable[TradeOutcome],
    *,
    closed_only: bool = True,
    exclude_never_triggered: bool = True,
) -> dict:
    """Calculate overall inventory, performance, excursion, and exit metrics."""
    all_records = list(records)
    closed_records = [record for record in all_records if _closed(record)]
    performance_records = _performance_records(
        all_records,
        closed_only=closed_only,
        exclude_never_triggered=exclude_never_triggered,
    )
    metrics = {
        "total_signals": len(all_records),
        "entered_trades": sum(record.entry_time is not None for record in all_records),
        "closed_trades": len(closed_records),
        "never_triggered": sum(
            record.exit_reason == "NEVER_TRIGGERED" for record in closed_records
        ),
    }
    metrics.update(_return_metrics(performance_records))
    metrics.update(
        {
            "average_hold_minutes": _average(
                record.hold_minutes for record in performance_records
            ),
            "average_mfe": _average(
                record.max_favorable_excursion for record in performance_records
            ),
            "average_mae": _average(
                record.max_adverse_excursion for record in performance_records
            ),
            "target_1_hits": sum(
                record.exit_reason == "TARGET_1" for record in closed_records
            ),
            "target_2_hits": sum(
                record.exit_reason == "TARGET_2" for record in closed_records
            ),
            "target_3_hits": sum(
                record.exit_reason == "TARGET_3" for record in closed_records
            ),
            "stop_hits": sum(record.exit_reason == "STOP" for record in closed_records),
            "time_exits": sum(
                record.exit_reason == "TIME_EXIT" for record in closed_records
            ),
        }
    )
    return metrics


def grouped_trade_analytics(
    records: Iterable[TradeOutcome],
    group_by: str,
    *,
    closed_only: bool = True,
    exclude_never_triggered: bool = True,
) -> list[dict]:
    """Calculate performance metrics grouped by one supported record field."""
    records = _performance_records(
        records,
        closed_only=closed_only,
        exclude_never_triggered=exclude_never_triggered,
    )
    if group_by == "confidence":
        group_value = lambda record: confidence_bucket(record.confidence)
    elif group_by in {"symbol", "setup", "direction"}:
        group_value = lambda record: str(getattr(record, group_by) or "Unknown")
    else:
        raise ValueError(f"Unsupported analytics group: {group_by}")

    groups = {}
    for record in records:
        groups.setdefault(group_value(record), []).append(record)

    if group_by == "confidence":
        order = {
            label: index
            for index, (label, _lower, _upper) in enumerate(CONFIDENCE_BUCKETS)
        }
        names = sorted(groups, key=lambda name: (order.get(name, len(order)), name))
    else:
        names = sorted(groups)

    results = []
    for name in names:
        group_records = groups[name]
        returns = _return_metrics(group_records)
        results.append(
            {
                "group": name,
                "total": len(group_records),
                "wins": returns["wins"],
                "losses": returns["losses"],
                "win_rate": returns["win_rate"],
                "average_return": returns["average_return"],
                "expectancy": returns["expectancy"],
                "average_hold_minutes": _average(
                    record.hold_minutes for record in group_records
                ),
            }
        )
    return results


def analyze_trade_outcomes(
    source: Iterable[TradeOutcome] | str | Path,
    *,
    closed_only: bool = True,
    exclude_never_triggered: bool = True,
) -> dict:
    """Return overall and grouped analytics suitable for later UI rendering."""
    records = analytics_records(source)
    options = {
        "closed_only": closed_only,
        "exclude_never_triggered": exclude_never_triggered,
    }
    return {
        "overall": overall_trade_analytics(records, **options),
        "by_symbol": grouped_trade_analytics(records, "symbol", **options),
        "by_setup": grouped_trade_analytics(records, "setup", **options),
        "by_direction": grouped_trade_analytics(records, "direction", **options),
        "by_confidence_bucket": grouped_trade_analytics(
            records,
            "confidence",
            **options,
        ),
    }
