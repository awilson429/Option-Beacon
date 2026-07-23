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


def _latest_history_row(history, symbol):
    if history is None or history.empty or "symbol" not in history.columns:
        return None

    rows = history[history["symbol"] == symbol]
    if rows.empty:
        return None
    return rows.iloc[-1].to_dict()


def setup_momentum_snapshot(result, history=None):
    symbol = result.get("symbol")
    current_score = _number(result.get("confidence"))
    current_bias = result.get("bias", "Neutral")
    current_signal = result.get("signal", "WATCHLIST")
    previous = _latest_history_row(history, symbol)

    if not previous:
        return {
            "label": "New read",
            "detail": "No recent high-score history for comparison yet.",
            "score_change": None,
            "bias_changed": False,
        }

    previous_score = _number(previous.get("score"))
    previous_bias = previous.get("bias", "Neutral")
    previous_signal = previous.get("signal", "WATCHLIST")
    score_change = round(current_score - previous_score, 1)
    bias_changed = bool(previous_bias and previous_bias != current_bias)
    signal_changed = bool(previous_signal and previous_signal != current_signal)

    if bias_changed:
        label = "Bias flipped"
        detail = f"Previous bias was {previous_bias}; current bias is {current_bias}."
    elif score_change >= 8:
        label = "Improving"
        detail = f"Score improved by {score_change:g} points since the last high-score read."
    elif score_change <= -8:
        label = "Weakening"
        detail = f"Score faded by {abs(score_change):g} points since the last high-score read."
    elif signal_changed:
        label = "State changed"
        detail = f"Signal changed from {previous_signal} to {current_signal}."
    else:
        label = "Stable"
        detail = "Current read is similar to the last high-score snapshot."

    return {
        "label": label,
        "detail": detail,
        "score_change": score_change,
        "bias_changed": bias_changed,
    }
