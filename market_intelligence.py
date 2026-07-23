def _number(value, default=0):
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _direction_score(result, direction):
    if direction == "Bullish":
        return _number(result.get("bullish_score"))
    if direction == "Bearish":
        return _number(result.get("bearish_score"))
    return _number(result.get("confidence"))


def market_regime(latest_results):
    market_symbols = [
        result for symbol, result in latest_results.items()
        if symbol in ["SPY", "QQQ", "IWM", "DIA"] and result
    ]

    if not market_symbols:
        return {
            "regime": "Unknown",
            "support": "Waiting for market data",
            "best_strategy": "Wait for SPY/QQQ context.",
            "bullish_count": 0,
            "bearish_count": 0,
            "average_score": 0,
        }

    bullish_count = sum(1 for result in market_symbols if result.get("bias") == "Bullish")
    bearish_count = sum(1 for result in market_symbols if result.get("bias") == "Bearish")
    average_score = sum(_number(result.get("confidence")) for result in market_symbols) / len(market_symbols)
    high_conviction = average_score >= 80

    if bullish_count >= 3 and high_conviction:
        regime = "Bullish trend"
        support = "Market support favors bullish continuation."
        best_strategy = "Favor bullish pullbacks and clean breakouts."
    elif bearish_count >= 3 and high_conviction:
        regime = "Bearish trend"
        support = "Market support favors bearish continuation."
        best_strategy = "Favor bearish breakdowns and failed bounces."
    elif bullish_count > bearish_count:
        regime = "Bullish but mixed"
        support = "Market leans bullish, but confirmation is not broad."
        best_strategy = "Be selective and avoid late entries."
    elif bearish_count > bullish_count:
        regime = "Bearish but mixed"
        support = "Market leans bearish, but confirmation is not broad."
        best_strategy = "Be selective and avoid late entries."
    else:
        regime = "Choppy"
        support = "Market direction is mixed."
        best_strategy = "Wait for cleaner confirmation or take smaller targets."

    return {
        "regime": regime,
        "support": support,
        "best_strategy": best_strategy,
        "bullish_count": bullish_count,
        "bearish_count": bearish_count,
        "average_score": round(average_score, 1),
    }


def setup_market_support(result, latest_results):
    direction = result.get("bias", "Neutral")
    regime = market_regime(latest_results)

    if direction == "Bullish" and regime["bullish_count"] >= 2:
        return "Aligned"
    if direction == "Bearish" and regime["bearish_count"] >= 2:
        return "Aligned"
    if regime["regime"] in ["Choppy", "Unknown"]:
        return "Mixed"
    return "Against"


def chase_risk(result):
    direction = result.get("bias", "Neutral")
    price = _number(result.get("price"))
    atr = _number(result.get("atr"))
    plan = result.get("trade_plan") or {}
    trigger = _number(plan.get("trigger_price") or result.get("entry") or result.get("price"))

    if not price or not trigger or not atr:
        return {
            "label": "Unknown",
            "distance_atr": None,
            "reason": "Not enough data to measure chase risk.",
        }

    if direction == "Bullish":
        distance = price - trigger
    elif direction == "Bearish":
        distance = trigger - price
    else:
        distance = abs(price - trigger)

    distance_atr = round(distance / atr, 2) if atr else 0

    if distance_atr >= 0.75:
        label = "High"
        reason = f"Price is {distance_atr} ATR beyond the preferred trigger."
    elif distance_atr >= 0.35:
        label = "Moderate"
        reason = f"Price is {distance_atr} ATR beyond the trigger. Entry discipline matters."
    elif distance_atr >= -0.25:
        label = "Low"
        reason = "Price is near the preferred trigger area."
    else:
        label = "Waiting"
        reason = "Price has not reached the preferred trigger area yet."

    return {
        "label": label,
        "distance_atr": distance_atr,
        "reason": reason,
    }


def missing_confirmations(result, latest_results=None):
    latest_results = latest_results or {}
    missing = []
    direction = result.get("bias", "Neutral")

    if _number(result.get("trend_score")) < 18:
        missing.append("trend alignment")
    if _number(result.get("momentum_score")) < 14:
        missing.append("momentum confirmation")
    if _number(result.get("volume_score")) < 14:
        missing.append("strong relative volume")
    if _number(result.get("price_action_score")) < 12:
        missing.append("clean breakout/breakdown")

    support = setup_market_support(result, latest_results)
    if support != "Aligned" and direction in ["Bullish", "Bearish"]:
        missing.append("market support")

    chase = chase_risk(result)
    if chase["label"] in ["Moderate", "High"]:
        missing.append("better entry location")

    return missing[:5]


def confidence_explanation(result, latest_results=None):
    missing = missing_confirmations(result, latest_results)
    if not missing:
        return "Most major confirmations are aligned."
    return "Missing: " + ", ".join(missing) + "."
