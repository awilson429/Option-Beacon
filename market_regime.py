"""Explainable point-in-time market regime classification."""

from __future__ import annotations

import math
from datetime import datetime, timezone

from intelligence_models import MarketRegimeSnapshot


def classify_market_regime(features: dict, *, timestamp=None) -> MarketRegimeSnapshot:
    """Classify only the supplied point-in-time features; never fetch future data."""
    at = timestamp or datetime.now(timezone.utc)
    spy = _trend(features.get("spy_direction"))
    qqq = _trend(features.get("qqq_direction"))
    efficiency = _number(features.get("directional_efficiency"))
    volatility = _number(features.get("normalized_volatility"), features.get("atr_percent"))
    breadth = _number(features.get("market_breadth"))
    reasons = []
    if spy == "UNKNOWN" or qqq == "UNKNOWN" or volatility is None:
        return MarketRegimeSnapshot(
            "INSUFFICIENT_DATA", "LOW", ("MISSING_CORE_MARKET_INPUTS",), at, "INCOMPLETE"
        )
    aligned = spy == qqq and spy in {"BULLISH", "BEARISH"}
    high_vol = volatility >= 1.5
    low_vol = volatility <= 0.55
    trending = aligned and (efficiency is None or efficiency >= 0.55)
    if high_vol and trending:
        regime = "HIGH_VOLATILITY_TREND"
        reasons.extend(("ELEVATED_VOLATILITY", "SPY_QQQ_TREND_ALIGNED"))
    elif high_vol:
        regime = "HIGH_VOLATILITY_CHOP"
        reasons.extend(("ELEVATED_VOLATILITY", "DIRECTIONAL_ALIGNMENT_ABSENT"))
    elif low_vol and not trending:
        regime = "LOW_VOLATILITY_COMPRESSION"
        reasons.extend(("LOW_VOLATILITY", "LIMITED_DIRECTIONAL_EFFICIENCY"))
    elif trending and spy == "BULLISH":
        regime = "BULLISH_TREND"
        reasons.append("SPY_QQQ_BULLISH_ALIGNMENT")
    elif trending and spy == "BEARISH":
        regime = "BEARISH_TREND"
        reasons.append("SPY_QQQ_BEARISH_ALIGNMENT")
    else:
        regime = "RANGE_BOUND_CHOPPY"
        reasons.append("MIXED_OR_LOW_PERSISTENCE_DIRECTION")
    if breadth is not None:
        risk = "RISK_ON" if breadth >= 0.6 and spy == "BULLISH" else "RISK_OFF" if breadth <= 0.4 and spy == "BEARISH" else "NEUTRAL_RISK"
        reasons.append(risk)
    confidence = "HIGH" if aligned and efficiency is not None and breadth is not None else "MEDIUM"
    return MarketRegimeSnapshot(regime, confidence, tuple(reasons), at, "COMPLETE")


def _number(*values):
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            return number
    return None


def _trend(value):
    text = str(value or "").strip().upper()
    if text in {"UP", "BULLISH", "POSITIVE"}:
        return "BULLISH"
    if text in {"DOWN", "BEARISH", "NEGATIVE"}:
        return "BEARISH"
    return "UNKNOWN" if not text else "NEUTRAL"
