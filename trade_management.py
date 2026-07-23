from exit_scoring import calculate_exit_score


def coach_recommendation(position, scanner_result=None, current_premium=None):
    exit_payload = calculate_exit_score(position, scanner_result, current_premium)
    score = exit_payload["exit_score"]

    if score >= 90:
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
        "coach_action": action,
        "coach_next_step": next_step,
    }
