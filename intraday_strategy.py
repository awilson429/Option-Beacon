"""Explainable, paper-only SPY/QQQ intraday signal detection.

This module is intentionally independent from OptionBeacon's authoritative scanner.
It has no persistence, broker, or order-submission dependencies and is replayable.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, time
from enum import Enum
from zoneinfo import ZoneInfo


EASTERN = ZoneInfo("America/New_York")
UNIVERSE = ("SPY", "QQQ")


class OpportunityState(str, Enum):
    OBSERVING = "OBSERVING"
    SETUP_DETECTED = "SETUP_DETECTED"
    ARMED = "ARMED"
    TRIGGERED = "TRIGGERED"
    PAPER_OPENED = "PAPER_OPENED"
    MANAGED = "MANAGED"
    CLOSED = "CLOSED"


ALLOWED_TRANSITIONS = {
    OpportunityState.OBSERVING: {OpportunityState.SETUP_DETECTED},
    OpportunityState.SETUP_DETECTED: {OpportunityState.ARMED, OpportunityState.CLOSED},
    OpportunityState.ARMED: {OpportunityState.TRIGGERED, OpportunityState.CLOSED},
    OpportunityState.TRIGGERED: {OpportunityState.PAPER_OPENED, OpportunityState.CLOSED},
    OpportunityState.PAPER_OPENED: {OpportunityState.MANAGED, OpportunityState.CLOSED},
    OpportunityState.MANAGED: {OpportunityState.CLOSED},
    OpportunityState.CLOSED: set(),
}


def transition(current, target):
    current, target = OpportunityState(current), OpportunityState(target)
    if target not in ALLOWED_TRANSITIONS[current]:
        raise ValueError(f"Invalid intraday transition: {current.value} -> {target.value}")
    return target


def _number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def ema(values, period):
    values = [_number(value) for value in values]
    if not values:
        return None
    result, alpha = values[0], 2 / (period + 1)
    for value in values[1:]:
        result = value * alpha + result * (1 - alpha)
    return result


def session_vwap(bars):
    weighted = volume = 0.0
    for bar in bars:
        bar_volume = max(0.0, _number(bar.get("volume")))
        typical = (_number(bar.get("high")) + _number(bar.get("low")) + _number(bar.get("close"))) / 3
        weighted += typical * bar_volume
        volume += bar_volume
    return weighted / volume if volume else None


def aggregate_bars(bars, minutes):
    """Deterministically aggregate aligned 1-minute ET bars into N-minute bars."""
    groups = {}
    for bar in bars:
        stamp = bar["timestamp"]
        stamp = stamp if isinstance(stamp, datetime) else datetime.fromisoformat(str(stamp))
        stamp = stamp.replace(tzinfo=EASTERN) if stamp.tzinfo is None else stamp.astimezone(EASTERN)
        session_minutes = (stamp.hour * 60 + stamp.minute) - (9 * 60 + 30)
        if session_minutes < 0:
            continue
        bucket = stamp.replace(second=0, microsecond=0) - __import__("datetime").timedelta(minutes=session_minutes % minutes)
        groups.setdefault(bucket, []).append(bar)
    result = []
    for stamp in sorted(groups):
        rows = groups[stamp]
        result.append({"timestamp": stamp, "open": _number(rows[0]["open"]),
                       "high": max(_number(row["high"]) for row in rows),
                       "low": min(_number(row["low"]) for row in rows),
                       "close": _number(rows[-1]["close"]),
                       "volume": sum(_number(row.get("volume")) for row in rows)})
    return result


def session_bucket(at):
    local = at.replace(tzinfo=EASTERN) if at.tzinfo is None else at.astimezone(EASTERN)
    value = local.time()
    if value < time(10): return "OPEN"
    if value < time(11, 30): return "MORNING"
    if value < time(13, 30): return "MIDDAY"
    if value < time(15): return "AFTERNOON"
    return "LATE"


def classify_regime(bars):
    if len(bars) < 21:
        return "OPENING VOLATILITY" if len(bars) < 15 else "RANGE / CHOP"
    closes = [_number(row["close"]) for row in bars]
    fast, slow = ema(closes, 9), ema(closes, 21)
    recent_range = max(_number(row["high"]) for row in bars[-10:]) - min(_number(row["low"]) for row in bars[-10:])
    price = closes[-1]
    if price and recent_range / price >= 0.008:
        return "HIGH VOLATILITY"
    separation = (fast - slow) / price if price else 0
    if separation > 0.0006: return "TRENDING UP"
    if separation < -0.0006: return "TRENDING DOWN"
    return "RANGE / CHOP"


def market_context(bars):
    closes = [_number(row["close"]) for row in bars]
    if len(closes) < 3:
        return "NEUTRAL"
    vwap = session_vwap(bars)
    fast, slow = ema(closes, 9), ema(closes, 21)
    if closes[-1] > (vwap or closes[-1]) and fast > slow: return "BULLISH"
    if closes[-1] < (vwap or closes[-1]) and fast < slow: return "BEARISH"
    return "NEUTRAL"


@dataclass(frozen=True)
class Candidate:
    opportunity_id: str
    symbol: str
    direction: str
    setup: str
    confidence: int
    price: float
    trigger: float
    detected_at: datetime
    session_bucket: str
    regime: str
    reasons: tuple[str, ...] = field(default_factory=tuple)
    waiting_for: str = "trigger confirmation"
    cross_market: dict = field(default_factory=dict)

    @property
    def option_type(self):
        return "call" if self.direction == "CALL" else "put"


def opportunity_id(symbol, setup, direction, detected_at):
    local = detected_at.replace(tzinfo=EASTERN) if detected_at.tzinfo is None else detected_at.astimezone(EASTERN)
    # Five-minute identity prevents duplicate trades while a setup remains active.
    bucket = local.replace(minute=(local.minute // 5) * 5, second=0, microsecond=0)
    return hashlib.sha256(f"INDEX_INTRADAY_V1|{symbol}|{setup}|{direction}|{bucket.isoformat()}".encode()).hexdigest()


def detect_candidate(symbol, bars, peer_bars, *, now=None):
    symbol = str(symbol).upper()
    if symbol not in UNIVERSE or len(bars) < 22:
        return None
    now = now or bars[-1]["timestamp"]
    local = now.replace(tzinfo=EASTERN) if now.tzinfo is None else now.astimezone(EASTERN)
    closes = [_number(row["close"]) for row in bars]
    current, prior = closes[-1], closes[-2]
    vwap_now, vwap_prior = session_vwap(bars), session_vwap(bars[:-1])
    fast, slow = ema(closes, 9), ema(closes, 21)
    avg_volume = sum(_number(row.get("volume")) for row in bars[-21:-1]) / 20
    volume_ratio = _number(bars[-1].get("volume")) / avg_volume if avg_volume else 1
    five = aggregate_bars(bars, 5)
    five_closes = [_number(row["close"]) for row in five]
    five_bull = len(five_closes) >= 5 and ema(five_closes, 3) >= ema(five_closes, 5)
    regime = classify_regime(bars)
    setup = direction = None
    reasons = []
    trigger = current

    if prior <= vwap_prior and current > vwap_now and fast > slow:
        setup, direction, trigger = "VWAP RECLAIM", "CALL", max(_number(bars[-1]["high"]), current)
        reasons = ["1m VWAP reclaimed", "EMA 9 above EMA 21"]
    elif prior >= vwap_prior and current < vwap_now and fast < slow:
        setup, direction, trigger = "VWAP REJECTION", "PUT", min(_number(bars[-1]["low"]), current)
        reasons = ["1m VWAP rejected", "EMA 9 below EMA 21"]
    else:
        opening = [row for row in bars if time(9, 30) <= (row["timestamp"] if isinstance(row["timestamp"], datetime) else datetime.fromisoformat(str(row["timestamp"]))).astimezone(EASTERN).time() < time(9, 45)]
        if opening and local.time() >= time(9, 45):
            or_high = max(_number(row["high"]) for row in opening)
            or_low = min(_number(row["low"]) for row in opening)
            if prior <= or_high < current and volume_ratio >= 1.1:
                setup, direction, trigger = "OPENING RANGE BREAKOUT", "CALL", or_high
                reasons = ["15-minute opening range high broken", "volume confirms breakout"]
            elif prior >= or_low > current and volume_ratio >= 1.1:
                setup, direction, trigger = "OPENING RANGE BREAKDOWN", "PUT", or_low
                reasons = ["15-minute opening range low broken", "volume confirms breakdown"]
        if setup is None:
            near_fast = abs(current - fast) / current <= 0.0025 if current else False
            if fast > slow and five_bull and near_fast and current > prior:
                setup, direction, trigger = "TREND CONTINUATION", "CALL", _number(bars[-1]["high"])
                reasons = ["EMA 9 above EMA 21", "5m trend bullish", "pullback resumed"]
            elif fast < slow and not five_bull and near_fast and current < prior:
                setup, direction, trigger = "TREND CONTINUATION", "PUT", _number(bars[-1]["low"])
                reasons = ["EMA 9 below EMA 21", "5m trend bearish", "pullback resumed"]
    if setup is None:
        return None
    peer = market_context(peer_bars)
    own = "BULLISH" if direction == "CALL" else "BEARISH"
    agreement = peer == own
    confidence = 68 + (6 if volume_ratio >= 1.25 else 0) + (6 if agreement else -4 if peer != "NEUTRAL" else 0)
    if agreement: reasons.append(("QQQ" if symbol == "SPY" else "SPY") + " confirms")
    elif peer != "NEUTRAL": reasons.append(("QQQ" if symbol == "SPY" else "SPY") + " disagrees")
    if abs(current - vwap_now) / current <= 0.004: reasons.append("not extended from VWAP")
    return Candidate(opportunity_id(symbol, setup, direction, local), symbol, direction, setup,
                     max(0, min(100, confidence)), current, trigger, local,
                     session_bucket(local), regime, tuple(reasons),
                     cross_market={"symbol_context": own, "peer_context": peer,
                                   "agreement": agreement})


def trigger_crossed(candidate, previous_price, current_price):
    if candidate.direction == "CALL":
        return previous_price < candidate.trigger <= current_price
    return previous_price > candidate.trigger >= current_price
