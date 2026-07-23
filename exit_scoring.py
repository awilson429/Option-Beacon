def _number(value, default=0):
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _is_bullish(position):
    return position.get("direction") == "Bullish" or position.get("option_type") == "CALL"


def _score_label(score):
    if score >= 90:
        return "Immediate exit condition"
    if score >= 75:
        return "Strong exit warning"
    if score >= 60:
        return "Consider reducing"
    if score >= 45:
        return "Protect profits"
    if score >= 25:
        return "Mild weakness"
    return "Hold"


def calculate_exit_score(position, scanner_result=None, current_premium=None):
    scanner_result = scanner_result or {}
    reasons = []
    score = 0

    bullish = _is_bullish(position)
    price = _number(scanner_result.get("price"))
    vwap = _number(scanner_result.get("vwap"))
    ema20 = _number(scanner_result.get("ema20"))
    ema50 = _number(scanner_result.get("ema50"))
    rsi = _number(scanner_result.get("rsi"))
    macd_hist = _number(scanner_result.get("macd_hist"))
    relative_volume = _number(scanner_result.get("relative_volume"))
    stop = _number(position.get("current_stop"))
    target_1 = _number(position.get("target_1"))
    target_2 = _number(position.get("target_2"))
    entry_underlying = _number(position.get("entry_underlying_price"))
    entry_premium = _number(position.get("entry_premium"))
    current_premium = _number(current_premium)

    if not scanner_result or scanner_result.get("signal") == "DATA UNAVAILABLE":
        return {
            "exit_score": 35,
            "exit_label": "Mild weakness",
            "exit_reasons": ["Current scanner data is unavailable; manage from original stop and plan."],
        }

    if price and stop:
        if bullish and price <= stop:
            score += 45
            reasons.append("Underlying is at or below the planned stop.")
        elif not bullish and price >= stop:
            score += 45
            reasons.append("Underlying is at or above the planned stop.")

    if price and vwap:
        if bullish and price < vwap:
            score += 20
            reasons.append("Underlying has lost VWAP.")
        elif not bullish and price > vwap:
            score += 20
            reasons.append("Underlying has reclaimed VWAP against the trade.")

    if price and ema20:
        if bullish and price < ema20:
            score += 12
            reasons.append("Underlying is below the 20 EMA.")
        elif not bullish and price > ema20:
            score += 12
            reasons.append("Underlying is above the 20 EMA against the trade.")

    if ema20 and ema50:
        if bullish and ema20 < ema50:
            score += 12
            reasons.append("Short-term trend has weakened below the 50 EMA.")
        elif not bullish and ema20 > ema50:
            score += 12
            reasons.append("Short-term trend has strengthened against the put thesis.")

    if relative_volume and relative_volume < 0.85:
        score += 8
        reasons.append("Relative volume is fading.")

    if bullish and macd_hist < 0:
        score += 8
        reasons.append("MACD histogram has turned bearish.")
    elif not bullish and macd_hist > 0:
        score += 8
        reasons.append("MACD histogram has turned bullish against the trade.")

    if bullish and rsi and rsi < 45:
        score += 8
        reasons.append("RSI has weakened below bullish momentum range.")
    elif not bullish and rsi and rsi > 55:
        score += 8
        reasons.append("RSI has strengthened against bearish momentum.")

    if price and target_1:
        if bullish and price >= target_1:
            score += 18
            reasons.append("Target 1 has been reached; protect or take partial profit.")
        elif not bullish and price <= target_1:
            score += 18
            reasons.append("Target 1 has been reached; protect or take partial profit.")

    if price and target_2:
        if bullish and price >= target_2:
            score += 15
            reasons.append("Target 2 has been reached; consider trailing remaining position.")
        elif not bullish and price <= target_2:
            score += 15
            reasons.append("Target 2 has been reached; consider trailing remaining position.")

    if current_premium and entry_premium:
        premium_change = (current_premium - entry_premium) / entry_premium
        if premium_change <= -0.25:
            score += 20
            reasons.append("Option premium is down 25% or more from entry.")
        elif premium_change >= 0.30:
            score += 12
            reasons.append("Option premium is up 30% or more; protect gains.")

    if price and entry_underlying and not reasons:
        reasons.append("Trade remains inside the current plan with no major exit flags.")

    score = min(100, score)
    return {
        "exit_score": score,
        "exit_label": _score_label(score),
        "exit_reasons": reasons or ["No major exit flags from current scanner data."],
    }
