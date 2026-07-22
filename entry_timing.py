from setup_stages import ARMED, EXTENDED, FAILED, TRIGGERED


def classify_entry_timing(result):
    stage = result.get("setup_stage", "Developing")
    direction = result.get("bias", "Neutral")

    if stage in ["Unavailable", "Market Closed"]:
        return {
            "entry_timing": "Wait",
            "entry_timing_reason": "Scanner is not showing an actionable live setup.",
        }

    if stage == FAILED:
        return {
            "entry_timing": "Setup invalidated",
            "entry_timing_reason": "The invalidation level has already been breached.",
        }

    if stage == EXTENDED:
        return {
            "entry_timing": "Do not chase",
            "entry_timing_reason": "The move is already stretched beyond the preferred entry area.",
        }

    if stage == TRIGGERED:
        return {
            "entry_timing": "Trigger confirmed",
            "entry_timing_reason": "The setup has triggered and remains inside chase limits.",
        }

    if stage == ARMED:
        trigger = result.get("trigger_price")
        if trigger:
            label = "above" if direction == "Bullish" else "below"
            return {
                "entry_timing": "Watch closely",
                "entry_timing_reason": f"Watch for entry {label} ${trigger:.2f} with volume confirmation.",
            }
        return {
            "entry_timing": "Watch closely",
            "entry_timing_reason": "Setup is close to triggering.",
        }

    return {
        "entry_timing": "Too early",
        "entry_timing_reason": "Conditions are developing, but the entry trigger has not formed yet.",
    }
