DEVELOPING = "Developing"
ARMED = "Armed"
TRIGGERED = "Triggered"
EXTENDED = "Extended"
FAILED = "Failed"


def _number(result, key, default=0):
    try:
        value = result.get(key, default)
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _direction(result):
    bias = result.get("bias", "Neutral")
    if bias in ["Bullish", "Bearish"]:
        return bias
    return None


def _score(result):
    return int(_number(result, "confidence", 0))


def _trigger_price(result, direction):
    if direction == "Bullish":
        return _number(result, "resistance", _number(result, "price"))
    if direction == "Bearish":
        return _number(result, "support", _number(result, "price"))
    return _number(result, "price")


def _invalidation_level(result, direction):
    if direction == "Bullish":
        return _number(result, "support", _number(result, "vwap"))
    if direction == "Bearish":
        return _number(result, "resistance", _number(result, "vwap"))
    return _number(result, "vwap")


def classify_setup_stage(result):
    if not result or result.get("signal") == "DATA UNAVAILABLE":
        return {
            "setup_stage": "Unavailable",
            "setup_stage_reason": "Market data is unavailable.",
        }

    if result.get("signal") == "MARKET CLOSED / WAIT":
        return {
            "setup_stage": "Market Closed",
            "setup_stage_reason": "Scanner is waiting for an active trading window.",
        }

    direction = _direction(result)
    if not direction:
        return {
            "setup_stage": DEVELOPING,
            "setup_stage_reason": "No clear bullish or bearish bias yet.",
        }

    price = _number(result, "price")
    atr = max(_number(result, "atr"), price * 0.0025)
    trigger = _trigger_price(result, direction)
    invalidation = _invalidation_level(result, direction)
    score = _score(result)
    signal = result.get("signal", "")

    if direction == "Bullish" and price < invalidation:
        return {
            "setup_stage": FAILED,
            "setup_stage_reason": "Bullish setup is below the invalidation level.",
        }
    if direction == "Bearish" and price > invalidation:
        return {
            "setup_stage": FAILED,
            "setup_stage_reason": "Bearish setup is above the invalidation level.",
        }

    if direction == "Bullish":
        distance_from_trigger = price - trigger
        distance_to_trigger = trigger - price
    else:
        distance_from_trigger = trigger - price
        distance_to_trigger = price - trigger

    if distance_from_trigger > atr * 0.5:
        return {
            "setup_stage": EXTENDED,
            "setup_stage_reason": "Price is more than 0.5 ATR beyond the preferred trigger.",
        }

    if signal in ["BULLISH SETUP", "BEARISH SETUP"]:
        return {
            "setup_stage": TRIGGERED,
            "setup_stage_reason": "Entry conditions have triggered, but chase rules still apply.",
        }

    if score >= 70 and 0 <= distance_to_trigger <= atr * 0.4:
        return {
            "setup_stage": ARMED,
            "setup_stage_reason": "Price is close to the trigger and conditions are developing.",
        }

    return {
        "setup_stage": DEVELOPING,
        "setup_stage_reason": "Setup is forming but has not reached the trigger area yet.",
    }
