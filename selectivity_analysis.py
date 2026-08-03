"""Shadow-only, point-in-time trade selectivity analysis."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean, median


MODEL_VERSION = "selectivity-empirical-v1"
MIN_FACTOR_SAMPLE = 5
MFE_WORKED_THRESHOLD = 0.50
MFE_INCONCLUSIVE_THRESHOLD = 0.25
MAE_BAD_ENTRY_THRESHOLD = -0.50


def build_analysis_rows(snapshot_rows, outcome_rows):
    """Join immutable entry snapshots to completed outcomes without mutation."""
    snapshots = {
        (row.get("snapshot") or row).get("opportunity_id"): row.get("snapshot") or row
        for row in snapshot_rows
    }
    rows, exclusions = [], defaultdict(int)
    for wrapped in outcome_rows:
        outcome = wrapped.get("outcome") or wrapped
        opportunity_id = outcome.get("opportunity_id")
        snapshot = snapshots.get(opportunity_id)
        if snapshot is None:
            exclusions["missing_entry_snapshot"] += 1
            continue
        if (
            not outcome.get("entered")
            or outcome.get("never_entered")
            or not outcome.get("exit_timestamp")
            or _number(outcome.get("realized_return")) is None
        ):
            exclusions["incomplete_outcome"] += 1
            continue
        features = snapshot.get("features") or {}
        scoring = snapshot.get("scoring") or {}
        regime = snapshot.get("market_regime") or {}
        sector = snapshot.get("sector_context") or {}
        realized = _number(outcome.get("realized_return"))
        mfe = _number(outcome.get("maximum_favorable_excursion"))
        mae = _number(outcome.get("maximum_adverse_excursion"))
        entry_timestamp = snapshot.get("entry_timestamp") or outcome.get("entry_timestamp")
        row = {
            "opportunity_id": opportunity_id,
            "entry_timestamp": entry_timestamp,
            "exit_timestamp": outcome.get("exit_timestamp"),
            "symbol": snapshot.get("symbol"),
            "setup": snapshot.get("setup_type"),
            "direction": snapshot.get("direction"),
            "rule_score": _number(scoring.get("quality") or scoring.get("confidence")),
            "confidence": _number(scoring.get("confidence")),
            "session_segment": snapshot.get("session_segment"),
            "day_of_week": _day_of_week(entry_timestamp),
            "market_regime": regime.get("regime"),
            "market_alignment": _market_alignment(regime, snapshot.get("direction")),
            "sector": sector.get("sector"),
            "sector_alignment": sector.get("alignment_status"),
            "sector_rank": sector.get("sector_rank"),
            "relative_volume": _number(features.get("relative_volume") or features.get("volume_ratio")),
            "rsi": _number(features.get("rsi")),
            "vwap_relationship": features.get("vwap_relationship"),
            "vwap_distance": _number(features.get("distance_from_vwap")),
            "trend_alignment": features.get("trend_alignment") or features.get("ema_alignment"),
            "ema9": _number(features.get("ema9")),
            "ema21": _number(features.get("ema21")),
            "ema9_slope": _number(features.get("ema9_slope")),
            "breakout_distance": _number(features.get("breakout_distance")),
            "candle_body_percent": _number(features.get("candle_body_percent")),
            "atr": _number(features.get("atr")),
            "volatility": _number(features.get("volatility")),
            "entry_price": _number(outcome.get("entry_price")),
            "realized_return": realized,
            "realized_pnl_dollars": _number(outcome.get("realized_pnl_dollars")),
            "winner": realized > 0,
            "mfe": mfe,
            "mae": mae,
            "mfe_dollars": _number(outcome.get("mfe_dollars")),
            "mae_dollars": _number(outcome.get("mae_dollars")),
            "hold_minutes": _number(outcome.get("duration_minutes")),
            "exit_reason": outcome.get("exit_reason"),
            "target_hit": bool(outcome.get("target_1_reached")),
            "stop_hit": bool(outcome.get("stop_reached")),
            "eod_exit": bool(outcome.get("end_of_day_exit")),
            "max_hold_exit": bool(outcome.get("maximum_hold_exit")),
            "mfe_over_0_25": mfe >= .25 if mfe is not None else None,
            "mfe_over_0_50": mfe >= .50 if mfe is not None else None,
            "mfe_over_1_00": mfe >= 1.0 if mfe is not None else None,
            "profitable_before_loss": bool(mfe > 0 and realized < 0) if mfe is not None else None,
            "return_from_peak": mfe - realized if mfe is not None else None,
            "time_to_mfe_minutes": _number(outcome.get("time_to_mfe_minutes")),
            "time_to_mae_minutes": _number(outcome.get("time_to_mae_minutes")),
        }
        row["diagnosis"] = classify_entry_exit(row)
        rows.append(row)
    rows.sort(key=lambda row: _timestamp(row["entry_timestamp"]))
    return rows, dict(exclusions)


def classify_entry_exit(row):
    mfe, mae, realized = (_number(row.get(key)) for key in ("mfe", "mae", "realized_return"))
    if mfe is None or mae is None or realized is None:
        return "INSUFFICIENT DATA"
    if realized > 0 and mfe >= MFE_WORKED_THRESHOLD:
        return "GOOD TRADE"
    if realized <= 0 and mfe >= MFE_WORKED_THRESHOLD:
        return "GOOD ENTRY / BAD EXIT"
    if mfe < MFE_INCONCLUSIVE_THRESHOLD and mae <= MAE_BAD_ENTRY_THRESHOLD:
        return "BAD ENTRY"
    return "CHOP / INCONCLUSIVE"


def chronological_split(rows, validation_fraction=.30):
    ordered = sorted(rows, key=lambda row: _timestamp(row.get("exit_timestamp")))
    if len(ordered) < 2:
        return ordered, []
    validation_count = max(1, int(math.ceil(len(ordered) * validation_fraction)))
    return ordered[:-validation_count], ordered[-validation_count:]


def fit_quality_model(training_rows, *, minimum_factor_sample=MIN_FACTOR_SAMPLE):
    baseline = mean(row["realized_return"] for row in training_rows) if training_rows else 0.0
    effects = {}
    for name, predicate in _factor_definitions():
        selected = [row["realized_return"] for row in training_rows if predicate(row)]
        if len(selected) >= minimum_factor_sample:
            effects[name] = {
                "effect": mean(selected) - baseline,
                "sample_size": len(selected),
            }
    return {
        "model_version": MODEL_VERSION,
        "shadow_only": True,
        "training_count": len(training_rows),
        "baseline_return": baseline,
        "factor_effects": effects,
    }


def score_quality(row, model):
    contributions = []
    for name, predicate in _factor_definitions():
        effect = (model.get("factor_effects") or {}).get(name)
        if effect and predicate(row):
            contributions.append((name, effect["effect"]))
    raw = sum(value for _, value in contributions)
    score = max(0.0, min(100.0, 50.0 + raw * 20.0))
    return {
        "selectivity_score": round(score, 2),
        "model_version": model.get("model_version", MODEL_VERSION),
        "positive_factors": [name for name, value in contributions if value > 0],
        "negative_factors": [name for name, value in contributions if value < 0],
        "shadow_only": True,
        "calibrated_probability": None,
    }


def assign_percentile_tiers(rows):
    ranked = sorted(rows, key=lambda row: (-row["selectivity_score"], row["opportunity_id"]))
    count = len(ranked)
    for index, row in enumerate(ranked):
        rank = index + 1
        top_10 = max(1, math.ceil(count * .10))
        top_25 = max(1, math.ceil(count * .25))
        top_50 = max(1, math.ceil(count * .50))
        top_75 = max(1, math.ceil(count * .75))
        row["percentile_tier"] = "TOP 10%" if rank <= top_10 else "TOP 25%" if rank <= top_25 else "TOP 50%" if rank <= top_50 else "TOP 75%" if rank <= top_75 else "BOTTOM 25%"
        row["selectivity_tier"] = "ELITE" if rank <= top_25 else "HIGH CONVICTION" if rank <= top_50 else "SELECTIVE" if rank <= top_75 else "BASELINE ONLY"
    return ranked


def summarize_rows(rows):
    returns = [_number(row.get("realized_return")) for row in rows]
    returns = [value for value in returns if value is not None]
    wins, losses = [x for x in returns if x > 0], [x for x in returns if x < 0]
    decided = len(wins) + len(losses)
    return {
        "trade_count": len(rows), "wins": len(wins), "losses": len(losses),
        "win_rate": len(wins) / decided * 100 if decided else None,
        "average_return": mean(returns) if returns else None,
        "median_return": median(returns) if returns else None,
        "expectancy": mean(returns) if returns else None,
        "average_winner": mean(wins) if wins else None,
        "average_loser": mean(losses) if losses else None,
        "profit_factor": sum(wins) / abs(sum(losses)) if losses else math.inf if wins else None,
        "average_mfe": _average(row.get("mfe") for row in rows),
        "average_mae": _average(row.get("mae") for row in rows),
        "average_hold": _average(row.get("hold_minutes") for row in rows),
        "target_exit_rate": _rate(rows, "target_hit"),
        "stop_out_rate": _rate(rows, "stop_hit"),
        "eod_exit_rate": _rate(rows, "eod_exit"),
        "max_hold_rate": _rate(rows, "max_hold_exit"),
    }


def tier_comparison(rows):
    baseline = summarize_rows(rows)
    definitions = (
        ("BASELINE", lambda row: True),
        ("SELECTIVE · TOP 75%", lambda row: row.get("percentile_tier") != "BOTTOM 25%"),
        ("HIGH CONVICTION · TOP 50%", lambda row: row.get("selectivity_tier") in {"ELITE", "HIGH CONVICTION"}),
        ("ELITE · TOP 25%", lambda row: row.get("selectivity_tier") == "ELITE"),
        ("TOP 10%", lambda row: row.get("percentile_tier") == "TOP 10%"),
    )
    results = []
    for name, predicate in definitions:
        selected = [row for row in rows if predicate(row)]
        summary = summarize_rows(selected)
        summary.update({
            "tier": name,
            "percent_retained": len(selected) / len(rows) * 100 if rows else 0,
            "trade_reduction": (1 - len(selected) / len(rows)) * 100 if rows else 0,
            "win_rate_lift": (
                summary["win_rate"] - baseline["win_rate"]
                if summary["win_rate"] is not None and baseline["win_rate"] is not None else None
            ),
        })
        results.append(summary)
    return results


def feature_bins(rows, feature, edges, *, minimum_sample=MIN_FACTOR_SAMPLE):
    groups = defaultdict(list)
    for row in rows:
        value = _number(row.get(feature))
        if value is None:
            groups["MISSING"].append(row)
            continue
        label = next((f"{low:g}–{high:g}" for low, high in zip(edges, edges[1:]) if low <= value < high), "OUTSIDE")
        groups[label].append(row)
    return [{"bin": label, "reliable": len(items) >= minimum_sample, **summarize_rows(items)} for label, items in sorted(groups.items())]


def sample_confidence(count):
    if count < 20: return "EXPLORATORY ONLY"
    if count < 50: return "DESCRIPTIVE"
    if count < 100: return "PRELIMINARY"
    return "STRONGER EVIDENCE"


def analyze_selectivity(snapshot_rows, outcome_rows):
    rows, exclusions = build_analysis_rows(snapshot_rows, outcome_rows)
    train, validation = chronological_split(rows)
    model = fit_quality_model(train)
    scored = []
    for row in rows:
        scored.append({**row, **score_quality(row, model)})
    assign_percentile_tiers(scored)
    validation_ids = {row["opportunity_id"] for row in validation}
    validation_scored = [dict(row) for row in scored if row["opportunity_id"] in validation_ids]
    assign_percentile_tiers(validation_scored)
    diagnoses = defaultdict(int)
    for row in scored: diagnoses[row["diagnosis"]] += 1
    return {
        "rows": sorted(scored, key=lambda row: _timestamp(row["entry_timestamp"]), reverse=True),
        "overview": summarize_rows(scored),
        "tiers": tier_comparison(validation_scored),
        "all_history_tiers": tier_comparison(scored),
        "validation_overview": summarize_rows(validation_scored),
        "diagnoses": dict(diagnoses),
        "sample_confidence": sample_confidence(len(scored)),
        "training_count": len(train), "validation_count": len(validation),
        "model": model, "exclusions": exclusions,
        "methodology": "CHRONOLOGICAL SHADOW DESCRIPTIVE",
    }


def filter_trade_review(rows, **filters):
    selected = list(rows)
    for key, value in filters.items():
        if value in (None, "ALL", ""):
            continue
        if key == "result":
            selected = [row for row in selected if ("WINNER" if row["winner"] else "LOSER") == value]
        else:
            selected = [row for row in selected if str(row.get(key)) == str(value)]
    return selected


def _factor_definitions():
    return (
        ("Rule score ≥ 90", lambda row: (_number(row.get("rule_score")) or -math.inf) >= 90),
        ("Relative volume ≥ 1.5", lambda row: (_number(row.get("relative_volume")) or -math.inf) >= 1.5),
        ("Balanced RSI 45–70", lambda row: (value := _number(row.get("rsi"))) is not None and 45 <= value <= 70),
        ("Market aligned", lambda row: row.get("market_alignment") is True),
        ("Sector aligned", lambda row: str(row.get("sector_alignment") or "").upper() in {"ALIGNED", "OUTPERFORMING"}),
        ("VWAP direction aligned", lambda row: _text_aligned(row.get("vwap_relationship"), row.get("direction"))),
        ("Trend aligned", lambda row: _directional_alignment(row.get("trend_alignment"), row.get("direction"))),
        ("Late session", lambda row: row.get("session_segment") == "CLOSING_PERIOD"),
    )


def _market_alignment(regime, direction):
    name = str(regime.get("regime") or "").upper()
    if not name or name == "INSUFFICIENT_DATA": return None
    if direction == "Bullish": return "BULLISH" in name
    if direction == "Bearish": return "BEARISH" in name
    return None


def _text_aligned(value, direction):
    text = str(value or "").upper()
    return (direction == "Bullish" and ("ABOVE" in text or "BULL" in text)) or (direction == "Bearish" and ("BELOW" in text or "BEAR" in text))


def _directional_alignment(value, direction):
    text = str(value or "").upper()
    return "ALIGNED" in text or (direction == "Bullish" and "BULL" in text) or (direction == "Bearish" and "BEAR" in text)


def _day_of_week(value):
    try: return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%A")
    except Exception: return None


def _timestamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None: parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except Exception: return float("-inf")


def _number(value):
    try: number = float(value)
    except (TypeError, ValueError): return None
    return number if math.isfinite(number) else None


def _average(values):
    available = [number for value in values if (number := _number(value)) is not None]
    return mean(available) if available else None


def _rate(rows, key):
    return sum(bool(row.get(key)) for row in rows) / len(rows) * 100 if rows else None
