"""Pure view helpers and a reusable Streamlit Live Trade Coach renderer."""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import datetime
from typing import Iterable

from live_trade_coach import coach_trade_outcome
from intraday_session import eod_coach_warning_due, intraday_trade_exit_due
from signal_history import TradeOutcome, scanner_result_to_trade_outcome
from trade_evidence import actionable_trade_plan


UNAVAILABLE = "—"


def format_coach_value(
    value,
    *,
    percentage: bool = False,
    decimals: int = 2,
) -> str:
    """Format finite coach values without exposing numeric sentinels."""
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


def open_trade_coach_eligible(record: TradeOutcome) -> bool:
    """Return whether a history record may receive live coaching."""
    return (
        record.entry_time is not None
        and record.exit_time is None
        and record.exit_reason != "NEVER_TRIGGERED"
    )


def actionable_live_plan_coach_eligible(result: dict) -> bool:
    """Use the existing trade-plan eligibility rules for live coaching."""
    return actionable_trade_plan(result)


def latest_symbol_price(latest_results: dict, symbol: str):
    """Return a finite positive scanner price for a symbol, when available."""
    result = (latest_results or {}).get(symbol) or {}
    value = result.get("price")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _result_fields(result: dict) -> tuple[str, str, str]:
    result = result or {}
    plan = result.get("trade_plan") or {}
    return (
        str(result.get("symbol") or plan.get("symbol") or ""),
        str(plan.get("direction") or result.get("bias") or ""),
        str(plan.get("setup_type") or plan.get("setup") or result.get("setup") or ""),
    )


def matching_open_trade(
    result: dict,
    records: Iterable[TradeOutcome],
) -> TradeOutcome | None:
    """Find the newest open outcome matching stable live-plan fields."""
    symbol, direction, setup = _result_fields(result)
    matches = [
        record
        for record in records
        if open_trade_coach_eligible(record)
        and record.symbol == symbol
        and record.direction == direction
        and record.setup == setup
    ]
    return max(matches, key=lambda record: record.timestamp) if matches else None


def live_plan_trade_outcome(
    result: dict,
    records: Iterable[TradeOutcome],
    *,
    current_price,
    current_timestamp: datetime,
) -> TradeOutcome | None:
    """Locate an open outcome or build a non-persisted entered view record."""
    if not actionable_live_plan_coach_eligible(result):
        return None

    matched = matching_open_trade(result, records)
    if matched is not None:
        return matched

    candidate = scanner_result_to_trade_outcome(result)
    if candidate is None or candidate.entry is None:
        return None
    try:
        price = float(current_price)
        entry = float(candidate.entry)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(price) or price <= 0:
        return None

    entered = (
        price >= entry
        if candidate.direction == "Bullish"
        else price <= entry
        if candidate.direction == "Bearish"
        else False
    )
    if not entered:
        return None
    return replace(candidate, entry_time=current_timestamp)


def open_trade_coach_output(
    record: TradeOutcome,
    current_price,
    current_timestamp: datetime,
    historical_intelligence=None,
) -> dict | None:
    """Evaluate only eligible open records through the canonical coach."""
    if not open_trade_coach_eligible(record):
        return None
    coach = coach_trade_outcome(
        record,
        current_price,
        current_timestamp,
        historical_intelligence=historical_intelligence,
    )
    if eod_coach_warning_due(current_timestamp) or intraday_trade_exit_due(
        record.entry_time, current_timestamp
    ):
        return {
            **coach,
            "status": "EXIT BEFORE CLOSE",
            "action": "Exit the intraday position before the regular session closes.",
            "urgency": "HIGH",
            "summary": "The authoritative end-of-day cutoff is approaching or has arrived.",
            "reasons": [
                *(coach.get("reasons") or []),
                "Intraday positions are not carried beyond the regular session.",
            ],
        }
    return coach


def coach_display_model(coach: dict) -> dict:
    """Return presentation-ready values without changing recommendations."""
    status = str(coach.get("status") or "UNAVAILABLE")
    treatments = {
        "HOLD": "positive",
        "PROTECT PROFIT": "caution",
        "TAKE PARTIAL": "caution",
        "EXIT": "urgent",
        "EXIT BEFORE CLOSE": "urgent",
        "CLOSED": "neutral",
        "UNAVAILABLE": "muted",
    }
    return {
        "status": status,
        "treatment": treatments.get(status, "muted"),
        "action": coach.get("action") or UNAVAILABLE,
        "urgency": coach.get("urgency") or UNAVAILABLE,
        "current_return": format_coach_value(
            coach.get("current_return"),
            percentage=True,
        ),
        "risk_remaining": format_coach_value(
            coach.get("risk_remaining"),
            percentage=True,
        ),
        "progress_to_target_1": format_coach_value(
            coach.get("progress_to_target_1"),
            percentage=True,
        ),
        "progress_to_target_2": format_coach_value(
            coach.get("progress_to_target_2"),
            percentage=True,
        ),
        "progress_to_target_3": format_coach_value(
            coach.get("progress_to_target_3"),
            percentage=True,
        ),
        "target_1_reached": "Yes" if coach.get("target_1_reached") else "No",
        "target_2_reached": "Yes" if coach.get("target_2_reached") else "No",
        "target_3_reached": "Yes" if coach.get("target_3_reached") else "No",
        "stop_threatened": "Yes" if coach.get("stop_threatened") else "No",
        "historical_grade": coach.get("historical_grade") or UNAVAILABLE,
        "summary": coach.get("summary") or UNAVAILABLE,
        "reasons": list(coach.get("reasons") or []),
    }


def render_live_trade_coach_output(
    coach: dict,
    *,
    show_overview: bool = True,
) -> None:
    """Render an advisory-only Live Trade Coach result."""
    import streamlit as st

    display = coach_display_model(coach)
    if show_overview:
        st.markdown("#### Live Trade Coach")
        headline = (
            f"**{display['status']} · {display['urgency']} urgency**  \n"
            f"{display['summary']}"
        )
        treatments = {
            "positive": st.success,
            "caution": st.warning,
            "urgent": st.error,
            "neutral": st.info,
            "muted": st.caption,
        }
        treatments[display["treatment"]](headline)

        first = st.columns(4)
        first[0].metric("Current Return", display["current_return"])
        first[1].metric("Risk Remaining", display["risk_remaining"])
        first[2].metric("Target 1 Progress", display["progress_to_target_1"])
        first[3].metric("Historical Grade", display["historical_grade"])
        st.markdown(f"**Suggested action:** {display['action']}  \n*Advisory only.*")

    with st.expander("Coach Details"):
        second = st.columns(4)
        second[0].metric("Status", display["status"])
        second[1].metric("Urgency", display["urgency"])
        second[2].metric("Progress to Target 2", display["progress_to_target_2"])
        second[3].metric("Progress to Target 3", display["progress_to_target_3"])

        third = st.columns(4)
        third[0].metric("Target 1 Reached", display["target_1_reached"])
        third[1].metric("Target 2 Reached", display["target_2_reached"])
        third[2].metric("Target 3 Reached", display["target_3_reached"])
        third[3].metric("Stop Threatened", display["stop_threatened"])

        st.markdown("**Reasons**")
        for reason in display["reasons"]:
            st.write(f"- {reason}")
