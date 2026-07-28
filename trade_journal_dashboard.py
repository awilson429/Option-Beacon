"""Pure view helpers for the read-only TradeOutcome journal dashboard."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from statistics import mean
from typing import Iterable

from live_trade_coach_dashboard import open_trade_coach_output
from signal_history import (
    DEFAULT_MIN_ENTRY_CONFIDENCE,
    TradeOutcome,
    entry_confidence_eligible,
)
from trade_analytics import confidence_bucket
from trade_desk_view_models import position_health


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


def format_signed_return(value, *, decimals: int = 2) -> str:
    """Format a finite percentage return with an explicit positive sign."""
    if value is None:
        return UNAVAILABLE
    try:
        number = float(value)
    except (TypeError, ValueError):
        return UNAVAILABLE
    if not math.isfinite(number):
        return UNAVAILABLE
    if number > 0:
        return f"+{number:.{decimals}f}%"
    return f"{number:.{decimals}f}%"


def _finite_number(value) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def journal_summary_metrics(records: Iterable[TradeOutcome]) -> dict:
    """Calculate filtered Trade Journal performance and activity metrics."""
    records = list(records)
    open_records = [
        record
        for record in records
        if record.entry_time is not None and record.exit_time is None
    ]
    closed_records = [
        record
        for record in records
        if record.entry_time is not None and record.exit_time is not None
    ]
    returns = [
        value
        for value in (
            _finite_number(record.realized_return) for record in closed_records
        )
        if value is not None
    ]
    winners = [value for value in returns if value > 0]
    losers = [value for value in returns if value < 0]
    breakeven = [value for value in returns if value == 0]
    decided = len(winners) + len(losers)
    hold_minutes = [
        value
        for value in (
            _finite_number(record.hold_minutes) for record in closed_records
        )
        if value is not None
    ]
    if losers:
        profit_factor = sum(winners) / abs(sum(losers))
    elif winners:
        profit_factor = math.inf
    else:
        profit_factor = None
    return {
        "open_trades": len(open_records),
        "closed_trades": len(closed_records),
        "winning_trades": len(winners),
        "losing_trades": len(losers),
        "breakeven_trades": len(breakeven),
        "win_rate": len(winners) / decided * 100 if decided else None,
        "average_return": mean(returns) if returns else None,
        "total_signals": len(records),
        "candidates_watch_only": sum(
            record.entry_time is None and record.exit_time is None
            for record in records
        ),
        "never_triggered": sum(
            record.exit_reason == "NEVER_TRIGGERED" for record in records
        ),
        "average_hold_minutes": mean(hold_minutes) if hold_minutes else None,
        "profit_factor": profit_factor,
        "expectancy": mean(returns) if returns else None,
    }


def performance_caption(completed_trades: int, open_trades: int) -> str:
    """Return the filtered completed/open activity caption."""
    completed_label = "trade" if completed_trades == 1 else "trades"
    open_label = "trade remains" if open_trades == 1 else "trades remain"
    return (
        f"Performance statistics are based on {completed_trades} completed "
        f"{completed_label}. {open_trades} {open_label} open."
    )


def _timestamp_value(value) -> float:
    if value is None:
        return float("-inf")
    timestamp = value
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.timestamp()


def active_edge_analytics(
    records: Iterable[TradeOutcome],
    current_prices: dict[str, float | None],
    current_timestamp: datetime,
    quote_status: dict[str, str] | None = None,
) -> dict:
    """Calculate unrealized metrics via the existing Live Trade Coach."""
    open_records = [
        record
        for record in records
        if record.entry_time is not None and record.exit_time is None
    ]
    open_records.sort(
        key=lambda record: _timestamp_value(record.entry_time),
        reverse=True,
    )
    returns = []
    target_progress = []
    risk_remaining = []
    minutes_open = []
    rows = []
    winning_now = losing_now = breakeven_now = 0
    healthy = need_attention = 0
    quote_status = quote_status or {}

    for record in open_records:
        price = _finite_number(current_prices.get(record.symbol))
        coach = open_trade_coach_output(record, price, current_timestamp) or {}
        current_return = _finite_number(coach.get("current_return"))
        progress = _finite_number(coach.get("progress_to_target_1"))
        remaining = _finite_number(coach.get("risk_remaining"))
        health = position_health(
            current_price=price,
            current_return=current_return,
            risk_remaining=remaining,
            coach_status=coach.get("status"),
            stop_threatened=coach.get("stop_threatened", False),
        )
        if health["label"] == "Healthy":
            healthy += 1
        elif health["label"] in {"Watch", "Action Needed"}:
            need_attention += 1
        if current_return is not None:
            returns.append(current_return)
            if current_return > 0:
                winning_now += 1
            elif current_return < 0:
                losing_now += 1
            else:
                breakeven_now += 1
        if progress is not None:
            target_progress.append(progress)
        if remaining is not None:
            risk_remaining.append(remaining)

        entered_at = record.entry_time
        if entered_at is not None:
            checked_at = current_timestamp
            if entered_at.tzinfo is None:
                entered_at = entered_at.replace(tzinfo=timezone.utc)
            if checked_at.tzinfo is None:
                checked_at = checked_at.replace(tzinfo=timezone.utc)
            elapsed = max(
                0.0,
                (checked_at - entered_at).total_seconds() / 60,
            )
            minutes_open.append(elapsed)
        else:
            elapsed = None

        rows.append(
            {
                "Symbol": record.symbol,
                "Direction": record.direction,
                "Entry": _format_price(record.entry),
                "Current Price": _format_price(price),
                "Open Return": format_signed_return(current_return),
                "Minutes Open": format_metric(elapsed),
                "Target 1 Progress": format_metric(
                    progress,
                    percentage=True,
                ),
                "Risk Remaining": format_metric(
                    remaining,
                    percentage=True,
                ),
                "Coach Status": coach.get("status") or "UNAVAILABLE",
                "Position Health": health["label"],
                "Quote Status": (
                    quote_status.get(record.symbol, "Live quote unavailable")
                    if price is None
                    else UNAVAILABLE
                ),
            }
        )

    return {
        "open_positions": len(open_records),
        "winning_now": winning_now,
        "losing_now": losing_now,
        "breakeven_now": breakeven_now,
        "healthy": healthy,
        "need_attention": need_attention,
        "average_open_return": mean(returns) if returns else None,
        "average_minutes_open": mean(minutes_open) if minutes_open else None,
        "average_target_1_progress": (
            mean(target_progress) if target_progress else None
        ),
        "average_risk_remaining": (
            mean(risk_remaining) if risk_remaining else None
        ),
        "rows": rows,
    }


def opened_alert_status(record: TradeOutcome) -> str:
    """Return the validation status for an entered alert."""
    if record.exit_time is None:
        return "OPEN"
    statuses = {
        "TARGET_1": "TARGET 1",
        "TARGET_2": "TARGET 2",
        "TARGET_3": "TARGET 3",
        "STOP": "STOPPED",
        "TIME_EXIT": "TIME EXIT",
    }
    return statuses.get(record.exit_reason, "CLOSED")


def opened_alerts_analytics(
    records: Iterable[TradeOutcome],
    current_prices: dict[str, float | None],
    current_timestamp: datetime,
    quote_status: dict[str, str] | None = None,
) -> dict:
    """Build filtered entered-alert validation metrics and display rows."""
    entered = [record for record in records if record.entry_time is not None]
    entered.sort(
        key=lambda record: _timestamp_value(record.entry_time),
        reverse=True,
    )
    open_records = [record for record in entered if record.exit_time is None]
    closed_records = [record for record in entered if record.exit_time is not None]
    realized_returns = [
        value
        for value in (
            _finite_number(record.realized_return) for record in closed_records
        )
        if value is not None
    ]
    winners = [value for value in realized_returns if value > 0]
    losers = [value for value in realized_returns if value < 0]
    breakeven = [value for value in realized_returns if value == 0]
    decided = len(winners) + len(losers)
    rows = []
    quote_status = quote_status or {}

    for record in entered:
        is_open = record.exit_time is None
        price = (
            _finite_number(current_prices.get(record.symbol))
            if is_open
            else None
        )
        coach = (
            open_trade_coach_output(record, price, current_timestamp) or {}
            if is_open
            else {}
        )
        health = position_health(
            current_price=price,
            current_return=_finite_number(coach.get("current_return")),
            risk_remaining=_finite_number(coach.get("risk_remaining")),
            coach_status=coach.get("status"),
            stop_threatened=coach.get("stop_threatened", False),
        ) if is_open else {"label": "Closed", "treatment": "neutral"}
        rows.append(
            {
                "Entry Time": _format_timestamp(record.entry_time),
                "Entry Datetime": record.entry_time,
                "Symbol": record.symbol,
                "Direction": record.direction,
                "Setup": record.setup,
                "Confidence": format_metric(record.confidence, decimals=0),
                "Entry": _format_price(record.entry),
                "Current Price": _format_price(price),
                "Stop": _format_price(record.stop),
                "Target 1": _format_price(record.target_1),
                "Open Return": format_signed_return(
                    _finite_number(coach.get("current_return"))
                ),
                "Position Health": health["label"],
                "Status": opened_alert_status(record),
                "Coach Status": coach.get("status") or UNAVAILABLE,
                "Suggested Action": coach.get("action") or UNAVAILABLE,
                "Exit Time": _format_timestamp(record.exit_time),
                "Exit Reason": record.exit_reason or UNAVAILABLE,
                "Realized Return": format_signed_return(
                    record.realized_return
                ),
                "Followed Manually": "Not Recorded",
                "Manual Result": "Not Recorded",
                "Quote Status": (
                    quote_status.get(record.symbol, "Live quote unavailable")
                    if is_open and price is None
                    else UNAVAILABLE
                ),
            }
        )

    return {
        "opened_alerts": len(entered),
        "currently_open": len(open_records),
        "closed_alerts": len(closed_records),
        "winners": len(winners),
        "losers": len(losers),
        "breakeven": len(breakeven),
        "win_rate": len(winners) / decided * 100 if decided else None,
        "average_realized_return": (
            mean(realized_returns) if realized_returns else None
        ),
        "rows": rows,
    }


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
