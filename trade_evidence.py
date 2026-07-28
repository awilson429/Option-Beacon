"""Pure helpers for presenting historical setup evidence."""

from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace
from typing import Iterable

from setup_intelligence import DEFAULT_MINIMUM_SAMPLE_SIZE, setup_intelligence
from signal_history import (
    DEFAULT_MIN_ENTRY_CONFIDENCE,
    TradeOutcome,
    entry_confidence_eligible,
)
from trade_planning import timing_label


UNAVAILABLE = "—"
NON_LIVE_SIGNALS = {
    "DATA UNAVAILABLE",
    "MARKET CLOSED / WAIT",
    "WAITING FOR CANDLE",
}


def scanner_entry_eligibility(
    result: dict,
    minimum_entry_confidence: float = DEFAULT_MIN_ENTRY_CONFIDENCE,
) -> dict:
    """Return canonical display eligibility and concise rejection reasons."""
    result = result or {}
    plan = result.get("trade_plan") or {}
    direction = plan.get("direction") or result.get("bias")
    reasons = []
    if direction not in {"Bullish", "Bearish"}:
        reasons.append("Direction is not actionable.")
    if not plan:
        reasons.append("Entry plan is incomplete.")
    if result.get("signal") in NON_LIVE_SIGNALS:
        reasons.append("Candidate is not live.")

    confidence = result.get("confidence")
    confidence_record = SimpleNamespace(confidence=confidence)
    if not entry_confidence_eligible(
        confidence_record,
        minimum_entry_confidence,
    ):
        try:
            confidence_label = f"{float(confidence):g}%"
        except (TypeError, ValueError):
            confidence_label = "Unavailable"
        reasons.append(
            f"Confidence {confidence_label} is below the "
            f"{float(minimum_entry_confidence):g}% entry requirement."
        )

    timing = str(result.get("timing_label") or timing_label(result)).upper()
    if timing in {"INVALID", "EXTENDED"}:
        reasons.append(f"Timing is {timing.lower()}.")
    entry_timing = str(result.get("entry_timing") or "").upper()
    if entry_timing in {"WAIT", "TOO EARLY"} or timing in {"TOO EARLY", "WAIT"}:
        reasons.append("Timing is too early.")
    if entry_timing in {"SETUP INVALIDATED", "DO NOT CHASE"}:
        reasons.append(
            "Timing is invalid."
            if entry_timing == "SETUP INVALIDATED"
            else "Timing is extended."
        )
    if result.get("watch_only") is True or str(
        result.get("entry_eligibility") or ""
    ).upper() in {"WATCH ONLY", "NOT ELIGIBLE"}:
        reasons.append("Candidate is watch-only.")
    if result.get("entry_time") is not None and result.get("exit_time") is not None:
        reasons.append("Trade is closed.")

    def valid_plan_value(*keys) -> bool:
        value = next((plan.get(key) for key in keys if plan.get(key) is not None), None)
        try:
            return math.isfinite(float(value)) and float(value) > 0
        except (TypeError, ValueError):
            return False

    if not valid_plan_value("trigger_price", "entry_price", "entry_zone_low"):
        reasons.append("Entry plan is incomplete.")
    if not valid_plan_value("technical_stop", "invalidation_level", "stop"):
        reasons.append("Entry plan is incomplete.")
    if not valid_plan_value("target_1"):
        reasons.append("Entry plan is incomplete.")

    unique_reasons = list(dict.fromkeys(reasons))
    return {
        "eligible": not unique_reasons,
        "reasons": unique_reasons[:2],
        "minimum_entry_confidence": minimum_entry_confidence,
    }


def actionable_trade_plan(result: dict) -> bool:
    """Return whether a scanner result clears the canonical display entry gate."""
    return scanner_entry_eligibility(result)["eligible"]


def format_evidence_metric(
    value,
    *,
    percentage: bool = False,
    decimals: int = 2,
) -> str:
    """Format a finite evidence value or an em dash."""
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


def evidence_grade(evidence: dict) -> str:
    """Return the friendly display grade for an evidence result."""
    if evidence.get("display_grade"):
        return evidence["display_grade"]
    if evidence.get("match_level") == "NO_MATCH":
        return "NO MATCH"
    return evidence.get("historical_grade") or "INSUFFICIENT DATA"


def _point_label(value: float) -> str:
    rounded = round(abs(value), 1)
    return f"{rounded:g}"


def evidence_summary(evidence: dict) -> str:
    """Build deterministic plain-English context from historical metrics."""
    grade = evidence_grade(evidence)
    sample_size = int(evidence.get("sample_size") or 0)
    if grade == "NO MATCH":
        return "No matching historical setup data is available yet."
    if grade == "INSUFFICIENT DATA":
        return (
            "Not enough completed historical trades are available for this setup yet. "
            "The sample size is still too small for a reliable conclusion."
        )

    summaries = {
        "STRONG": f"Historical results are strong across {sample_size} similar trades.",
        "POSITIVE": (
            f"Historical results are positive across {sample_size} similar trades."
        ),
        "MIXED": "Results are mixed and should be treated cautiously.",
        "WEAK": f"Historical results are weak across {sample_size} similar trades.",
    }
    summary = summaries.get(grade, "Historical evidence is unavailable.")
    gap = evidence.get("confidence_gap")
    try:
        gap = float(gap)
    except (TypeError, ValueError):
        gap = None
    if gap is not None and math.isfinite(gap) and gap != 0:
        points = _point_label(gap)
        if gap < 0:
            summary += (
                f" The current confidence is {points} percentage points above "
                "the historical win rate."
            )
        else:
            summary += (
                f" The historical win rate is {points} percentage points above "
                "the current confidence."
            )
    return summary


def historical_evidence(
    result: dict,
    history: Iterable[TradeOutcome] | str | Path,
    *,
    minimum_sample_size: int = DEFAULT_MINIMUM_SAMPLE_SIZE,
) -> dict:
    """Return historical evidence plus its friendly display state."""
    records = history
    if not isinstance(history, (str, Path)):
        records = list(history)
        if not records:
            evidence = setup_intelligence(
                result,
                records,
                minimum_sample_size=minimum_sample_size,
            )
            evidence["historical_grade"] = "INSUFFICIENT DATA"
            evidence["display_grade"] = "INSUFFICIENT DATA"
            evidence["summary"] = evidence_summary(evidence)
            return evidence

    evidence = setup_intelligence(
        result,
        records,
        minimum_sample_size=minimum_sample_size,
    )
    evidence["display_grade"] = evidence_grade(evidence)
    evidence["summary"] = evidence_summary(evidence)
    return evidence
