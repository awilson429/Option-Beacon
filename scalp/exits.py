from __future__ import annotations


def evaluate_exit(opportunity, *, underlying_price, option_return_pct, hold_minutes, momentum_ok=True):
    direction = getattr(opportunity.direction, "value", opportunity.direction)
    if direction == "CALL" and underlying_price <= opportunity.invalidation: return "UNDERLYING_INVALIDATION"
    if direction == "PUT" and underlying_price >= opportunity.invalidation: return "UNDERLYING_INVALIDATION"
    if option_return_pct <= -20: return "OPTION_STOP"
    if option_return_pct >= 30: return "PROFIT_TARGET"
    if hold_minutes >= opportunity.expected_hold_minutes[1]: return "MAX_HOLD"
    if hold_minutes >= 3 and not momentum_ok: return "MOMENTUM_DETERIORATION"
    return None
