"""Transparent empirical confidence calibration for shadow evaluation only."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from statistics import mean


DEFAULT_MINIMUM_TRAINING_SAMPLES = 50
DEFAULT_PRIOR_STRENGTH = 20.0
SHADOW_MODEL_VERSION = "empirical-shrinkage-v1"


def time_based_split(records, *, validation_fraction=0.2):
    ordered = sorted(records, key=lambda row: str(row.get("exit_timestamp") or row.get("generated_timestamp") or ""))
    if not ordered: return [], []
    split = max(1, min(len(ordered), int(len(ordered) * (1 - validation_fraction))))
    return ordered[:split], ordered[split:]


def train_shadow_calibrator(records, *, minimum_samples=DEFAULT_MINIMUM_TRAINING_SAMPLES, prior_strength=DEFAULT_PRIOR_STRENGTH, trained_at=None):
    usable = [row for row in records if _number(row.get("rule_score")) is not None and _number(row.get("realized_return")) is not None]
    train, validation = time_based_split(usable)
    if len(train) < minimum_samples:
        return {"available": False, "shadow_only": True, "model_version": SHADOW_MODEL_VERSION, "sample_size": len(train), "fallback_reason": "INSUFFICIENT_HISTORY", "minimum_samples": minimum_samples, "promotion_status": "SHADOW_REQUIRES_HUMAN_APPROVAL"}
    base = mean(1.0 if _number(row["realized_return"]) > 0 else 0.0 for row in train)
    buckets = {}
    for row in train:
        name = score_bucket(row["rule_score"]); item = buckets.setdefault(name, {"wins": 0, "total": 0})
        item["total"] += 1; item["wins"] += _number(row["realized_return"]) > 0
    for item in buckets.values():
        item["estimate"] = (item["wins"] + prior_strength * base) / (item["total"] + prior_strength)
    predictions = [predict_shadow_probability({"available": True, "buckets": buckets, "base_rate": base}, row["rule_score"])["probability"] for row in validation]
    actual = [1.0 if _number(row["realized_return"]) > 0 else 0.0 for row in validation]
    brier = mean((p-y)**2 for p,y in zip(predictions, actual)) if actual else None
    return {"available": True, "shadow_only": True, "model_version": SHADOW_MODEL_VERSION,
            "trained_at": (trained_at or datetime.now(timezone.utc)).isoformat(), "sample_size": len(train),
            "validation_sample_size": len(validation), "data_window": {"start": str(train[0].get("exit_timestamp")), "end": str(train[-1].get("exit_timestamp"))},
            "feature_list": ["rule_score"], "prior_strength": prior_strength, "base_rate": base, "buckets": buckets,
            "validation_metrics": {"brier_score": brier, "class_balance": base, "calibration_curve": _curve(predictions, actual)},
            "promotion_status": "SHADOW_REQUIRES_HUMAN_APPROVAL"}


def predict_shadow_probability(model, rule_score):
    if not model or not model.get("available"):
        return {"probability": None, "probability_band": "INSUFFICIENT_HISTORY", "fallback_reason": (model or {}).get("fallback_reason", "MODEL_UNAVAILABLE"), "shadow_only": True, "model_version": (model or {}).get("model_version", SHADOW_MODEL_VERSION), "sample_size": (model or {}).get("sample_size", 0), "top_positive_contributors": [], "top_negative_contributors": []}
    bucket = score_bucket(rule_score); item = model.get("buckets", {}).get(bucket)
    if not item: probability = model.get("base_rate"); reason = "BUCKET_UNAVAILABLE_BASE_RATE_USED"
    else: probability = item["estimate"]; reason = None
    return {"probability": probability, "probability_band": _band(probability), "fallback_reason": reason,
            "shadow_only": True, "model_version": model.get("model_version", SHADOW_MODEL_VERSION), "sample_size": item["total"] if item else model.get("sample_size", 0),
            "top_positive_contributors": [f"RULE_SCORE_BUCKET_{bucket}"] if probability >= model.get("base_rate", 0) else [],
            "top_negative_contributors": [f"RULE_SCORE_BUCKET_{bucket}"] if probability < model.get("base_rate", 0) else []}


def score_bucket(value):
    number = _number(value)
    if number is None: return "UNKNOWN"
    lower = max(0, min(90, int(number // 10) * 10)); return f"{lower}-{lower + 9 if lower < 90 else 100}"


def _curve(predictions, actual):
    groups = {}
    for p,y in zip(predictions,actual):
        key = int(p*10)/10; groups.setdefault(key, []).append(y)
    return [{"predicted_bucket": key, "observed_win_rate": mean(values), "sample_size": len(values)} for key, values in sorted(groups.items())]


def _band(p):
    if p is None: return "UNAVAILABLE"
    if p < .45: return "LOW"
    if p < .60: return "MIXED"
    if p < .75: return "POSITIVE"
    return "HIGH"


def _number(value):
    try: number=float(value)
    except (TypeError,ValueError): return None
    return number if math.isfinite(number) else None
