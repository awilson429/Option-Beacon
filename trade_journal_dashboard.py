"""Pure view helpers for the read-only TradeOutcome journal dashboard."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Iterable

from signal_history import (
    DEFAULT_MIN_ENTRY_CONFIDENCE,
    TradeOutcome,
    entry_confidence_eligible,
)
from trade_analytics import confidence_bucket


UNAVAILABLE = "—"
STATUS_OPTIONS = (
    "All",
    "Candidates",
    "Entered/Open",
    "Closed",
    "Never Triggered",
)


def trade_outcome_status(record: TradeOutcome) -> str:
    """Return the journal status label for one outcome record."""
    if record.exit_reason == "NEVER_TRIGGERED":
        return "NEVER TRIGGERED"
    if record.exit_time is not None:
        return "CLOSED"
    if record.entry_time is not None:
        return "OPEN"
    return "CANDIDATE"


def entry_eligibility_label(
    record: TradeOutcome,
    minimum_entry_confidence: float = DEFAULT_MIN_ENTRY_CONFIDENCE,
) -> str:
    """Return a read-only explanation of candidate entry eligibility."""
    if trade_outcome_status(record) != "CANDIDATE":
        return UNAVAILABLE
    if not entry_confidence_eligible(record, minimum_entry_confidence):
        return "WATCH ONLY — BELOW ENTRY CONFIDENCE"
    return "ENTRY ELIGIBLE"


def filter_trade_outcomes(
    records: Iterable[TradeOutcome],
    *,
    symbol: str = "All",
    setup: str = "All",
    direction: str = "All",
    exit_reason: str = "All",
    confidence: str = "All",
    status: str = "All",
) -> list[TradeOutcome]:
    """Filter outcomes using the dashboard's single-select controls."""
    status_labels = {
        "Candidates": "CANDIDATE",
        "Entered/Open": "OPEN",
        "Closed": "CLOSED",
        "Never Triggered": "NEVER TRIGGERED",
    }
    expected_status = status_labels.get(status)
    filtered = []
    for record in records:
        if symbol != "All" and record.symbol != symbol:
            continue
        if setup != "All" and record.setup != setup:
            continue
        if direction != "All" and record.direction != direction:
            continue
        if exit_reason != "All" and record.exit_reason != exit_reason:
            continue
        if confidence != "All" and confidence_bucket(record.confidence) != confidence:
            continue
        if expected_status and trade_outcome_status(record) != expected_status:
            continue
        filtered.append(record)
    return filtered


def sort_trade_outcomes_newest(
    records: Iterable[TradeOutcome],
) -> list[TradeOutcome]:
    """Sort outcomes by signal timestamp, newest first."""
    def timestamp_value(record):
        value = record.timestamp or datetime.min.replace(tzinfo=timezone.utc)
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()

    return sorted(
        records,
        key=timestamp_value,
        reverse=True,
    )


def format_metric(value, *, percentage: bool = False, decimals: int = 2) -> str:
    """Format a dashboard metric without leaking unavailable numeric sentinels."""
    if value is None:
        return UNAVAILABLE
    try:
        number = float(value)
    except (TypeError, ValueError):
        return UNAVAILABLE
    if not math.isfinite(number):
        return UNAVAILABLE
    suffix = "%" if percentage else ""
    return f"{number:.{decimals}f}{suffix}"


def _format_timestamp(value) -> str:
    if value is None:
        return UNAVAILABLE
    return value.strftime("%Y-%m-%d %H:%M")


def _format_price(value) -> str:
    if value is None:
        return UNAVAILABLE
    try:
        number = float(value)
    except (TypeError, ValueError):
        return UNAVAILABLE
    return f"${number:.2f}" if math.isfinite(number) else UNAVAILABLE


def trade_history_rows(records: Iterable[TradeOutcome]) -> list[dict]:
    """Return newest-first, consistently formatted trade-history rows."""
    rows = []
    for record in sort_trade_outcomes_newest(records):
        rows.append(
            {
                "Signal Time": _format_timestamp(record.timestamp),
                "Symbol": record.symbol,
                "Direction": record.direction,
                "Setup": record.setup,
                "Confidence": format_metric(record.confidence, decimals=0),
                "Entry": _format_price(record.entry),
                "Stop": _format_price(record.stop),
                "Target 1": _format_price(record.target_1),
                "Target 2": _format_price(record.target_2),
                "Target 3": _format_price(record.target_3),
                "Entry Time": _format_timestamp(record.entry_time),
                "Exit Time": _format_timestamp(record.exit_time),
                "Exit Reason": record.exit_reason or UNAVAILABLE,
                "Realized Return": format_metric(
                    record.realized_return,
                    percentage=True,
                ),
                "MFE": format_metric(
                    record.max_favorable_excursion,
                    percentage=True,
                ),
                "MAE": format_metric(
                    record.max_adverse_excursion,
                    percentage=True,
                ),
                "Hold Minutes": format_metric(record.hold_minutes),
                "Status": trade_outcome_status(record),
                "Entry Eligibility": entry_eligibility_label(record),
            }
        )
    return rows


def grouped_performance_rows(rows: Iterable[dict]) -> list[dict]:
    """Format analytics-engine group rows for consistent display."""
    return [
        {
            "Group": row["group"],
            "Total": row["total"],
            "Wins": row["wins"],
            "Losses": row["losses"],
            "Win Rate": format_metric(row["win_rate"], percentage=True),
            "Average Return": format_metric(
                row["average_return"],
                percentage=True,
            ),
            "Expectancy": format_metric(row["expectancy"], percentage=True),
            "Average Hold Minutes": format_metric(row["average_hold_minutes"]),
        }
        for row in rows
    ]
