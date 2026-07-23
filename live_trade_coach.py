ACTION_ENTER = "Entry zone active"
ACTION_WATCH = "Watch for trigger"
ACTION_HOLD = "Manage active idea"
ACTION_AVOID = "Avoid chasing"
ACTION_WAIT = "Wait"


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
            f"Coach this as a call idea. First target is {_format_price(target_1)}. "
            f"If price pushes toward {_format_price(target_2)}, protect gains and trail. "
            f"If price loses {_format_price(stop)}, the bullish thesis is weakened."
        )

    if direction == "Bearish":
        return (
            f"Coach this as a put idea. First target is {_format_price(target_1)}. "
            f"If price flushes toward {_format_price(target_2)}, protect gains and trail. "
            f"If price reclaims {_format_price(stop)}, the bearish thesis is weakened."
        )

    return f"Wait for a clearer setup. Breakeven reference: {_format_price(breakeven)}."


def coach_live_setup(result):
    if not result:
        return {
            "action": ACTION_WAIT,
            "priority": 0,
            "summary": "No scanner data is available yet.",
            "next_step": "Wait for fresh 5-minute scanner data.",
            "risk_note": "No trade idea is active.",
            "contract": "N/A",
        }

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

    if signal in ["MARKET CLOSED / WAIT", "WAITING FOR CANDLE"]:
        return {
            "action": ACTION_WAIT,
            "priority": score,
            "summary": f"{direction} setup is not actionable yet.",
            "next_step": "Wait for the next completed 5-minute candle.",
            "risk_note": "Do not force an entry while the scanner is waiting.",
            "contract": contract,
        }

    if signal == "DATA UNAVAILABLE":
        return {
            "action": ACTION_WAIT,
            "priority": 0,
            "summary": "Market data is unavailable for this symbol.",
            "next_step": "Skip this ticker until fresh data returns.",
            "risk_note": "No trade idea should be evaluated without data.",
            "contract": contract,
        }

    if timing == "Do not chase" or stage == "Extended":
        return {
            "action": ACTION_AVOID,
            "priority": score,
            "summary": f"{direction} setup is extended at {price}.",
            "next_step": f"Do not chase past {max_entry}. Wait for a reset or a new setup.",
            "risk_note": f"Invalidation remains {invalidation}.",
            "contract": contract,
        }

    if timing == "Trigger confirmed" and signal in ["BULLISH SETUP", "BEARISH SETUP"]:
        return {
            "action": ACTION_ENTER,
            "priority": score,
            "summary": f"{direction} {contract} idea is active at {price}.",
            "next_step": f"Entry is valid near {trigger} if price remains inside the plan.",
            "risk_note": _management_text(result),
            "contract": contract,
        }

    if timing == "Watch closely" or stage == "Armed":
        return {
            "action": ACTION_WATCH,
            "priority": score,
            "summary": f"{direction} {contract} idea is setting up.",
            "next_step": f"Watch for confirmation through {trigger} with volume.",
            "risk_note": f"Do not act if price violates {invalidation}.",
            "contract": contract,
        }

    if score >= 85 and direction in ["Bullish", "Bearish"]:
        return {
            "action": ACTION_HOLD,
            "priority": score,
            "summary": f"{direction} idea has a strong score but timing is {timing.lower()}.",
            "next_step": result.get("what_next_reason") or "Wait for cleaner timing.",
            "risk_note": f"Use {invalidation} as the thesis failure area.",
            "contract": contract,
        }

    return {
        "action": ACTION_WAIT,
        "priority": score,
        "summary": f"{direction} setup is still developing.",
        "next_step": result.get("what_next_reason") or "Wait for stronger alignment.",
        "risk_note": "No live trade idea is active yet.",
        "contract": contract,
    }


def coach_rows(latest_results, min_score=80):
    rows = []
    for symbol, result in latest_results.items():
        coach = coach_live_setup(result)
        if coach["priority"] < min_score and coach["action"] == ACTION_WAIT:
            continue

        rows.append(
            {
                "Symbol": symbol,
                "Action": coach["action"],
                "Bias": (result or {}).get("bias", "Neutral"),
                "Score": coach["priority"],
                "Contract": coach["contract"],
                "Price": (result or {}).get("price"),
                "Stage": (result or {}).get("setup_stage", "Developing"),
                "Timing": (result or {}).get("entry_timing", "Wait"),
                "Coach Summary": coach["summary"],
                "Next Step": coach["next_step"],
                "Risk Note": coach["risk_note"],
            }
        )

    return sorted(rows, key=lambda row: row["Score"], reverse=True)
