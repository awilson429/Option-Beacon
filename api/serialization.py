"""Strict JSON normalization for API projection values."""
from __future__ import annotations

import math
from datetime import date, datetime
from decimal import Decimal
from enum import Enum


def normalize_json_value(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if type(value).__name__ in {"NaTType", "NAType"}:
        return None
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Decimal):
        converted = float(value)
        return converted if math.isfinite(converted) else None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return normalize_json_value(value.value)
    if isinstance(value, dict):
        return {str(key): normalize_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [normalize_json_value(item) for item in value]
    to_datetime = getattr(value, "to_pydatetime", None)
    if callable(to_datetime):
        converted = to_datetime()
        return None if converted is value else normalize_json_value(converted)
    scalar = getattr(value, "item", None)
    if callable(scalar):
        try:
            converted = scalar()
            return None if converted is value else normalize_json_value(converted)
        except (TypeError, ValueError):
            pass
    return value
