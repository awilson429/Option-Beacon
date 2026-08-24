from __future__ import annotations

from datetime import datetime
from statistics import mean, pstdev
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")


def _f(value, default=0.0):
    try: return float(value)
    except (TypeError, ValueError): return default


def ema(values, period):
    if not values: return None
    result, alpha = _f(values[0]), 2 / (period + 1)
    for value in values[1:]: result = _f(value) * alpha + result * (1 - alpha)
    return result


def vwap(bars):
    volume = sum(max(0, _f(row.get("volume"))) for row in bars)
    return (sum(((_f(r["high"]) + _f(r["low"]) + _f(r["close"])) / 3) * max(0, _f(r.get("volume"))) for r in bars) / volume) if volume else None


def feature_snapshot(bars, *, now: datetime, peer_context=None, sensor_context=None):
    if len(bars) < 22: return None
    closes = [_f(row["close"]) for row in bars]; current = closes[-1]
    fast, slow = ema(closes, 9), ema(closes, 21); fast_prior = ema(closes[:-1], 9)
    session_vwap = vwap(bars); volumes = [_f(row.get("volume")) for row in bars]
    baseline = mean(volumes[-21:-1]) if any(volumes[-21:-1]) else 0
    true_ranges = [max(_f(r["high"]) - _f(r["low"]), abs(_f(r["high"]) - closes[i-1]), abs(_f(r["low"]) - closes[i-1])) for i, r in enumerate(bars[1:], 1)]
    opening = bars[:15]; local = now if now.tzinfo else now.replace(tzinfo=EASTERN); local = local.astimezone(EASTERN)
    returns = [(closes[i] / closes[i-1] - 1) for i in range(max(1, len(closes)-10), len(closes)) if closes[i-1]]
    high, low = _f(bars[-1]["high"]), _f(bars[-1]["low"]); body = abs(current - _f(bars[-1]["open"])); candle_range = high-low
    return {
        "price": current, "vwap": session_vwap, "distance_vwap_pct": (current/session_vwap-1)*100 if session_vwap else None,
        "ema_9": fast, "ema_21": slow, "ema_alignment": "BULLISH" if fast > slow else "BEARISH",
        "ema_9_slope": fast-fast_prior, "momentum_1m_pct": (current/closes[-2]-1)*100,
        "momentum_5m_pct": (current/closes[-6]-1)*100, "relative_volume": volumes[-1]/baseline if baseline else None,
        "volume_acceleration": volumes[-1]/mean(volumes[-4:-1]) if any(volumes[-4:-1]) else None,
        "atr_14": mean(true_ranges[-14:]), "realized_volatility_10": pstdev(returns) if len(returns)>1 else 0,
        "candle_body_ratio": body/candle_range if candle_range else 0, "upper_wick_ratio": (high-max(current,_f(bars[-1]["open"])))/candle_range if candle_range else 0,
        "lower_wick_ratio": (min(current,_f(bars[-1]["open"]))-low)/candle_range if candle_range else 0,
        "recent_swing_high": max(_f(r["high"]) for r in bars[-10:-1]), "recent_swing_low": min(_f(r["low"]) for r in bars[-10:-1]),
        "opening_range_high": max(_f(r["high"]) for r in opening), "opening_range_low": min(_f(r["low"]) for r in opening),
        "minutes_since_open": max(0, (local.hour*60+local.minute)-(9*60+30)), "minutes_to_close": max(0, (16*60)-(local.hour*60+local.minute)),
        "time_bucket": "OPEN" if local.hour < 10 else "MIDDAY" if local.hour < 14 else "POWER_HOUR" if local.hour >= 15 else "AFTERNOON",
        "peer_context": peer_context or {}, "sensor_context": sensor_context or {},
    }
