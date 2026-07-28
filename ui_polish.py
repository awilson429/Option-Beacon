"""Pure formatting helpers for OptionBeacon's compact decision summaries."""

from __future__ import annotations

import math

from live_trade_coach_dashboard import coach_display_model


UNAVAILABLE = "—"


def format_ui_value(
    value,
    *,
    price: bool = False,
    percentage: bool = False,
    decimals: int = 2,
) -> str:
    """Format finite UI values without exposing implementation sentinels."""
    if value is None:
        return UNAVAILABLE
    try:
        number = float(value)
    except (TypeError, ValueError):
        return UNAVAILABLE
    if not math.isfinite(number):
        return UNAVAILABLE
    if price:
        return f"${number:.2f}"
    suffix = "%" if percentage else ""
    return f"{number:.{decimals}f}{suffix}"


def status_emphasis(status: str) -> str:
    """Map decision text to a theme treatment without changing the decision."""
    normalized = str(status or "WAIT").upper()
    if normalized in {"BUY", "ENTERABLE", "HOLD"}:
        return "positive"
    if normalized in {"PROTECT PROFIT", "TAKE PARTIAL", "EXTENDED"}:
        return "caution"
    if normalized in {"EXIT", "INVALID"}:
        return "urgent"
    if normalized in {"WAIT", "UNAVAILABLE", "INSUFFICIENT DATA", "NO MATCH"}:
        return "muted"
    return "neutral"


def decision_state_label(result: dict, coach: dict | None = None) -> str:
    """Return a prominent existing decision state for display."""
    result = result or {}
    timing = str(
        result.get("timing_label")
        or result.get("entry_timing")
        or ""
    ).upper()
    stage = str(result.get("setup_stage") or "").upper()
    if timing in {"INVALID", "SETUP INVALIDATED"} or stage in {"INVALID", "FAILED"}:
        return "INVALID"
    if timing in {"EXTENDED", "DO NOT CHASE"} or stage == "EXTENDED":
        return "EXTENDED"
    if coach and coach.get("status") not in {None, "UNAVAILABLE"}:
        return str(coach["status"])
    if timing in {"TRIGGER CONFIRMED", "ENTERABLE"}:
        return "ENTERABLE"
    return "WAIT"


def _plan_value(plan: dict, *keys):
    for key in keys:
        value = plan.get(key)
        if value is not None:
            return value
    return None


def opportunity_summary(
    result: dict,
    evidence: dict | None = None,
    coach: dict | None = None,
) -> dict:
    """Build the visible decision fields for an actionable opportunity."""
    result = result or {}
    plan = result.get("trade_plan") or {}
    evidence = evidence or {}
    coach_display = coach_display_model(coach) if coach else {}
    state = decision_state_label(result, coach)
    return {
        "symbol": str(result.get("symbol") or plan.get("symbol") or UNAVAILABLE),
        "direction": str(
            plan.get("direction") or result.get("bias") or UNAVAILABLE
        ),
        "current_price": format_ui_value(result.get("price"), price=True),
        "setup": str(
            plan.get("setup_type")
            or plan.get("setup")
            or result.get("setup")
            or UNAVAILABLE
        ),
        "confidence": format_ui_value(
            result.get("confidence"),
            percentage=True,
            decimals=0,
        ),
        "timing": str(
            result.get("timing_label")
            or result.get("entry_timing")
            or UNAVAILABLE
        ),
        "entry": format_ui_value(
            _plan_value(plan, "trigger_price", "entry_price", "entry_zone_low"),
            price=True,
        ),
        "stop": format_ui_value(
            _plan_value(plan, "technical_stop", "invalidation_level"),
            price=True,
        ),
        "target_1": format_ui_value(plan.get("target_1"), price=True),
        "historical_grade": str(
            evidence.get("display_grade")
            or evidence.get("historical_grade")
            or "INSUFFICIENT DATA"
        ),
        "historical_sample_size": (
            str(evidence["sample_size"])
            if evidence.get("sample_size") is not None
            else UNAVAILABLE
        ),
        "historical_win_rate": format_ui_value(
            evidence.get("win_rate"),
            percentage=True,
        ),
        "coach_status": str(coach_display.get("status") or UNAVAILABLE),
        "coach_action": str(coach_display.get("action") or UNAVAILABLE),
        "decision_state": state,
        "treatment": status_emphasis(state),
    }


def scanner_summary(
    result: dict,
    evidence: dict | None = None,
    coach: dict | None = None,
) -> dict:
    """Return the required at-a-glance scanner fields."""
    summary = opportunity_summary(result, evidence, coach)
    return {
        key: summary[key]
        for key in (
            "symbol",
            "direction",
            "setup",
            "confidence",
            "timing",
            "historical_grade",
            "coach_status",
            "coach_action",
            "entry",
            "stop",
            "target_1",
            "decision_state",
            "treatment",
        )
    }


def open_trade_summary(record, coach: dict) -> dict:
    """Return the visible summary fields for one OPEN journal record."""
    display = coach_display_model(coach)
    return {
        "symbol": record.symbol or UNAVAILABLE,
        "direction": record.direction or UNAVAILABLE,
        "current_return": display["current_return"],
        "coach_status": display["status"],
        "coach_action": display["action"],
        "risk_remaining": display["risk_remaining"],
        "target_progress": display["progress_to_target_1"],
        "historical_grade": display["historical_grade"],
        "treatment": status_emphasis(display["status"]),
    }
