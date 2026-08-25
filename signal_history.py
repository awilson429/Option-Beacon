"""Serializable trade-outcome records for generated Option Beacon signals."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4


DEFAULT_HISTORY_FILE = "signal_history.jsonl"
DEFAULT_MAX_CANDIDATE_AGE_MINUTES = 60
DEFAULT_MAX_ENTERED_AGE_MINUTES = 240
DEFAULT_MIN_ENTRY_CONFIDENCE = 65
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


def load_trade_outcomes(
    file_name: str | Path = DEFAULT_HISTORY_FILE,
) -> list[TradeOutcome]:
    """Load valid history records, logging and skipping malformed lines."""
    path = Path(file_name)
    if not path.exists():
        return []

    records = []
    with path.open("r", encoding="utf-8") as history_file:
        for line_number, line in enumerate(history_file, start=1):
            if not line.strip():
                continue
            try:
                records.append(deserialize_trade_outcome(line))
            except Exception:
                LOGGER.exception(
                    "Could not load signal outcome at %s:%s",
                    path,
                    line_number,
                )
    return records


def rewrite_trade_outcomes(
    records: list[TradeOutcome],
    file_name: str | Path = DEFAULT_HISTORY_FILE,
) -> Path:
    """Atomically replace the history file with the supplied records."""
    path = Path(file_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as history_file:
            temporary_path = Path(history_file.name)
            for record in records:
                history_file.write(serialize_trade_outcome(record))
                history_file.write("\n")
            history_file.flush()
            os.fsync(history_file.fileno())
        os.replace(temporary_path, path)
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise
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


def _current_timestamp(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        timestamp = value
    else:
        timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp


def _directional_return(direction: str, entry: float, price: float) -> float:
    change = ((price - entry) / entry) * 100
    return change if direction == "Bullish" else -change


def entry_confidence_eligible(
    record: TradeOutcome,
    minimum_entry_confidence: float = DEFAULT_MIN_ENTRY_CONFIDENCE,
) -> bool:
    """Return whether an unentered record clears the finite confidence gate."""
    try:
        confidence = float(record.confidence)
        threshold = float(minimum_entry_confidence)
    except (TypeError, ValueError):
        return False
    return (
        math.isfinite(confidence)
        and math.isfinite(threshold)
        and confidence >= threshold
    )


def expire_trade_outcome(
    record: TradeOutcome,
    current_price: float,
    current_timestamp: datetime | str,
    max_candidate_age_minutes: float = DEFAULT_MAX_CANDIDATE_AGE_MINUTES,
    max_entered_age_minutes: float = DEFAULT_MAX_ENTERED_AGE_MINUTES,
) -> TradeOutcome:
    """Close an untriggered candidate or stale entered trade at its age limit."""
    if record.exit_time is not None:
        return record

    checked_at = _current_timestamp(current_timestamp)
    if record.entry_time is None:
        signal_time = _current_timestamp(record.timestamp)
        elapsed_minutes = max(
            0.0,
            (checked_at - signal_time).total_seconds() / 60,
        )
        if elapsed_minutes >= max_candidate_age_minutes:
            record.exit_time = checked_at
            record.exit_reason = "NEVER_TRIGGERED"
            record.realized_return = None
            record.max_favorable_excursion = None
            record.max_adverse_excursion = None
            record.hold_minutes = elapsed_minutes
        return record

    entry = _valid_price(record.entry)
    price = _valid_price(current_price)
    entry_time = _current_timestamp(record.entry_time)
    elapsed_minutes = max(
        0.0,
        (checked_at - entry_time).total_seconds() / 60,
    )
    if (
        elapsed_minutes >= max_entered_age_minutes
        and entry is not None
        and price is not None
    ):
        record.exit_time = checked_at
        record.exit_reason = "TIME_EXIT"
        record.realized_return = _directional_return(
            record.direction,
            entry,
            price,
        )
    return record


def update_trade_outcome(
    record: TradeOutcome,
    current_price: float,
    current_timestamp: datetime | str,
    minimum_entry_confidence: float = DEFAULT_MIN_ENTRY_CONFIDENCE,
) -> TradeOutcome:
    """Advance one candidate or entered outcome using the latest market price."""
    if record.exit_time is not None:
        return record

    price = _valid_price(current_price)
    entry = _valid_price(record.entry)
    if price is None or entry is None:
        return record

    checked_at = _current_timestamp(current_timestamp)
    if record.entry_time is None:
        entry_reached = (
            price >= entry if record.direction == "Bullish" else price <= entry
        )
        if entry_reached and entry_confidence_eligible(
            record,
            minimum_entry_confidence,
        ):
            record.entry_time = checked_at
        return record

    entry_time = _current_timestamp(record.entry_time)
    current_return = _directional_return(record.direction, entry, price)
    record.max_favorable_excursion = max(
        0.0,
        record.max_favorable_excursion or 0.0,
        current_return,
    )
    record.max_adverse_excursion = min(
        0.0,
        record.max_adverse_excursion or 0.0,
        current_return,
    )
    record.hold_minutes = max(
        0.0,
        (checked_at - entry_time).total_seconds() / 60,
    )

    exit_reason = None
    exit_level = None
    stop = _valid_price(record.stop)
    if stop is not None and (
        (record.direction == "Bullish" and price <= stop)
        or (record.direction == "Bearish" and price >= stop)
    ):
        exit_reason = "STOP"
        exit_level = stop
    else:
        for reason, target in (
            ("TARGET_3", record.target_3),
            ("TARGET_2", record.target_2),
            ("TARGET_1", record.target_1),
        ):
            target_price = _valid_price(target)
            if target_price is not None and (
                (record.direction == "Bullish" and price >= target_price)
                or (record.direction == "Bearish" and price <= target_price)
            ):
                exit_reason = reason
                exit_level = target_price
                break

    if exit_reason is not None:
        record.exit_time = checked_at
        record.exit_reason = exit_reason
        record.realized_return = _directional_return(
            record.direction,
            entry,
            exit_level,
        )
    return record


def close_trade_outcome_end_of_day(
    record: TradeOutcome,
    current_price: float,
    current_timestamp: datetime | str,
) -> TradeOutcome:
    """Close one entered intraday outcome at the latest sampled underlying price."""
    if record.entry_time is None or record.exit_time is not None:
        return record
    price = _valid_price(current_price)
    entry = _valid_price(record.entry)
    if price is None or entry is None:
        return record
    checked_at = _current_timestamp(current_timestamp)
    entry_time = _current_timestamp(record.entry_time)
    current_return = _directional_return(record.direction, entry, price)
    record.max_favorable_excursion = max(
        0.0,
        record.max_favorable_excursion or 0.0,
        current_return,
    )
    record.max_adverse_excursion = min(
        0.0,
        record.max_adverse_excursion or 0.0,
        current_return,
    )
    record.hold_minutes = max(
        0.0,
        (checked_at - entry_time).total_seconds() / 60,
    )
    record.exit_time = checked_at
    record.exit_reason = "END_OF_DAY"
    record.realized_return = current_return
    return record


def update_trade_outcomes_from_result(
    result: dict,
    file_name: str | Path = DEFAULT_HISTORY_FILE,
    max_candidate_age_minutes: float = DEFAULT_MAX_CANDIDATE_AGE_MINUTES,
    max_entered_age_minutes: float = DEFAULT_MAX_ENTERED_AGE_MINUTES,
    minimum_entry_confidence: float = DEFAULT_MIN_ENTRY_CONFIDENCE,
) -> int:
    """Update matching history records without allowing failures to stop scanning."""
    try:
        path = Path(file_name)
        if not path.exists():
            return 0

        current_price = _valid_price((result or {}).get("price"))
        symbol = str((result or {}).get("symbol") or "").upper()
        if current_price is None or not symbol:
            return 0

        current_timestamp = _signal_timestamp(result)
        records = load_trade_outcomes(path)
        updated_count = 0
        for record in records:
            if record.symbol.upper() != symbol or record.exit_time is not None:
                continue
            before = serialize_trade_outcome(record)
            expire_trade_outcome(
                record,
                current_price,
                current_timestamp,
                max_candidate_age_minutes=max_candidate_age_minutes,
                max_entered_age_minutes=max_entered_age_minutes,
            )
            if record.exit_time is None:
                update_trade_outcome(
                    record,
                    current_price,
                    current_timestamp,
                    minimum_entry_confidence=minimum_entry_confidence,
                )
            if serialize_trade_outcome(record) != before:
                updated_count += 1

        if updated_count:
            rewrite_trade_outcomes(records, path)
        return updated_count
    except Exception:
        LOGGER.exception(
            "Could not update signal outcomes for %s",
            (result or {}).get("symbol", "unknown"),
        )
        return 0


def scanner_result_to_trade_outcome(
    result: dict,
    trade_plan: Optional[dict] = None,
) -> Optional[TradeOutcome]:
    """Convert one eligible completed scanner result into an open outcome."""
    record, _ = scanner_result_decision(result, trade_plan=trade_plan)
    return record


def scanner_result_decision(
    result: dict,
    trade_plan: Optional[dict] = None,
) -> tuple[Optional[TradeOutcome], dict]:
    """Return the unchanged candidate result plus its exact conversion disposition.

    This is an observational wrapper around the pre-existing qualification
    branches.  Callers must not use the disposition to change strategy or
    execution behavior.
    """
    result = result or {}
    signal = str(result.get("signal") or "").upper()
    if signal == "MARKET CLOSED / WAIT":
        return None, {
            "qualification_state": "SESSION_BLOCKED",
            "reason_code": "MARKET_CLOSED_WAIT",
            "explanation": "The existing scanner result blocked evaluation outside its trade session.",
        }
    plan = trade_plan if trade_plan is not None else result.get("trade_plan")
    if not plan:
        return None, {
            "qualification_state": "NO_SETUP",
            "reason_code": "NO_TRADE_PLAN",
            "explanation": "The existing scanner result did not produce a directional trade plan.",
        }

    direction = plan.get("direction") or result.get("bias")
    if direction not in {"Bullish", "Bearish"}:
        return None, {
            "qualification_state": "NO_SETUP",
            "reason_code": "NO_DIRECTIONAL_SETUP",
            "explanation": "The existing scanner result had no Bullish or Bearish direction.",
        }

    timing = str(
        result.get("timing_label") or result.get("entry_timing") or ""
    ).upper()
    stage = str(result.get("setup_stage") or "").upper()
    if timing in {"INVALID", "EXTENDED", "SETUP INVALIDATED", "DO NOT CHASE"}:
        return None, {
            "qualification_state": "REJECTED",
            "reason_code": "TIMING_" + (timing.replace(" ", "_") or "INVALID"),
            "explanation": str(result.get("entry_timing_reason") or result.get("what_next_reason")
                               or f"The existing entry timing state was {timing}."),
        }
    if stage in {"INVALID", "FAILED", "EXTENDED"}:
        return None, {
            "qualification_state": "REJECTED",
            "reason_code": "SETUP_STAGE_" + stage,
            "explanation": str(result.get("setup_stage_reason")
                               or f"The existing setup stage was {stage}."),
        }

    entry = _valid_price(plan.get("trigger_price"))
    if entry is None:
        entry = _valid_price(plan.get("entry_price"))
    if entry is None:
        entry = _valid_price(plan.get("entry_zone_low"))
    if entry is None:
        entry = _valid_price(result.get("entry"))
    if entry is None:
        return None, {
            "qualification_state": "REJECTED",
            "reason_code": "NO_ENTRY_REFERENCE",
            "explanation": "The existing trade plan contained no usable entry reference.",
        }

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

    record = create_trade_record(
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
    record.entry_time = None
    return record, {
        "qualification_state": "QUALIFIED",
        "reason_code": "ELIGIBLE_TRADE_OUTCOME",
        "explanation": "The existing scanner conversion produced a canonical opportunity candidate.",
    }


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
