"""Supplementary rule-based exit coaching; never mutates lifecycle state."""

from __future__ import annotations


def assess_exit_conditions(context: dict) -> dict:
    reasons = []
    if context.get("authoritative_closed"):
        return _result("CLOSED", ("AUTHORITATIVE_TRADE_CLOSED",))
    if context.get("end_of_day_due"):
        return _result("EXIT BEFORE CLOSE", ("END_OF_DAY_APPROACHING",))
    if context.get("stop_threatened") or context.get("vwap_lost") and context.get("momentum_weakening"):
        reasons.extend([code for condition, code in ((context.get("stop_threatened"), "STOP_PROXIMITY"), (context.get("vwap_lost"), "VWAP_LOST"), (context.get("momentum_weakening"), "MOMENTUM_WEAKENING")) if condition])
        return _result("EXIT SIGNAL", tuple(reasons))
    if context.get("mfe_giveback_percent", 0) >= 50:
        return _result("PROTECT GAINS", ("MFE_GIVEBACK_AT_LEAST_50_PERCENT",))
    if context.get("target_1_reached"):
        return _result("CONSIDER PARTIAL EXIT", ("TARGET_1_REACHED",))
    if context.get("momentum_weakening") or context.get("sector_reversal"):
        return _result("TIGHTEN STOP", ("MOMENTUM_OR_SECTOR_WEAKENING",))
    if context.get("momentum_strengthening") and context.get("volume_expanding"):
        return _result("HOLD - MOMENTUM STRONG", ("MOMENTUM_STRENGTHENING", "VOLUME_EXPANDING"))
    return _result("HOLD", ("NO_EXIT_PRESSURE_DETECTED",))


def _result(state, reasons):
    return {"state": state, "reason_codes": list(reasons), "advisory_only": True, "authoritative_lifecycle_unchanged": True}
