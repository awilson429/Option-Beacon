"""Deterministic view models for the OptionBeacon Trade Desk."""

from __future__ import annotations

import math
from datetime import date, datetime, timezone
from statistics import mean
from typing import Iterable
from zoneinfo import ZoneInfo

from signal_history import TradeOutcome


EASTERN = ZoneInfo("America/New_York")


def eastern_trade_date(value: datetime | None) -> date | None:
    """Return the New York trading date for a persisted timestamp."""
    if value is None:
        return None
    timestamp = value
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(EASTERN).date()


UNAVAILABLE = "—"


def finite_number(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def historical_edge_grade(evidence: dict | None) -> str:
    """Return a conservative display grade from existing historical evidence."""
    evidence = evidence or {}
    sample = finite_number(evidence.get("sample_size"))
    win_rate = finite_number(evidence.get("win_rate"))
    average_return = finite_number(evidence.get("average_return"))
    profit_factor = finite_number(evidence.get("profit_factor"))
    if sample is None or sample < 10 or win_rate is None or average_return is None:
        return "Insufficient Data"
    if (
        sample >= 30
        and win_rate >= 65
        and average_return > 0
        and (profit_factor is None or profit_factor >= 1.5)
    ):
        return "A+"
    if (
        sample >= 20
        and win_rate >= 58
        and average_return > 0
        and (profit_factor is None or profit_factor >= 1.2)
    ):
        return "A"
    if sample >= 10 and win_rate >= 52 and average_return >= 0:
        return "B"
    return "C"


def historical_edge_summary(evidence: dict | None) -> str:
    """Build concise, deterministic supporting text without false precision."""
    evidence = evidence or {}
    grade = historical_edge_grade(evidence)
    if grade == "Insufficient Data":
        return "Historical evidence is not yet sufficient."
    sample = int(finite_number(evidence.get("sample_size")) or 0)
    win_rate = finite_number(evidence.get("win_rate"))
    average_return = finite_number(evidence.get("average_return"))
    trade_word = "trade" if sample == 1 else "trades"
    return (
        f"{sample} similar {trade_word} · {win_rate:.0f}% wins · "
        f"{average_return:+.2f}% average return"
    )


def opportunity_entry_presentation(
    eligibility: dict,
    *,
    is_open: bool,
    coach: dict | None = None,
) -> dict:
    """Return a truthful hero state without manufacturing coach decisions."""
    if not eligibility.get("eligible"):
        return {
            "eligibility": "NOT ELIGIBLE",
            "entry_status": "DEVELOPING",
            "suggested_action": "WATCH — NOT ELIGIBLE",
            "coach_status": UNAVAILABLE,
            "treatment": "neutral",
        }
    if not is_open:
        return {
            "eligibility": "QUALIFIED",
            "entry_status": "WAITING FOR TRIGGER",
            "suggested_action": "WAIT FOR ENTRY",
            "coach_status": UNAVAILABLE,
            "treatment": "neutral",
        }
    coach = coach or {}
    return {
        "eligibility": "QUALIFIED",
        "entry_status": "OPEN",
        "suggested_action": coach.get("action") or coach.get("status") or UNAVAILABLE,
        "coach_status": coach.get("status") or UNAVAILABLE,
        "treatment": {
            "HOLD": "positive",
            "PROTECT PROFIT": "caution",
            "TAKE PARTIAL": "caution",
            "EXIT": "negative",
        }.get(str(coach.get("status") or "").upper(), "neutral"),
    }


def position_health(
    *,
    current_price,
    current_return,
    risk_remaining,
    coach_status,
    stop_threatened=False,
) -> dict:
    """Interpret canonical coach metrics without changing coach decisions."""
    price = finite_number(current_price)
    current_return = finite_number(current_return)
    risk_remaining = finite_number(risk_remaining)
    status = str(coach_status or "UNAVAILABLE").upper()
    if price is None or current_return is None or risk_remaining is None:
        label, treatment = "Unavailable", "neutral"
    elif status in {"EXIT", "EXIT BEFORE CLOSE"} or stop_threatened or risk_remaining <= 0:
        label, treatment = "Action Needed", "negative"
    elif (
        current_return < 0
        or status in {"PROTECT PROFIT", "TAKE PARTIAL"}
        or risk_remaining < 35
    ):
        label, treatment = "Watch", "caution"
    else:
        label, treatment = "Healthy", "positive"
    return {"label": label, "treatment": treatment}


def attention_positions(rows: Iterable[dict]) -> list[dict]:
    """Filter and sort compact attention rows from entered-alert view models."""
    priority = {"Action Needed": 0, "Watch": 1}
    selected = [
        dict(row)
        for row in rows
        if row.get("Position Health") in priority
    ]

    def timestamp(value) -> float:
        if not isinstance(value, datetime):
            return float("-inf")
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()

    return sorted(
        selected,
        key=lambda row: (
            priority[row["Position Health"]],
            timestamp(row.get("Recommendation Time"))
            if row.get("Recommendation Time") is not None
            else -timestamp(row.get("Entry Datetime")),
        ),
    )


def daily_scorecard(
    records: Iterable[TradeOutcome],
    trading_date: date,
) -> dict:
    """Summarize entered alerts for one trading date."""
    entered = [
        record
        for record in records
        if record.entry_time is not None
        and eastern_trade_date(record.entry_time) == trading_date
    ]
    closed = [record for record in entered if record.exit_time is not None]
    returns = [
        value
        for value in (finite_number(record.realized_return) for record in closed)
        if value is not None
    ]
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value < 0]
    breakeven = [value for value in returns if value == 0]
    decided = len(wins) + len(losses)
    holds = [
        value
        for value in (finite_number(record.hold_minutes) for record in closed)
        if value is not None
    ]
    return {
        "opened_alerts": len(entered),
        "closed_trades": len(closed),
        "winners": len(wins),
        "losers": len(losses),
        "breakeven": len(breakeven),
        "win_rate": len(wins) / decided * 100 if decided else None,
        "average_realized_return": mean(returns) if returns else None,
        "best_trade": max(returns) if returns else None,
        "worst_trade": min(returns) if returns else None,
        "average_hold_minutes": mean(holds) if holds else None,
    }


def trade_timeline(record: TradeOutcome) -> list[dict]:
    """Build lifecycle events using only timestamps persisted on the record."""
    events = []
    if record.timestamp is not None:
        events.append(
            {
                "timestamp": record.timestamp,
                "event": "Alert recorded",
                "detail": record.setup or "",
            }
        )
    if record.entry_time is not None:
        events.append(
            {
                "timestamp": record.entry_time,
                "event": "Entry triggered",
                "detail": _price_detail(record.entry),
            }
        )
    if record.exit_time is not None:
        reasons = {
            "TARGET_1": "Target 1 reached",
            "TARGET_2": "Target 2 reached",
            "TARGET_3": "Target 3 reached",
            "STOP": "Stop reached",
            "TIME_EXIT": "Time exit",
            "END_OF_DAY": "End-of-day exit",
        }
        event = reasons.get(record.exit_reason)
        if event:
            events.append(
                {
                    "timestamp": record.exit_time,
                    "event": event,
                    "detail": "",
                }
            )
        events.append(
            {
                "timestamp": record.exit_time,
                "event": "Trade closed",
                "detail": str(record.exit_reason or ""),
            }
        )
    return sorted(events, key=lambda item: _timestamp(item["timestamp"]))


def _timestamp(value: datetime) -> float:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def _price_detail(value) -> str:
    number = finite_number(value)
    return f"at ${number:.2f}" if number is not None else ""
