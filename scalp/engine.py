from __future__ import annotations

import hashlib
from datetime import datetime

from scalp.features import feature_snapshot
from scalp.models import Direction, ScalpOpportunity, ScalpState
from scalp.signals import classify_signal


class ScalpEngine:
    """Pure research evaluator. It has no broker, provider, or persistence dependency."""
    symbols = frozenset({"SPY", "QQQ"})

    def evaluate(self, symbol, bars, *, now: datetime | None = None, peer_context=None, sensor_context=None):
        symbol = str(symbol).upper()
        if symbol not in self.symbols: raise ValueError(f"Unsupported scalp symbol: {symbol}")
        now = now or (bars[-1]["timestamp"] if bars else datetime.now().astimezone())
        features = feature_snapshot(bars, now=now, peer_context=peer_context, sensor_context=sensor_context)
        signal = classify_signal(features)
        direction, state = signal["direction"], signal["state"]
        price = features["price"] if features else None; atr = features["atr_14"] if features else None
        trigger = None if not direction else (features["recent_swing_high"] if direction == Direction.CALL else features["recent_swing_low"])
        invalidation = None if not direction else (min(features["vwap"], features["ema_21"]) if direction == Direction.CALL else max(features["vwap"], features["ema_21"]))
        chase = None if trigger is None else trigger + (atr*.2 if direction == Direction.CALL else -atr*.2)
        if state == ScalpState.TRIGGERED and ((direction == Direction.CALL and price > chase) or (direction == Direction.PUT and price < chase)): state = ScalpState.EXTENDED
        identity = hashlib.sha256(f"SCALP_RESEARCH|{symbol}|{now.isoformat()}|{direction}".encode()).hexdigest()[:24]
        zone = None if trigger is None else tuple(sorted((trigger, trigger + (atr*.08 if direction == Direction.CALL else -atr*.08))))
        return ScalpOpportunity(identity, symbol, now, direction, signal["family"], state, signal["probability"], trigger, zone,
                                invalidation, chase, atr*.35 if atr else None, features=features or {})
