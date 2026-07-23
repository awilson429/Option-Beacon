from exit_scoring import calculate_exit_score


def _number(value, default=0):
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def premium_metrics(position, current_premium=None):
    entry = _number(position.get("entry_premium"))
    current = _number(current_premium, _number(position.get("current_premium")))
    peak = max(_number(position.get("peak_premium")), current, entry)

    if not entry:
        return {
            "current_profit_percent": None,
            "peak_profit_percent": None,
            "profit_giveback_percent": None,
        }

    current_profit = round(((current - entry) / entry) * 100, 2)
    peak_profit = round(((peak - entry) / entry) * 100, 2)
    giveback = 0

    if peak > entry and current < peak:
        giveback = round(((peak - current) / (peak - entry)) * 100, 2)

    return {
        "current_profit_percent": current_profit,
        "peak_profit_percent": peak_profit,
        "profit_giveback_percent": giveback,
    }


def phase_two_guidance(position, current_premium=None):
    metrics = premium_metrics(position, current_premium)
    current_profit = metrics["current_profit_percent"]
    peak_profit = metrics["peak_profit_percent"]
    giveback = metrics["profit_giveback_percent"]

    if current_profit is None:
        return None, metrics

    if peak_profit is not None and peak_profit >= 50 and giveback is not None and giveback >= 20:
        return {
            "coach_action": "Trail remaining position",
            "coach_next_step": "Peak profit exceeded 50% and at least 20% of peak profit has been given back.",
            "reason": f"Peak profit was {peak_profit}%; current giveback is {giveback}%.",
        }, metrics

    if current_profit >= 50:
        return {
            "coach_action": "Take partial profit",
            "coach_next_step": "Consider taking another partial profit and trailing the rest.",
            "reason": f"Current premium profit is {current_profit}%.",
        }, metrics

    if current_profit >= 30:
        return {
            "coach_action": "Take partial profit",
            "coach_next_step": "Consider selling 25% of the position and protecting the remainder.",
            "reason": f"Current premium profit is {current_profit}%.",
        }, metrics

    if current_profit >= 20:
        return {
            "coach_action": "Move stop to breakeven",
            "coach_next_step": "Premium is up at least 20%; consider moving the remaining risk to breakeven.",
            "reason": f"Current premium profit is {current_profit}%.",
        }, metrics

    return None, metrics


def coach_recommendation(position, scanner_result=None, current_premium=None):
    current_premium = current_premium if current_premium is not None else position.get("current_premium")
    exit_payload = calculate_exit_score(position, scanner_result, current_premium)
    phase_two, metrics = phase_two_guidance(position, current_premium)
    score = exit_payload["exit_score"]

    if phase_two and score < 75:
        action = phase_two["coach_action"]
        next_step = phase_two["coach_next_step"]
        exit_payload["exit_reasons"] = [phase_two["reason"]] + exit_payload["exit_reasons"]
    elif score >= 90:
        action = "Exit"
        next_step = "The original thesis appears invalidated. Close or strongly consider closing the paper trade."
    elif score >= 75:
        action = "Strong exit warning"
        next_step = "Review immediately. If this were live, this would call for decisive risk reduction."
    elif score >= 60:
        action = "Reduce position"
        next_step = "Consider taking partial profit or cutting exposure."
    elif score >= 45:
        action = "Protect profits"
        next_step = "Move stop closer to breakeven or protect open gains."
    elif score >= 25:
        action = "Hold, but watch"
        next_step = "Momentum is not fully clean. Keep the planned stop in place."
    else:
        action = "Hold"
        next_step = "No major exit flag. Continue following the original plan."

    return {
        **exit_payload,
        **metrics,
        "coach_action": action,
        "coach_next_step": next_step,
    }
