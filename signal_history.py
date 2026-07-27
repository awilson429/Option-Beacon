"""Serializable trade-outcome records for generated Option Beacon signals."""

from __future__ import annotations

import hashlib
import json
import logging
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4


DEFAULT_HISTORY_FILE = "signal_history.jsonl"
LOGGER = logging.getLogger(__name__)


@dataclass
class TradeOutcome:
    """A generated trade signal and its eventual observed outcome."""

    trade_id: str
    timestamp: datetime
    symbol: str
    direction: str
    setup: str
    confidence: float
    entry: Optional[float]
    stop: Optional[float]
    target_1: Optional[float]
    target_2: Optional[float]
    target_3: Optional[float]
    entry_time: Optional[datetime]
    exit_time: Optional[datetime]
    exit_reason: Optional[str]
    max_favorable_excursion: Optional[float]
    max_adverse_excursion: Optional[float]
    realized_return: Optional[float]
    hold_minutes: Optional[float]


def create_trade_record(
    *,
    symbol: str,
    direction: str,
    setup: str,
    confidence: float,
    entry: Optional[float],
    stop: Optional[float],
    target_1: Optional[float],
    target_2: Optional[float],
    target_3: Optional[float] = None,
    timestamp: Optional[datetime] = None,
    entry_time: Optional[datetime] = None,
    trade_id: Optional[str] = None,
) -> TradeOutcome:
    """Create an open outcome record without evaluating or changing the signal."""
    created_at = timestamp or datetime.now(timezone.utc)
    return TradeOutcome(
        trade_id=trade_id or uuid4().hex,
        timestamp=created_at,
        symbol=symbol,
        direction=direction,
        setup=setup,
        confidence=confidence,
        entry=entry,
        stop=stop,
        target_1=target_1,
        target_2=target_2,
        target_3=target_3,
        entry_time=entry_time or created_at,
        exit_time=None,
        exit_reason=None,
        max_favorable_excursion=None,
        max_adverse_excursion=None,
        realized_return=None,
        hold_minutes=None,
    )


def serialize_trade_outcome(record: TradeOutcome) -> str:
    """Serialize a trade outcome to a JSON object."""
    payload = asdict(record)
    for field_name in ("timestamp", "entry_time", "exit_time"):
        value = payload[field_name]
        payload[field_name] = value.isoformat() if value is not None else None
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def deserialize_trade_outcome(payload: str) -> TradeOutcome:
    """Deserialize a JSON object into a trade outcome."""
    values = json.loads(payload)
    for field_name in ("timestamp", "entry_time", "exit_time"):
        value = values.get(field_name)
        values[field_name] = datetime.fromisoformat(value) if value else None
    return TradeOutcome(**values)


def append_trade_outcome(
    record: TradeOutcome,
    file_name: str | Path = DEFAULT_HISTORY_FILE,
) -> Path:
    """Append one trade outcome as a JSON Lines record."""
    path = Path(file_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as history_file:
        history_file.write(serialize_trade_outcome(record))
        history_file.write("\n")
    return path


def _valid_price(value) -> Optional[float]:
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return price if math.isfinite(price) and price > 0 else None


def _signal_timestamp(result: dict) -> datetime:
    value = result.get("last_candle_at") or result.get("timestamp")
    if isinstance(value, datetime):
        timestamp = value
    elif value:
        timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    else:
        timestamp = datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp


def scanner_result_to_trade_outcome(
    result: dict,
    trade_plan: Optional[dict] = None,
) -> Optional[TradeOutcome]:
    """Convert one eligible completed scanner result into an open outcome."""
    result = result or {}
    plan = trade_plan if trade_plan is not None else result.get("trade_plan")
    if not plan:
        return None

    direction = plan.get("direction") or result.get("bias")
    if direction not in {"Bullish", "Bearish"}:
        return None

    timing = str(
        result.get("timing_label") or result.get("entry_timing") or ""
    ).upper()
    stage = str(result.get("setup_stage") or "").upper()
    if timing in {"INVALID", "EXTENDED", "SETUP INVALIDATED", "DO NOT CHASE"}:
        return None
    if stage in {"INVALID", "FAILED", "EXTENDED"}:
        return None

    entry = _valid_price(plan.get("trigger_price"))
    if entry is None:
        entry = _valid_price(plan.get("entry_price"))
    if entry is None:
        entry = _valid_price(plan.get("entry_zone_low"))
    if entry is None:
        entry = _valid_price(result.get("entry"))
    if entry is None:
        return None

    timestamp = _signal_timestamp(result)
    bucket = timestamp.replace(
        minute=(timestamp.minute // 5) * 5,
        second=0,
        microsecond=0,
    )
    setup = str(plan.get("setup_type") or result.get("setup") or "Directional setup")
    identity = {
        "symbol": str(result.get("symbol") or "").upper(),
        "direction": direction,
        "setup": setup,
        "trigger_price": entry,
        "setup_bucket": bucket.isoformat(),
    }
    trade_id = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    return create_trade_record(
        trade_id=trade_id,
        timestamp=timestamp,
        symbol=identity["symbol"],
        direction=direction,
        setup=setup,
        confidence=float(result.get("confidence") or 0),
        entry=entry,
        stop=_valid_price(plan.get("technical_stop")),
        target_1=_valid_price(plan.get("target_1")),
        target_2=_valid_price(plan.get("target_2")),
        target_3=_valid_price(plan.get("target_3")),
    )


def append_trade_outcome_once(
    record: TradeOutcome,
    file_name: str | Path = DEFAULT_HISTORY_FILE,
) -> bool:
    """Append a record unless its deterministic identity is already present."""
    path = Path(file_name)
    if path.exists():
        with path.open("r", encoding="utf-8") as history_file:
            for line in history_file:
                if not line.strip():
                    continue
                if deserialize_trade_outcome(line).trade_id == record.trade_id:
                    return False
    append_trade_outcome(record, path)
    return True


def record_scanner_result(
    result: dict,
    file_name: str | Path = DEFAULT_HISTORY_FILE,
) -> bool:
    """Record an eligible result without allowing history I/O to stop scanning."""
    try:
        record = scanner_result_to_trade_outcome(result)
        return append_trade_outcome_once(record, file_name) if record else False
    except Exception:
        LOGGER.exception(
            "Could not record signal outcome for %s",
            (result or {}).get("symbol", "unknown"),
        )
        return False
