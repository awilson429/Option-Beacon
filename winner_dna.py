"""Read-only Winner DNA and entry-attribution analytics."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean, median
from zoneinfo import ZoneInfo

from selectivity_analysis import build_analysis_rows, chronological_split


FLAT_NOISE_THRESHOLD_PCT = 0.10
MIN_PATTERN_SAMPLE = 10
EASTERN = ZoneInfo("America/New_York")
FEATURE_DEFINITIONS = {
    "confidence": "PERSISTED",
    "rule_score": "PERSISTED",
    "direction": "PERSISTED",
    "symbol": "PERSISTED",
    "setup": "PERSISTED",
    "entry_price": "PERSISTED",
    "relative_volume": "PERSISTED",
    "vwap_relationship": "PERSISTED",
    "vwap_distance": "PERSISTED",
    "ema9": "PERSISTED",
    "ema21": "PERSISTED",
    "ema9_slope": "PERSISTED",
    "rsi": "PERSISTED",
    "atr": "PERSISTED",
    "candle_body_percent": "PERSISTED",
    "breakout_distance": "PERSISTED",
    "trend_alignment": "PERSISTED",
    "session_segment": "PERSISTED",
    "market_regime": "PERSISTED",
    "sector": "PERSISTED",
    "sector_alignment": "PERSISTED",
    "time_of_day": "DERIVABLE FROM PERSISTED DATA",
    "ema_relationship": "DERIVABLE FROM PERSISTED DATA",
    "spy_qqq_agreement": "DERIVABLE FROM PERSISTED DATA",
    "trigger_distance": "NOT PERSISTED",
    "atr_normalized_trigger_distance": "NOT PERSISTED",
    "macd_state": "NOT PERSISTED",
    "support_resistance_proximity": "NOT PERSISTED",
    "candidate_age": "NOT PERSISTED",
    "prior_scans_before_entry": "NOT PERSISTED",
    "delta": "NOT PERSISTED IN AUTHORITATIVE SNAPSHOT",
    "iv": "NOT PERSISTED IN AUTHORITATIVE SNAPSHOT",
}


def _number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _average(values):
    values = [value for value in values if value is not None]
    return mean(values) if values else None


def _percentile(values, percentile):
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * percentile
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def outcome_thresholds(rows):
    positives = [row["realized_return"] for row in rows if row["realized_return"] > FLAT_NOISE_THRESHOLD_PCT]
    return {"flat_noise_absolute_pct": FLAT_NOISE_THRESHOLD_PCT,
            "large_winner_positive_75th_percentile": _percentile(positives, .75)}


def classify_outcome(value, thresholds):
    value = _number(value)
    if value is None:
        return "UNAVAILABLE"
    if abs(value) <= thresholds["flat_noise_absolute_pct"]:
        return "FLAT / NOISE"
    if value < 0:
        return "LOSER"
    large = thresholds["large_winner_positive_75th_percentile"]
    return "LARGE WINNER" if large is not None and value >= large else "SMALL WINNER"


def session_bucket(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        parsed = parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
        local = parsed.astimezone(EASTERN)
        minute = local.hour * 60 + local.minute
    except (TypeError, ValueError):
        return None
    if minute < 10 * 60 + 15: return "OPEN"
    if minute < 12 * 60: return "MORNING"
    if minute < 14 * 60: return "MIDDAY"
    if minute < 15 * 60 + 30: return "AFTERNOON"
    return "LATE"


def feature_bin(feature, value):
    value = _number(value)
    if value is None:
        return "MISSING"
    edges = {
        "confidence": ((-math.inf, 65), (65, 70), (70, 75), (75, 80), (80, math.inf)),
        "rule_score": ((-math.inf, 65), (65, 70), (70, 75), (75, 80), (80, math.inf)),
        "relative_volume": ((-math.inf, 1), (1, 1.25), (1.25, 1.5), (1.5, 2), (2, math.inf)),
        "rsi": ((-math.inf, 40), (40, 50), (50, 60), (60, 70), (70, math.inf)),
    }.get(feature)
    if not edges:
        return str(value)
    low, high = next((bounds for bounds in edges if bounds[0] <= value < bounds[1]), edges[-1])
    return f"{low:g}–{high:g}"


def summarize(rows, return_key="realized_return"):
    returns = [_number(row.get(return_key)) for row in rows]
    returns = [value for value in returns if value is not None]
    wins, losses = [value for value in returns if value > 0], [value for value in returns if value < 0]
    gross_loss = abs(sum(losses))
    return {
        "n": len(rows), "decided_n": len(returns),
        "win_rate": len(wins) / len(returns) * 100 if returns else None,
        "average_return": mean(returns) if returns else None,
        "median_return": median(returns) if returns else None,
        "average_winner": mean(wins) if wins else None,
        "average_loser": mean(losses) if losses else None,
        "expectancy": mean(returns) if returns else None,
        "profit_factor": sum(wins) / gross_loss if gross_loss else math.inf if wins else None,
    }


def _peak_capital(rows):
    events = []
    for row in rows:
        debit = _number(row.get("mirror_debit"))
        start, end = row.get("mirror_opened_at"), row.get("mirror_closed_at")
        if debit is None or not start:
            continue
        start = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(end).replace("Z", "+00:00")) if end else start
        events += [(start, 1, debit), (end, -1, debit)]
    capital = peak = 0.0
    for _, kind, debit in sorted(events, key=lambda item: (item[0], item[1])):
        capital += debit if kind == 1 else -debit
        peak = max(peak, capital)
    return peak


def _mirror_summary(rows):
    realized = [row for row in rows if row.get("mirror_pnl") is not None]
    pnl = [row["mirror_pnl"] for row in realized]
    debits = [row["mirror_debit"] for row in realized if row.get("mirror_debit") is not None]
    peak = _peak_capital(realized)
    gross_loss = abs(sum(value for value in pnl if value < 0))
    return {
        "mirror_n": len(realized),
        "mirror_win_rate": sum(value > 0 for value in pnl) / len(pnl) * 100 if pnl else None,
        "average_mirror_return": _average(row.get("mirror_return") for row in realized),
        "mirror_net_pnl": sum(pnl),
        "mirror_profit_factor": sum(value for value in pnl if value > 0) / gross_loss if gross_loss else math.inf if any(value > 0 for value in pnl) else None,
        "average_debit": _average(debits), "peak_capital": peak,
        "return_on_debit": sum(pnl) / sum(debits) * 100 if debits and sum(debits) else None,
        "return_on_peak_capital": sum(pnl) / peak * 100 if peak else None,
    }


def _group(rows, key):
    groups = defaultdict(list)
    for row in rows:
        groups[str(row.get(key) or "MISSING")].append(row)
    return [{"group": name, **summarize(items), **_mirror_summary(items),
             "large_winner_rate": sum(item["outcome_bucket"] == "LARGE WINNER" for item in items) / len(items) * 100,
             "average_confidence": _average(item.get("confidence") for item in items),
             "average_volume_ratio": _average(item.get("relative_volume") for item in items),
             "average_atr": _average(item.get("atr") for item in items),
             "average_hold_minutes": _average(item.get("hold_minutes") for item in items),
             "average_mirror_spread_percent": _average(item.get("mirror_spread_percent") for item in items),
             "average_mirror_dte": _average(item.get("mirror_dte") for item in items),
             "rows": items} for name, items in sorted(groups.items())]


def _pattern_rows(rows):
    definitions = (
        ("CONFIDENCE ≥70 + VOLUME ≥1.5", lambda row: (row.get("confidence") or -math.inf) >= 70 and (row.get("relative_volume") or -math.inf) >= 1.5),
        ("VWAP + EMA ALIGNED", lambda row: str(row.get("vwap_relationship")).upper() in {"ABOVE", "BELOW"} and bool(row.get("trend_alignment"))),
        ("MORNING + TREND ALIGNED", lambda row: row.get("session_bucket") == "MORNING" and bool(row.get("trend_alignment"))),
        ("HIGH VOLUME + SPY/QQQ AGREEMENT", lambda row: (row.get("relative_volume") or -math.inf) >= 1.5 and row.get("spy_qqq_agreement") is True),
    )
    result = []
    for name, predicate in definitions:
        selected = [row for row in rows if predicate(row)]
        train, validation = chronological_split(selected)
        total_summary, train_summary, validation_summary = summarize(selected), summarize(train), summarize(validation)
        sufficient = len(selected) >= MIN_PATTERN_SAMPLE and len(train) >= 5 and len(validation) >= 3
        stable = sufficient and (train_summary["expectancy"] or 0) > 0 and (validation_summary["expectancy"] or 0) > 0
        symbols = {row.get("symbol") for row in selected if row.get("symbol")}
        regimes = {row.get("market_regime") for row in selected if row.get("market_regime")}
        sessions = {str(row.get("entry_timestamp"))[:10] for row in selected}
        result.append({"pattern": name, **total_summary, **_mirror_summary(selected),
                       "train": train_summary, "validation": validation_summary,
                       "train_n": len(train), "validation_n": len(validation),
                       "sessions": len(sessions), "symbols": len(symbols), "regimes": len(regimes),
                       "call_count": sum(str(row.get("direction")).lower().startswith("bull") for row in selected),
                       "put_count": sum(str(row.get("direction")).lower().startswith("bear") for row in selected),
                       "stability": "PROMISING" if stable else "UNSTABLE" if sufficient else "INSUFFICIENT DATA"})
    return result


def analyze_winner_dna(snapshot_rows, outcome_rows, *, mirror_rows=(), mirror_marks=(),
                       broad_journal=(), broad_captures=()):
    """Build deterministic entry attribution using immutable entry snapshots."""
    rows, exclusions = build_analysis_rows(snapshot_rows, outcome_rows)
    snapshots = {(wrapped.get("snapshot") or wrapped).get("opportunity_id"): wrapped.get("snapshot") or wrapped
                 for wrapped in snapshot_rows}
    mirrors = {str(row.get("opportunity_id")): row for row in mirror_rows}
    marks_by_trade = defaultdict(list)
    for mark in mirror_marks:
        marks_by_trade[str(mark.get("mirror_trade_id"))].append(mark)
    source_by_trade = {str(capture.trade_id): str(capture.source_signal_id) for capture in broad_captures}
    broad = {}
    for decision in sorted(broad_journal, key=lambda row: str(row.get("created_at") or "")):
        source = source_by_trade.get(str(decision.get("trade_id")))
        if source and source not in broad:
            broad[source] = decision.get("reason_code")
    enriched = []
    for row in rows:
        identity = str(row["opportunity_id"])
        snapshot, mirror = snapshots.get(identity, {}), mirrors.get(identity, {})
        features = snapshot.get("features") or {}
        spy, qqq = features.get("spy_direction"), features.get("qqq_direction")
        mirror_marks_for_trade = marks_by_trade.get(str(mirror.get("mirror_trade_id")), [])
        enriched.append({**row,
            "relative_volume": _number(features.get("relative_volume") or features.get("volume_ratio")),
            "spy_direction": spy, "qqq_direction": qqq,
            "spy_qqq_agreement": bool(spy and qqq and str(spy).upper() == str(qqq).upper()) if spy and qqq else None,
            "session_bucket": session_bucket(row.get("entry_timestamp")),
            "time_of_day": session_bucket(row.get("entry_timestamp")),
            "ema_relationship": ("EMA9_ABOVE_EMA21" if row.get("ema9") > row.get("ema21") else "EMA9_BELOW_EMA21")
            if row.get("ema9") is not None and row.get("ema21") is not None else None,
            "mirror_pnl": _number(mirror.get("realized_pnl")),
            "mirror_return": _number(mirror.get("realized_return_percent")),
            "mirror_debit": _number(mirror.get("total_debit")),
            "mirror_spread_percent": _number(mirror.get("spread_percent")),
            "mirror_dte": _number(mirror.get("dte")),
            "mirror_opened_at": mirror.get("opened_at"),
            "mirror_closed_at": mirror.get("exit_quote_at"),
            "mirror_marks_available": any(_number(mark.get("return_pct")) is not None for mark in mirror_marks_for_trade),
            "broad_disposition": broad.get(identity),
        })
    thresholds = outcome_thresholds(enriched)
    for row in enriched:
        row["outcome_bucket"] = classify_outcome(row["realized_return"], thresholds)
        auth_win, mirror_pnl = row["realized_return"] > 0, row.get("mirror_pnl")
        row["option_translation_bucket"] = (
            ("AUTH WIN / MIRROR WIN" if mirror_pnl > 0 else "AUTH WIN / MIRROR LOSS") if auth_win
            else ("AUTH LOSS / MIRROR WIN" if mirror_pnl > 0 else "AUTH LOSS / MIRROR LOSS")
        ) if mirror_pnl is not None else "MIRROR UNAVAILABLE"
    coverage = {name: sum(row.get(name) is not None for row in enriched) / len(enriched) * 100 if enriched else 0
                for name, status in FEATURE_DEFINITIONS.items() if status != "NOT PERSISTED"}
    coverage["mirror_outcome"] = sum(row.get("mirror_pnl") is not None for row in enriched) / len(enriched) * 100 if enriched else 0
    coverage["mirror_marks"] = sum(row.get("mirror_marks_available") for row in enriched) / len(enriched) * 100 if enriched else 0
    feature_effects = []
    for feature in ("confidence", "rule_score", "relative_volume", "rsi"):
        binned = defaultdict(list)
        for row in enriched: binned[feature_bin(feature, row.get(feature))].append(row)
        feature_effects.extend({"feature": feature, "bin": label, **summarize(items), **_mirror_summary(items),
                                "large_winner_rate": sum(item["outcome_bucket"] == "LARGE WINNER" for item in items) / len(items) * 100}
                               for label, items in sorted(binned.items()))
    by_outcome = _group(enriched, "outcome_bucket")
    translation = _group([row for row in enriched if row["option_translation_bucket"] != "MIRROR UNAVAILABLE"], "option_translation_bucket")
    by_session, by_regime = _group(enriched, "session_bucket"), _group(enriched, "market_regime")
    by_symbol = _group(enriched, "symbol")
    by_sector, by_direction = _group(enriched, "sector"), _group(enriched, "direction")
    largest_symbol = max(by_symbol, key=lambda group: group["n"], default=None)
    concentration = largest_symbol["n"] / len(enriched) * 100 if largest_symbol and enriched else None
    patterns = _pattern_rows(enriched)
    reliable_effects = [row for row in feature_effects if row["n"] >= MIN_PATTERN_SAMPLE and row["bin"] != "MISSING"]
    reliable_sessions = [row for row in by_session if row["n"] >= MIN_PATTERN_SAMPLE]
    insights = {
        "strongest_factor": max(reliable_effects, key=lambda row: row["expectancy"], default=None),
        "weakest_factor": min(reliable_effects, key=lambda row: row["expectancy"], default=None),
        "weakest_session": min(reliable_sessions, key=lambda row: row["expectancy"], default=None),
    }
    return {"rows": enriched, "thresholds": thresholds, "coverage": coverage,
            "feature_status": FEATURE_DEFINITIONS, "exclusions": exclusions,
            "outcome_distribution": by_outcome, "large_winner_dna": by_outcome,
            "feature_effects": feature_effects, "option_translation": translation,
            "patterns": patterns, "session_effects": by_session, "regime_effects": by_regime,
            "symbol_effects": by_symbol, "sector_effects": by_sector,
            "direction_effects": by_direction, "symbol_concentration": concentration,
            "insights": insights,
            "symbol_concentration_warning": concentration is not None and concentration > 50}
