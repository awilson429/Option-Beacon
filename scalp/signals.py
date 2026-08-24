from __future__ import annotations

from scalp.models import Direction, ScalpState


def classify_signal(features):
    if not features: return {"direction": None, "family": None, "state": ScalpState.IDLE, "probability": None}
    price, vwap = features["price"], features["vwap"]
    rv = features.get("relative_volume") or 0; m1 = features["momentum_1m_pct"]
    bull = price > vwap and features["ema_alignment"] == "BULLISH"
    bear = price < vwap and features["ema_alignment"] == "BEARISH"
    direction = Direction.CALL if bull else Direction.PUT if bear else None
    if direction is None: return {"direction": None, "family": None, "state": ScalpState.WATCHING, "probability": 0.5}
    signed_momentum = m1 if direction == Direction.CALL else -m1
    probability = min(.82, .52 + min(.12, abs(features["distance_vwap_pct"])*4) + min(.1, max(0,rv-1)*.1) + min(.08,max(0,signed_momentum)*2))
    breakout = price > features["recent_swing_high"] if direction == Direction.CALL else price < features["recent_swing_low"]
    family = "MOMENTUM_BREAKOUT" if breakout else "VWAP_CONTINUATION"
    state = ScalpState.TRIGGERED if breakout and rv >= 1.1 else ScalpState.READY if probability >= .62 else ScalpState.FORMING
    return {"direction": direction, "family": family, "state": state, "probability": round(probability,4)}
