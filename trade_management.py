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


def _protective_stop(position, candidates):
    bullish = position.get("direction") == "Bullish" or position.get("option_type") == "CALL"
    current_stop = _number(position.get("current_stop"))
    valid_candidates = [_number(candidate) for candidate in candidates if _number(candidate)]

    if current_stop:
        valid_candidates.append(current_stop)

    if not valid_candidates:
        return None

    stop = max(valid_candidates) if bullish else min(valid_candidates)
    return round(stop, 2)


def stop_guidance(position, metrics):
    current_profit = metrics.get("current_profit_percent")
    if current_profit is None or current_profit < 20:
        return {
            "suggested_stop": None,
            "suggested_stop_reason": None,
        }

    entry_underlying = _number(position.get("entry_underlying_price"))
    target_1 = _number(position.get("target_1"))
    target_2 = _number(position.get("target_2"))
    partial_1_taken = bool(position.get("partial_1_taken"))
    partial_2_taken = bool(position.get("partial_2_taken"))

    if partial_1_taken and partial_2_taken and target_2:
        return {
            "suggested_stop": _protective_stop(position, [entry_underlying, target_1, target_2]),
            "suggested_stop_reason": "Both partials are marked taken; consider trailing near Target 2.",
        }

    if partial_1_taken and target_1:
        return {
            "suggested_stop": _protective_stop(position, [entry_underlying, target_1]),
            "suggested_stop_reason": "First partial is marked taken; consider protecting near Target 1.",
        }

    if entry_underlying:
        return {
            "suggested_stop": _protective_stop(position, [entry_underlying]),
            "suggested_stop_reason": "Premium is up at least 20%; consider protecting around breakeven.",
        }

    return {
        "suggested_stop": None,
        "suggested_stop_reason": None,
    }


def phase_two_guidance(position, current_premium=None):
    metrics = premium_metrics(position, current_premium)
    current_profit = metrics["current_profit_percent"]
    peak_profit = metrics["peak_profit_percent"]
    giveback = metrics["profit_giveback_percent"]
    partial_1_taken = bool(position.get("partial_1_taken"))
    partial_2_taken = bool(position.get("partial_2_taken"))

    if current_profit is None:
        return None, metrics

    if peak_profit is not None and peak_profit >= 50 and giveback is not None and giveback >= 20:
        return {
            "coach_action": "Trail remaining position",
            "coach_next_step": "Peak profit exceeded 50% and at least 20% of peak profit has been given back.",
            "reason": f"Peak profit was {peak_profit}%; current giveback is {giveback}%.",
        }, metrics

    if current_profit >= 50:
        if partial_1_taken and partial_2_taken:
            return {
                "coach_action": "Trail remaining position",
                "coach_next_step": "Both partial-profit targets are marked taken; focus on trailing the rest.",
                "reason": f"Current premium profit is {current_profit}%.",
            }, metrics

        if partial_1_taken:
            return {
                "coach_action": "Take second partial profit",
                "coach_next_step": "Consider selling another portion and trailing the rest.",
                "reason": f"Current premium profit is {current_profit}%.",
            }, metrics

        return {
            "coach_action": "Take first partial profit",
            "coach_next_step": "Consider selling 25% of the position, then trail the remainder if strength continues.",
            "reason": f"Current premium profit is {current_profit}%.",
        }, metrics

    if current_profit >= 30:
        if partial_1_taken:
            return {
                "coach_action": "Hold protected runner",
                "coach_next_step": "First partial is marked taken; consider holding the rest toward the next profit zone.",
                "reason": f"Current premium profit is {current_profit}%.",
            }, metrics

        return {
            "coach_action": "Take first partial profit",
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
    stop_payload = stop_guidance(position, metrics)
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
        **stop_payload,
        "coach_action": action,
        "coach_next_step": next_step,
    }
