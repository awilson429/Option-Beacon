"""Bounded observational capture for the canonical SPY/QQQ decision chain."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from signal_history import scanner_result_decision
from trade_repository import parse_utc


SUPPORTED_PROVENANCE_SYMBOLS = frozenset({"SPY", "QQQ"})
COMPONENT_SCORE_FIELDS = (
    "trend_score", "momentum_score", "volume_score", "volatility_score",
    "price_action_score",
)
DECISION_INDICATOR_FIELDS = (
    "relative_volume", "atr", "rsi", "vwap", "support", "resistance",
    "prior_15_high", "prior_15_low", "ema20", "ema50", "ema200", "macd",
    "macd_signal", "macd_hist", "volume", "avg_volume",
)


def _stable_id(namespace, payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(f"{namespace}|{encoded}".encode("utf-8")).hexdigest()


def scan_cycle_identity(*, scanner_id, run_number, started_at):
    return _stable_id("decision-provenance-cycle-v1", {
        "scanner_id": str(scanner_id), "run_number": run_number,
        "started_at": parse_utc(started_at).isoformat(),
    })


def observation_identity(*, scan_cycle_id, symbol, observed_at, data_timestamp=None):
    return _stable_id("decision-provenance-observation-v1", {
        "scan_cycle_id": str(scan_cycle_id), "symbol": str(symbol).upper(),
        "observed_at": parse_utc(observed_at).isoformat(),
        "data_timestamp": parse_utc(data_timestamp).isoformat() if data_timestamp else None,
    })


def _result_timestamp(result):
    value = (result or {}).get("last_candle_at") or (result or {}).get("timestamp")
    return parse_utc(value) if value else None


def _number(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _reasons(result):
    values = [
        *((result or {}).get("reasons") or []),
        (result or {}).get("setup_stage_reason"),
        (result or {}).get("entry_timing_reason"),
        (result or {}).get("what_next_reason"),
    ]
    unique = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in unique:
            unique.append(text)
    return unique[:20]


def build_observation(*, scan_cycle_id, symbol, observed_at, result=None,
                      failure=None, source_version=None):
    """Build one bounded row from existing strategy output without re-deciding it."""
    symbol = str(symbol).upper()
    if symbol not in SUPPORTED_PROVENANCE_SYMBOLS:
        return None
    observed = parse_utc(observed_at) or datetime.now(timezone.utc)
    data_timestamp = _result_timestamp(result)
    age = max(0, (observed - data_timestamp).total_seconds()) if data_timestamp else None
    stale = bool(age is not None and age > 900)
    if failure is not None:
        disposition = {
            "qualification_state": "DATA_UNSAFE",
            "reason_code": type(failure).__name__.upper(),
            "explanation": "The existing signal generator could not produce a safe decision result.",
        }
    elif result is None:
        disposition = {
            "qualification_state": "DATA_UNSAFE",
            "reason_code": "NO_RESULT",
            "explanation": "The existing signal generator returned no decision result.",
        }
    else:
        _, disposition = scanner_result_decision(result)
    component_scores = {
        key: _number((result or {}).get(key)) for key in COMPONENT_SCORE_FIELDS
        if (result or {}).get(key) is not None
    }
    indicators = {
        key: _number((result or {}).get(key)) for key in DECISION_INDICATOR_FIELDS
        if (result or {}).get(key) is not None
    }
    observation_id = observation_identity(
        scan_cycle_id=scan_cycle_id, symbol=symbol, observed_at=observed,
        data_timestamp=data_timestamp,
    )
    return {
        "observation_id": observation_id,
        "scan_cycle_id": str(scan_cycle_id),
        "symbol": symbol,
        "observed_at": observed,
        "data_timestamp": data_timestamp,
        "underlying_price": _number((result or {}).get("price")),
        "session_state": "SCANNER_BLOCKED" if disposition["qualification_state"] == "SESSION_BLOCKED"
            else "SCANNER_EVALUATED",
        "direction": (result or {}).get("bias"),
        "data_quality": "error" if failure or result is None else "stale" if stale else "fresh",
        "stale": stale,
        "signal": (result or {}).get("signal"),
        "setup_state": (result or {}).get("setup_stage") or (result or {}).get("entry_timing"),
        **disposition,
        "total_score": _number((result or {}).get("score")),
        "confidence": _number((result or {}).get("confidence")),
        "bullish_score": _number((result or {}).get("bullish_score")),
        "bearish_score": _number((result or {}).get("bearish_score")),
        "component_scores": component_scores,
        "indicators": indicators,
        "reasons": _reasons(result),
        "opportunity_id": None,
        "source_version": source_version,
    }
