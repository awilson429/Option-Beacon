"""Explicit, idempotent legacy trade-history importer."""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

from signal_history import TradeOutcome, deserialize_trade_outcome
from trade_state_service import sync_trade_outcome


@dataclass
class ImportReport:
    source: str
    dry_run: bool
    imported: int = 0
    skipped: int = 0
    invalid: int = 0
    duplicates: int = 0


def import_legacy_history(path, repository, *, dry_run=True) -> ImportReport:
    source = Path(path)
    report = ImportReport(str(source), dry_run)
    if not source.exists():
        report.invalid += 1
        return report
    fingerprint = hashlib.sha256(source.read_bytes()).hexdigest()
    for row_number, record in _records(source):
        if record is None:
            report.invalid += 1
            continue
        if repository.legacy_imported(fingerprint, row_number):
            report.duplicates += 1
            continue
        if repository.get_opportunity(opportunity_id=record.trade_id):
            report.duplicates += 1
            if not dry_run:
                repository.record_legacy_import(
                    source, fingerprint, row_number, record.trade_id
                )
            continue
        if dry_run:
            report.imported += 1
            continue
        sync_trade_outcome(repository, record, source_version=f"legacy:{source.name}")
        if repository.record_legacy_import(
            source, fingerprint, row_number, record.trade_id
        ):
            report.imported += 1
        else:
            report.skipped += 1
    return report


def _records(path):
    if path.suffix.lower() == ".jsonl":
        with path.open("r", encoding="utf-8") as stream:
            for number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    yield number, deserialize_trade_outcome(line)
                except Exception:
                    yield number, None
        return
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            for number, row in enumerate(csv.DictReader(stream), 2):
                try:
                    yield number, _csv_outcome(row, path.name, number)
                except Exception:
                    yield number, None
        return
    yield 1, None


def _csv_outcome(row, source_name, row_number):
    timestamp = _time(
        row.get("Signal Time")
        or row.get("Timestamp")
        or row.get("timestamp")
        or row.get("Entered")
    )
    symbol = row.get("Symbol") or row.get("symbol") or row.get("Ticker")
    direction = row.get("Direction") or row.get("direction")
    if not timestamp or not symbol or not direction:
        raise ValueError("missing identity")
    identity = json.dumps(
        {
            "source": source_name,
            "row": row_number,
            "symbol": symbol,
            "direction": direction,
            "timestamp": timestamp.isoformat(),
        },
        sort_keys=True,
    )
    return TradeOutcome(
        trade_id=hashlib.sha256(identity.encode("utf-8")).hexdigest(),
        timestamp=timestamp,
        symbol=str(symbol).upper(),
        direction=direction,
        setup=row.get("Setup") or row.get("setup") or "Legacy",
        confidence=_number(row.get("Confidence") or row.get("confidence")) or 0,
        entry=_number(row.get("Entry") or row.get("entry")),
        stop=_number(row.get("Stop") or row.get("stop")),
        target_1=_number(row.get("Target 1") or row.get("target_1")),
        target_2=_number(row.get("Target 2") or row.get("target_2")),
        target_3=_number(row.get("Target 3") or row.get("target_3")),
        entry_time=_time(row.get("Entry Time") or row.get("Entered")),
        exit_time=_time(row.get("Exit Time") or row.get("Closed")),
        exit_reason=row.get("Exit Reason") or row.get("Outcome") or None,
        max_favorable_excursion=_number(row.get("MFE")),
        max_adverse_excursion=_number(row.get("MAE")),
        realized_return=_number(
            row.get("Realized Return") or row.get("Return %") or row.get("Premium P/L")
        ),
        hold_minutes=_number(row.get("Hold Minutes")),
    )


def _time(value):
    if value is None or not str(value).strip():
        return None
    text = str(value).strip().replace("Z", "+00:00")
    for parser in (
        lambda: datetime.fromisoformat(text),
        lambda: datetime.strptime(text, "%Y-%m-%d %H:%M"),
        lambda: datetime.strptime(text, "%Y-%m-%d %I:%M:%S %p ET"),
    ):
        try:
            parsed = parser()
            return (
                parsed.replace(tzinfo=timezone.utc)
                if parsed.tzinfo is None
                else parsed
            )
        except ValueError:
            continue
    return None


def _number(value):
    if value is None or not str(value).strip():
        return None
    return float(str(value).replace("$", "").replace("%", "").replace(",", ""))
