import math


ACTION_ENTER = "Entry zone active"
ACTION_WATCH = "Watch for trigger"
ACTION_HOLD = "Manage active idea"
ACTION_AVOID = "Avoid chasing"
ACTION_MONITOR = "Monitor setup"
ACTION_WAIT = "Wait"

TRADE_COACH_STATUSES = {
    "HOLD",
    "PROTECT PROFIT",
    "TAKE PARTIAL",
    "EXIT",
    "CLOSED",
    "UNAVAILABLE",
}
TRADE_COACH_URGENCIES = {"LOW", "MEDIUM", "HIGH"}
STOP_THREAT_RISK_PERCENT = 25.0
NEAR_TARGET_PROGRESS_PERCENT = 80.0
MEANINGFUL_LOSS_PERCENT = -0.5
MATERIAL_REVERSAL_FRACTION = 0.5

from market_intelligence import (
    chase_risk,
    confidence_explanation,
    missing_confirmations,
    setup_momentum_snapshot,
)


def _finite_positive(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _direction_sign(direction):
    if str(direction).lower() == "bullish":
        return 1
    if str(direction).lower() == "bearish":
        return -1
    return 0


def _directional_return(entry, price, direction_sign):
    return direction_sign * (price - entry) / entry * 100


def _target_progress(entry, price, target, direction_sign):
    target = _finite_positive(target)
    if target is None:
        return None
    target_distance = direction_sign * (target - entry)
    if target_distance <= 0:
        return None
    progress = direction_sign * (price - entry) / target_distance * 100
    return max(0.0, min(200.0, progress))


def _target_reached(price, target, direction_sign):
    target = _finite_positive(target)
    if target is None:
        return False
    return direction_sign * (price - target) >= 0


def _historical_grade(historical_intelligence):
    if not isinstance(historical_intelligence, dict):
        return "INSUFFICIENT DATA"
    grade = historical_intelligence.get("historical_grade")
    if grade is None:
        grade = historical_intelligence.get("grade")
    grade = str(grade or "INSUFFICIENT DATA").upper()
    return grade if grade in {
        "STRONG",
        "POSITIVE",
        "MIXED",
        "WEAK",
        "INSUFFICIENT DATA",
        "NO MATCH",
    } else "INSUFFICIENT DATA"


def _outcome_payload(
    *,
    status,
    action,
    urgency,
    historical_grade,
    summary,
    reasons,
    progress=None,
    current_return=None,
    risk_remaining=None,
    reached=None,
    stop_threatened=False,
):
    progress = progress or {}
    reached = reached or {}
    return {
        "status": status,
        "action": action,
        "urgency": urgency,
        "progress_to_target_1": progress.get("target_1"),
        "progress_to_target_2": progress.get("target_2"),
        "progress_to_target_3": progress.get("target_3"),
        "current_return": current_return,
        "risk_remaining": risk_remaining,
        "target_1_reached": reached.get("target_1", False),
        "target_2_reached": reached.get("target_2", False),
        "target_3_reached": reached.get("target_3", False),
        "stop_threatened": stop_threatened,
        "historical_grade": historical_grade,
        "summary": summary,
        "reasons": reasons[:5],
    }


def coach_trade_outcome(
    record,
    current_price,
    current_timestamp,
    historical_intelligence=None,
):
    """Return deterministic management context for an entered TradeOutcome.

    This is advisory only: it does not mutate the outcome, its planned levels,
    or any lifecycle state.
    """
    del current_timestamp  # Reserved for time-aware coaching without changing lifecycle.
    grade = _historical_grade(historical_intelligence)

    if record.exit_time is not None:
        return _outcome_payload(
            status="CLOSED",
            action="No action; this trade is already closed.",
            urgency="LOW",
            historical_grade=grade,
            summary="This trade is closed and is not eligible for live coaching.",
            reasons=[
                "The outcome already has an exit time.",
                "Closed records are never reconsidered by the Live Trade Coach.",
            ],
        )

    if record.entry_time is None:
        return _outcome_payload(
            status="UNAVAILABLE",
            action="Wait for the planned entry to trigger.",
            urgency="LOW",
            historical_grade=grade,
            summary="Live coaching is unavailable until the candidate enters.",
            reasons=[
                "The outcome does not have an entry time.",
                "Candidate signals are not treated as active trades.",
            ],
        )

    entry = _finite_positive(record.entry)
    price = _finite_positive(current_price)
    direction_sign = _direction_sign(record.direction)
    if entry is None or price is None or not direction_sign:
        return _outcome_payload(
            status="UNAVAILABLE",
            action="Wait for valid trade and market data.",
            urgency="LOW",
            historical_grade=grade,
            summary="Live coaching is unavailable because required price data is invalid.",
            reasons=[
                "A valid entry, current price, and direction are required.",
                "No management recommendation is made from incomplete data.",
            ],
        )

    targets = {
        "target_1": record.target_1,
        "target_2": record.target_2,
        "target_3": record.target_3,
    }
    progress = {
        name: _target_progress(entry, price, target, direction_sign)
        for name, target in targets.items()
    }
    reached = {
        name: _target_reached(price, target, direction_sign)
        for name, target in targets.items()
    }
    current_return = _directional_return(entry, price, direction_sign)

    stop = _finite_positive(record.stop)
    risk_remaining = None
    stop_breached = False
    stop_threatened = False
    if stop is not None:
        original_risk = direction_sign * (entry - stop)
        if original_risk > 0:
            risk_remaining = direction_sign * (price - stop) / original_risk * 100
            risk_remaining = max(0.0, min(200.0, risk_remaining))
            stop_breached = direction_sign * (price - stop) <= 0
            stop_threatened = (
                stop_breached or risk_remaining <= STOP_THREAT_RISK_PERCENT
            )

    base_reasons = [
        f"Current underlying return is {current_return:.2f}% from the planned entry."
    ]
    if stop is None:
        base_reasons.append("No valid stop is available, so remaining risk is unavailable.")
    elif stop_threatened:
        base_reasons.append(
            "Price has crossed the planned stop."
            if stop_breached
            else "Price is close to exhausting the original stop distance."
        )
    else:
        base_reasons.append("The planned stop is not currently threatened.")

    if stop_breached or (
        risk_remaining is not None and risk_remaining <= 0
    ):
        return _outcome_payload(
            status="EXIT",
            action="Exit at the planned risk limit.",
            urgency="HIGH",
            historical_grade=grade,
            summary="Price has reached or crossed the planned stop.",
            reasons=base_reasons,
            progress=progress,
            current_return=current_return,
            risk_remaining=risk_remaining,
            reached=reached,
            stop_threatened=True,
        )

    peak_return = _finite_positive(record.max_favorable_excursion)
    target_1_return = (
        _directional_return(entry, _finite_positive(record.target_1), direction_sign)
        if _finite_positive(record.target_1) is not None
        else None
    )
    reversed_after_target = (
        peak_return is not None
        and target_1_return is not None
        and peak_return >= target_1_return
        and current_return <= peak_return * MATERIAL_REVERSAL_FRACTION
    )
    if reversed_after_target:
        return _outcome_payload(
            status="EXIT",
            action="Exit after the material reversal from prior favorable progress.",
            urgency="HIGH",
            historical_grade=grade,
            summary="The trade has materially reversed after reaching target-level progress.",
            reasons=base_reasons
            + ["More than half of the recorded favorable excursion has been given back."],
            progress=progress,
            current_return=current_return,
            risk_remaining=risk_remaining,
            reached=reached,
            stop_threatened=stop_threatened,
        )

    if grade == "WEAK" and current_return <= MEANINGFUL_LOSS_PERCENT:
        return _outcome_payload(
            status="EXIT",
            action="Exit or reduce risk; weak historical evidence compounds the loss.",
            urgency="HIGH",
            historical_grade=grade,
            summary="The trade is losing meaningfully and similar trades have weak history.",
            reasons=base_reasons
            + ["Historical evidence is weak, so manage the position defensively."],
            progress=progress,
            current_return=current_return,
            risk_remaining=risk_remaining,
            reached=reached,
            stop_threatened=stop_threatened,
        )

    if reached["target_3"]:
        status = "EXIT"
        action = "Exit at the planned final target."
        urgency = "HIGH"
        summary = "Target 3 has been reached; the planned upside is complete."
        reasons = base_reasons + ["The final available target has been reached."]
    elif (
        (reached["target_2"] and _finite_positive(record.target_3) is not None)
        or (reached["target_1"] and _finite_positive(record.target_2) is not None)
    ) and grade != "WEAK":
        status = "TAKE PARTIAL"
        action = "Reduce part of the position and keep a remainder open."
        urgency = "MEDIUM"
        reached_name = "Target 2" if reached["target_2"] else "Target 1"
        summary = f"{reached_name} has been reached with planned upside remaining."
        reasons = base_reasons + [
            f"{reached_name} has been reached.",
            "Historical evidence is not weak, so a managed remainder can stay open.",
        ]
    elif (
        current_return > 0
        and (
            reached["target_1"]
            or (
                progress["target_1"] is not None
                and progress["target_1"] >= NEAR_TARGET_PROGRESS_PERCENT
            )
        )
    ):
        status = "PROTECT PROFIT"
        action = "Protect gains and consider moving the stop toward breakeven."
        urgency = "MEDIUM"
        summary = "Target 1 is near or reached; protect the open profit."
        reasons = base_reasons + [
            "The trade has achieved at least 80% of the move toward Target 1."
        ]
    else:
        status = "HOLD"
        action = "Hold while respecting the planned stop and targets."
        urgency = "LOW"
        summary = "The open trade remains within its planned risk and target structure."
        reasons = base_reasons + ["Target 1 has not been reached."]

    if grade == "STRONG":
        reasons.append("Strong historical evidence reinforces the current plan.")
    elif grade == "POSITIVE":
        reasons.append("Positive historical evidence supports measured patience.")
    elif grade == "MIXED":
        reasons.append("Historical evidence is mixed, so remain cautious.")
    elif grade == "WEAK":
        reasons.append("Historical evidence is weak, so manage the position defensively.")
    else:
        reasons.append("History is insufficient for a reliable conclusion.")

    return _outcome_payload(
        status=status,
        action=action,
        urgency=urgency,
        historical_grade=grade,
        summary=summary,
        reasons=reasons,
        progress=progress,
        current_return=current_return,
        risk_remaining=risk_remaining,
        reached=reached,
        stop_threatened=stop_threatened,
    )


def exit_score_for_live_setup(result, coach=None):
    if not result:
        return {
            "exit_score": 0,
            "exit_label": "No active idea",
            "exit_reasons": ["No live setup is available."],
        }

    coach = coach or {"action": ACTION_WAIT}
    signal = result.get("signal", "WATCHLIST")
    score = int(_number(result.get("confidence")))
    direction = result.get("bias", "Neutral")
    timing = result.get("entry_timing", "Wait")
    reasons = []
    exit_score = 0

    if signal in ["MARKET CLOSED / WAIT", "WAITING FOR CANDLE", "DATA UNAVAILABLE"]:
        return {
            "exit_score": 0,
            "exit_label": "No active idea",
            "exit_reasons": ["Scanner is not showing an active idea."],
        }

    if coach["action"] == ACTION_AVOID:
        exit_score += 65
        reasons.append("The setup is extended; chasing risk is elevated.")

    chase = chase_risk(result)
    if chase["label"] == "High" and coach["action"] != ACTION_AVOID:
        exit_score += 25
        reasons.append(chase["reason"])
    elif chase["label"] == "Moderate":
        exit_score += 10
        reasons.append(chase["reason"])

    if timing in ["Do not chase", "Setup invalidated"]:
        exit_score += 25
        reasons.append(f"Entry timing is {timing.lower()}.")

    bullish_score = _number(result.get("bullish_score"))
    bearish_score = _number(result.get("bearish_score"))
    if direction == "Bullish" and bearish_score >= bullish_score - 5:
        exit_score += 20
        reasons.append("Bearish score is close enough to challenge the bullish thesis.")
    elif direction == "Bearish" and bullish_score >= bearish_score - 5:
        exit_score += 20
        reasons.append("Bullish score is close enough to challenge the bearish thesis.")

    price = _number(result.get("price"))
    vwap = _number(result.get("vwap"))
    macd_hist = _number(result.get("macd_hist"))
    relative_volume = _number(result.get("relative_volume"))

    if direction == "Bullish" and price and vwap and price < vwap:
        exit_score += 18
        reasons.append("Price is below VWAP against the bullish idea.")
    elif direction == "Bearish" and price and vwap and price > vwap:
        exit_score += 18
        reasons.append("Price is above VWAP against the bearish idea.")

    if direction == "Bullish" and macd_hist < 0:
        exit_score += 12
        reasons.append("MACD histogram is bearish against the call idea.")
    elif direction == "Bearish" and macd_hist > 0:
        exit_score += 12
        reasons.append("MACD histogram is bullish against the put idea.")

    if relative_volume and relative_volume < 0.85:
        exit_score += 10
        reasons.append("Relative volume is fading.")

    if score >= 90 and exit_score < 20:
        reasons.append("No major reversal warning is active yet.")

    exit_score = min(100, exit_score)
    if exit_score >= 80:
        label = "Reversal risk high"
    elif exit_score >= 55:
        label = "Weakness building"
    elif exit_score >= 30:
        label = "Some caution"
    else:
        label = "Hold idea"

    return {
        "exit_score": exit_score,
        "exit_label": label,
        "exit_reasons": reasons or ["No major reversal warning is active yet."],
    }


def ten_minute_edge(result, coach):
    score = _number(result.get("confidence"))
    edge = 45 + ((score - 60) * 0.45)

    if coach["action"] == ACTION_ENTER:
        edge += 8
    elif coach["action"] == ACTION_WATCH:
        edge += 4
    elif coach["action"] == ACTION_MONITOR:
        edge -= 2
    elif coach["action"] == ACTION_AVOID:
        edge -= 16
    elif coach["action"] == ACTION_WAIT:
        edge -= 10

    chase_risk = coach.get("chase_risk")
    if chase_risk == "Low":
        edge += 5
    elif chase_risk == "Moderate":
        edge -= 2
    elif chase_risk == "High":
        edge -= 10

    exit_score = _number(coach.get("exit_score"))
    if exit_score >= 80:
        edge -= 18
    elif exit_score >= 55:
        edge -= 9
    elif exit_score <= 20:
        edge += 3

    relative_volume = _number(result.get("relative_volume"))
    if relative_volume >= 1.5:
        edge += 5
    elif relative_volume and relative_volume < 0.8:
        edge -= 5

    direction = result.get("bias", "Neutral")
    price = _number(result.get("price"))
    vwap = _number(result.get("vwap"))
    macd_hist = _number(result.get("macd_hist"))
    if direction == "Bullish":
        if price and vwap and price >= vwap:
            edge += 4
        if macd_hist > 0:
            edge += 3
    elif direction == "Bearish":
        if price and vwap and price <= vwap:
            edge += 4
        if macd_hist < 0:
            edge += 3

    edge = max(5, min(92, round(edge)))
    if edge >= 65:
        label = "High"
    elif edge >= 55:
        label = "Moderate"
    elif edge >= 45:
        label = "Developing"
    else:
        label = "Low"

    return {
        "probability": edge,
        "label": label,
    }


def _number(value, default=0):
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _format_price(value):
    value = _number(value)
    return f"${value:.2f}" if value else "N/A"


def _option_type(direction):
    if direction == "Bullish":
        return "CALL"
    if direction == "Bearish":
        return "PUT"
    return "N/A"


def _management_text(result):
    direction = result.get("bias", "Neutral")
    plan = result.get("trade_plan") or {}
    target_1 = plan.get("target_1") or result.get("target")
    target_2 = plan.get("target_2")
    stop = plan.get("technical_stop") or result.get("stop")
    breakeven = result.get("breakeven")

    if direction == "Bullish":
        return (
            f"Use this as a call idea. First target is {_format_price(target_1)}. "
            f"If price pushes toward {_format_price(target_2)}, protect gains and trail. "
            f"If price loses {_format_price(stop)}, the bullish thesis is weakened."
        )

    if direction == "Bearish":
        return (
            f"Use this as a put idea. First target is {_format_price(target_1)}. "
            f"If price flushes toward {_format_price(target_2)}, protect gains and trail. "
            f"If price reclaims {_format_price(stop)}, the bearish thesis is weakened."
        )

    return f"Wait for a clearer setup. Breakeven reference: {_format_price(breakeven)}."


def coach_live_setup(result):
    if not result:
        payload = {
            "action": ACTION_WAIT,
            "priority": 0,
            "summary": "No scanner data is available yet.",
            "next_step": "Wait for fresh 5-minute scanner data.",
            "risk_note": "No trade idea is active.",
            "contract": "N/A",
            "chase_risk": "Unknown",
            "chase_reason": "No scanner data is available yet.",
            "missing_confirmations": ["scanner data"],
            "confidence_note": "Missing: scanner data.",
        }
        payload.update(exit_score_for_live_setup(result, payload))
        return payload

    signal = result.get("signal", "WATCHLIST")
    direction = result.get("bias", "Neutral")
    score = int(_number(result.get("confidence")))
    timing = result.get("entry_timing", "Wait")
    stage = result.get("setup_stage", "Developing")
    plan = result.get("trade_plan") or {}
    price = _format_price(result.get("price"))
    trigger = _format_price(plan.get("trigger_price") or result.get("entry"))
    invalidation = _format_price(plan.get("invalidation_level") or result.get("stop"))
    max_entry = _format_price(plan.get("max_entry_price"))
    contract = _option_type(direction)
    chase = chase_risk(result)
    missing = missing_confirmations(result)
    confidence_note = confidence_explanation(result)

    if signal in ["MARKET CLOSED / WAIT", "WAITING FOR CANDLE"]:
        payload = {
            "action": ACTION_WAIT,
            "priority": score,
            "summary": f"{direction} setup is not actionable yet.",
            "next_step": "Wait for the next completed 5-minute candle.",
            "risk_note": "Do not force an entry while the scanner is waiting.",
            "contract": contract,
            "chase_risk": chase["label"],
            "chase_reason": chase["reason"],
            "missing_confirmations": missing,
            "confidence_note": confidence_note,
        }
        payload.update(exit_score_for_live_setup(result, payload))
        return payload

    if signal == "DATA UNAVAILABLE":
        payload = {
            "action": ACTION_WAIT,
            "priority": 0,
            "summary": "Market data is unavailable for this symbol.",
            "next_step": "Skip this ticker until fresh data returns.",
            "risk_note": "No trade idea should be evaluated without data.",
            "contract": contract,
            "chase_risk": chase["label"],
            "chase_reason": chase["reason"],
            "missing_confirmations": missing,
            "confidence_note": confidence_note,
        }
        payload.update(exit_score_for_live_setup(result, payload))
        return payload

    if timing == "Do not chase" or stage == "Extended":
        payload = {
            "action": ACTION_AVOID,
            "priority": score,
            "summary": f"{direction} setup is extended at {price}.",
            "next_step": f"Do not chase past {max_entry}. Wait for a reset or a new setup.",
            "risk_note": f"Invalidation remains {invalidation}.",
            "contract": contract,
            "chase_risk": chase["label"],
            "chase_reason": chase["reason"],
            "missing_confirmations": missing,
            "confidence_note": confidence_note,
        }
        payload.update(exit_score_for_live_setup(result, payload))
        return payload

    if timing == "Trigger confirmed" and signal in ["BULLISH SETUP", "BEARISH SETUP"]:
        payload = {
            "action": ACTION_ENTER,
            "priority": score,
            "summary": f"{direction} {contract} idea is active at {price}.",
            "next_step": f"Entry is valid near {trigger} if price remains inside the plan.",
            "risk_note": _management_text(result),
            "contract": contract,
            "chase_risk": chase["label"],
            "chase_reason": chase["reason"],
            "missing_confirmations": missing,
            "confidence_note": confidence_note,
        }
        payload.update(exit_score_for_live_setup(result, payload))
        return payload

    if timing == "Watch closely" or stage == "Armed":
        payload = {
            "action": ACTION_WATCH,
            "priority": score,
            "summary": f"{direction} {contract} idea is setting up.",
            "next_step": f"Watch for confirmation through {trigger} with volume.",
            "risk_note": f"Do not act if price violates {invalidation}.",
            "contract": contract,
            "chase_risk": chase["label"],
            "chase_reason": chase["reason"],
            "missing_confirmations": missing,
            "confidence_note": confidence_note,
        }
        payload.update(exit_score_for_live_setup(result, payload))
        return payload

    if score >= 85 and direction in ["Bullish", "Bearish"]:
        payload = {
            "action": ACTION_HOLD,
            "priority": score,
            "summary": f"{direction} idea has a strong score but timing is {timing.lower()}.",
            "next_step": result.get("what_next_reason") or "Wait for cleaner timing.",
            "risk_note": f"Use {invalidation} as the thesis failure area.",
            "contract": contract,
            "chase_risk": chase["label"],
            "chase_reason": chase["reason"],
            "missing_confirmations": missing,
            "confidence_note": confidence_note,
        }
        payload.update(exit_score_for_live_setup(result, payload))
        return payload

    if score >= 60 and direction in ["Bullish", "Bearish"]:
        payload = {
            "action": ACTION_MONITOR,
            "priority": score,
            "summary": f"{direction} setup is developing, but confirmation is incomplete.",
            "next_step": result.get("what_next_reason") or "Monitor for stronger trend, volume, and price-action alignment.",
            "risk_note": "No entry is active yet. Treat this as a watchlist read, not an entry callout.",
            "contract": contract,
            "chase_risk": chase["label"],
            "chase_reason": chase["reason"],
            "missing_confirmations": missing,
            "confidence_note": confidence_note,
        }
        payload.update(exit_score_for_live_setup(result, payload))
        return payload

    payload = {
        "action": ACTION_WAIT,
        "priority": score,
        "summary": f"{direction} setup is still developing.",
        "next_step": result.get("what_next_reason") or "Wait for stronger alignment.",
        "risk_note": "No live trade idea is active yet.",
        "contract": contract,
        "chase_risk": chase["label"],
        "chase_reason": chase["reason"],
        "missing_confirmations": missing,
        "confidence_note": confidence_note,
    }
    payload.update(exit_score_for_live_setup(result, payload))
    return payload


def coach_rows(latest_results, min_score=80, history=None):
    rows = []
    for symbol, result in latest_results.items():
        coach = coach_live_setup(result)
        edge = ten_minute_edge(result or {"confidence": 0}, coach)
        momentum = setup_momentum_snapshot(result or {"symbol": symbol}, history)
        if coach["priority"] < min_score and coach["action"] == ACTION_WAIT:
            continue

        rows.append(
            {
                "Symbol": symbol,
                "Time": (result or {}).get("timestamp", ""),
                "Action": coach["action"],
                "Bias": (result or {}).get("bias", "Neutral"),
                "Score": coach["priority"],
                "Contract": coach["contract"],
                "Price": (result or {}).get("price"),
                "Stage": (result or {}).get("setup_stage", "Developing"),
                "Timing": (result or {}).get("entry_timing", "Wait"),
                "Coach Summary": coach["summary"],
                "Next Step": coach["next_step"],
                "Exit Score": coach["exit_score"],
                "Exit Label": coach["exit_label"],
                "10m Edge": edge["probability"],
                "10m Edge Label": edge["label"],
                "Entry Risk": coach["chase_risk"],
                "Live Read": momentum["label"],
                "Live Detail": momentum["detail"],
                "Missing": ", ".join(coach["missing_confirmations"]) or "None",
                "Risk Note": coach["risk_note"],
            }
        )

    return sorted(rows, key=lambda row: row["Score"], reverse=True)
