"""Idempotently import legacy PAPER JSON/JSONL state into authoritative SQL."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from types import SimpleNamespace

from option_position_tracker import _deserialize
from option_trade_engine import PaperOptionTrade
from paper_execution_repository import PaperExecutionRepository
from trade_repository import TradeRepository, parse_utc


LOGGER = logging.getLogger(__name__)


def migrate(*, repository, base_path=".", dry_run=False):
    base = Path(base_path)
    paper = PaperExecutionRepository(repository)
    report = {
        "legacy_positions_found": 0, "legacy_trades_found": 0, "journal_rows_found": 0,
        "imported": 0, "skipped": 0, "duplicates": 0, "malformed": 0,
    }
    existing_trades = {item.source_signal_id for item in paper.records()}
    for values in _jsonl(base / "paper_option_trades.jsonl", report, "legacy_trades_found"):
        try:
            values["created_timestamp"] = parse_utc(values["created_timestamp"])
            record = PaperOptionTrade(**values)
            if record.source_signal_id in existing_trades:
                report["duplicates"] += 1
            elif dry_run:
                report["skipped"] += 1
            else:
                paper.append_once(record)
                existing_trades.add(record.source_signal_id)
                report["imported"] += 1
        except Exception:
            report["malformed"] += 1

    position_path = base / "paper_option_positions.json"
    if position_path.exists():
        try:
            payload = json.loads(position_path.read_text(encoding="utf-8"))
            rows = payload.get("positions", []) if isinstance(payload, dict) else []
        except Exception:
            rows = []
            report["malformed"] += 1
        existing_positions = {position.trade_id for position in paper.load()}
        for values in rows:
            report["legacy_positions_found"] += 1
            try:
                position = _deserialize(values)
                if position.trade_id in existing_positions:
                    report["duplicates"] += 1
                elif dry_run:
                    report["skipped"] += 1
                else:
                    paper.upsert_position(position)
                    existing_positions.add(position.trade_id)
                    report["imported"] += 1
            except Exception:
                report["malformed"] += 1

    for row in _jsonl(base / "paper_execution_journal.jsonl", report, "journal_rows_found"):
        try:
            trade = SimpleNamespace(
                trade_id=row.get("trade_id"), option_symbol=row.get("option_symbol"),
            )
            decision = SimpleNamespace(
                eligible=bool(row.get("eligible")), reason=row["reason"],
                position_size=int(row.get("position_size") or 0),
                maximum_cost=float(row.get("maximum_cost") or 0),
                paper_fill_price=row.get("paper_fill_price"),
            )
            if dry_run:
                report["skipped"] += 1
            else:
                before = paper.counts()["journal"]
                paper.append(
                    checked_at=parse_utc(row["timestamp"]), result={"symbol": row.get("symbol")},
                    trade=trade, decision=decision, scanner_id=row.get("scanner_id"),
                    run_number=row.get("run_number"), risk_state=row.get("risk_state"),
                )
                after = paper.counts()["journal"]
                report["imported" if after > before else "duplicates"] += 1
        except Exception:
            report["malformed"] += 1
    report["final_counts"] = paper.counts()
    return report


def _jsonl(path, report, counter):
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        report[counter] += 1
        try:
            rows.append(json.loads(line))
        except Exception:
            report["malformed"] += 1
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-path", default=".")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--db-file", default="optionbeacon_state.db")
    args = parser.parse_args(argv)
    repository = TradeRepository(args.db_file, require_durable=not args.dry_run)
    print(json.dumps(migrate(repository=repository, base_path=args.base_path, dry_run=args.dry_run), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
