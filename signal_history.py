"""Serializable trade-outcome records for generated Option Beacon signals."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4


DEFAULT_HISTORY_FILE = "signal_history.jsonl"


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
