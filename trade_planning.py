from entry_timing import classify_entry_timing
from setup_stages import classify_setup_stage


UNAVAILABLE = "Unavailable"


def _number(result, key, default=0):
    try:
        value = result.get(key, default)
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _round(value):
    return round(float(value), 2) if value is not None else None


def _direction_multiplier(direction):
    return 1 if direction == "Bullish" else -1


def timing_label(result):
    """Return the plain-language timing state for a planned setup."""
    stage = result.get("setup_stage")
    entry_timing = result.get("entry_timing")

    if stage == "Failed" or entry_timing == "Setup invalidated":
        return "INVALID"
    if stage == "Extended" or entry_timing == "Do not chase":
        return "EXTENDED"
    if stage == "Triggered" or entry_timing == "Trigger confirmed":
        return "ENTERABLE"
    return "EARLY"


def _invalidation_condition(direction, level):
    if level is None:
        return UNAVAILABLE
    if direction == "Bullish":
        return f"Price falls below ${level:.2f}."
    if direction == "Bearish":
        return f"Price rises above ${level:.2f}."
    return UNAVAILABLE


def _supporting_reasons(result, minimum=3, maximum=5):
    candidates = [
        *(result.get("reasons") or []),
        result.get("setup_stage_reason"),
        result.get("entry_timing_reason"),
        result.get("what_next_reason"),
    ]
    reasons = []
    for candidate in candidates:
        text = str(candidate or "").strip()
        if text and text not in reasons:
            reasons.append(text)
        if len(reasons) == maximum:
            break

    while len(reasons) < minimum:
        reasons.append("Supporting reason unavailable.")
    return reasons


def _money(value):
    try:
        return f"${float(value):.2f}" if value is not None else UNAVAILABLE
    except (TypeError, ValueError):
        return UNAVAILABLE


def trade_plan_view(result):
    """Normalize existing trade-plan values for safe display in Streamlit."""
    result = result or {}
    plan = result.get("trade_plan") or {}
    confidence = result.get("confidence")
    entry_low = plan.get("entry_zone_low")
    entry_high = plan.get("entry_zone_high")
    risk_reward = plan.get("risk_reward")

    entry_zone = (
        f"{_money(entry_low)} - {_money(entry_high)}"
        if entry_low is not None and entry_high is not None
        else UNAVAILABLE
    )
    return {
        "ticker": result.get("symbol") or UNAVAILABLE,
        "direction": plan.get("direction") or result.get("bias") or UNAVAILABLE,
        "setup_name": plan.get("setup_type") or UNAVAILABLE,
        "confidence": f"{confidence}/100" if confidence is not None else UNAVAILABLE,
        "entry_zone": entry_zone,
        "trigger_price": _money(plan.get("trigger_price")),
        "initial_stop": _money(plan.get("technical_stop")),
        "target_1": _money(plan.get("target_1")),
        "target_2": _money(plan.get("target_2")),
        "target_3": _money(plan.get("target_3")),
        "risk_reward": f"{risk_reward}:1" if risk_reward is not None else UNAVAILABLE,
        "expected_hold": plan.get("expected_hold") or UNAVAILABLE,
        "maximum_chase_price": _money(
            plan.get("do_not_chase_price") or plan.get("max_entry_price")
        ),
        "invalidation_condition": plan.get("invalidation_condition")
        or _invalidation_condition(
            plan.get("direction") or result.get("bias"),
            plan.get("invalidation_level"),
        ),
        "reasons": _supporting_reasons(result),
        "timing_label": timing_label(result),
    }


def build_trade_plan(result):
    direction = result.get("bias", "Neutral")
    price = _number(result, "price")

    if direction not in ["Bullish", "Bearish"] or not price:
        return {
            "trade_plan": {},
            "what_next": "Wait.",
            "what_next_reason": "No clear directional setup is available yet.",
        }

    atr = max(_number(result, "atr"), price * 0.0025)
    multiplier = _direction_multiplier(direction)
    trigger = _number(
        result,
        "resistance" if direction == "Bullish" else "support",
        price,
    )
    invalidation = _number(
        result,
        "support" if direction == "Bullish" else "resistance",
        result.get("stop") or price - multiplier * atr * 0.45,
    )

    entry_low = trigger if direction == "Bullish" else trigger - atr * 0.2
    entry_high = trigger + atr * 0.2 if direction == "Bullish" else trigger
    max_entry = trigger + multiplier * atr * 0.35
    target_1 = trigger + multiplier * atr * 0.75
    target_2 = trigger + multiplier * atr * 1.25
    target_3 = trigger + multiplier * atr * 1.75
    risk = abs(trigger - invalidation)
    reward = abs(target_2 - trigger)
    risk_reward = round(reward / risk, 2) if risk else None

    trade_plan = {
        "direction": direction,
        "setup_type": "Bullish breakout" if direction == "Bullish" else "Bearish breakdown",
        "entry_zone_low": _round(min(entry_low, entry_high)),
        "entry_zone_high": _round(max(entry_low, entry_high)),
        "trigger_price": _round(trigger),
        "invalidation_level": _round(invalidation),
        "technical_stop": _round(invalidation),
        "invalidation_condition": _invalidation_condition(
            direction, _round(invalidation)
        ),
        "target_1": _round(target_1),
        "target_2": _round(target_2),
        "target_3": _round(target_3),
        "max_entry_price": _round(max_entry),
        "do_not_chase_price": _round(max_entry),
        "risk_reward": risk_reward,
        "expected_hold": "Intraday",
        "risk_rating": "Elevated" if risk_reward is not None and risk_reward < 1.5 else "Normal",
        "contract_guidance": "Intraday: 0-7 DTE, 0.50-0.70 delta, tight spread, strong volume/open interest.",
    }

    return {"trade_plan": trade_plan}


def next_action(result):
    timing = result.get("entry_timing", "Wait")
    plan = result.get("trade_plan", {})
    direction = result.get("bias", "Neutral")

    if timing == "Trigger confirmed":
        return (
            "Enter only within zone.",
            f"{direction} trigger is confirmed. Do not chase beyond ${plan.get('do_not_chase_price')}.",
        )
    if timing == "Watch closely":
        trigger = plan.get("trigger_price")
        label = "above" if direction == "Bullish" else "below"
        return (
            "Watch for breakout." if direction == "Bullish" else "Watch for breakdown.",
            f"Wait for price to break and hold {label} ${trigger} with volume confirmation.",
        )
    if timing == "Do not chase":
        return (
            "Do not chase.",
            "The setup is valid, but the entry is late relative to the trigger and ATR.",
        )
    if timing == "Setup invalidated":
        return (
            "Remove from watchlist.",
            "The setup breached its invalidation level.",
        )

    return (
        "Wait.",
        result.get("entry_timing_reason", "The setup has not reached a timely entry area yet."),
    )


def enrich_with_trade_plan(result):
    if not result:
        return result

    enriched = dict(result)
    stage = classify_setup_stage(enriched)
    enriched.update(stage)

    if enriched.get("bias") in ["Bullish", "Bearish"]:
        plan_payload = build_trade_plan(enriched)
        enriched.update(plan_payload)
        plan = enriched.get("trade_plan", {})
        enriched["trigger_price"] = plan.get("trigger_price")
        enriched["invalidation_level"] = plan.get("invalidation_level")
    else:
        enriched.update(build_trade_plan(enriched))

    timing = classify_entry_timing(enriched)
    enriched.update(timing)
    action, reason = next_action(enriched)
    enriched["what_next"] = action
    enriched["what_next_reason"] = reason
    return enriched
