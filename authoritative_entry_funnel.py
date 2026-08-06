"""Read-only models and additive worker diagnostics for authoritative entries."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from optionbeacon_strategy import (
    BREAKOUT_BUFFER_DOWN,
    BREAKOUT_BUFFER_UP,
    DEFAULT_CALL_SCORE_THRESHOLD,
    DEFAULT_PUT_SCORE_THRESHOLD,
    VOLUME_MULTIPLIER,
)
from signal_history import (
    DEFAULT_MIN_ENTRY_CONFIDENCE,
    entry_confidence_eligible,
    scanner_result_to_trade_outcome,
)
from trade_repository import utc_iso


EASTERN = ZoneInfo("America/New_York")
FUNNEL_STAGES = (
    "scanned", "valid_results", "directional_candidates", "confidence_qualified",
    "trigger_reached", "not_entered", "trade_entered",
)


class AuthoritativeEntryFunnelRepository:
    """Persist diagnostic snapshots without participating in lifecycle decisions."""

    def __init__(self, repository, *, initialize=True):
        self.repository = repository
        if initialize:
            self.initialize()

    def initialize(self):
        with self.repository.connection() as connection:
            self.repository._execute(connection, """CREATE TABLE IF NOT EXISTS authoritative_entry_funnel_cycles (
                cycle_id TEXT PRIMARY KEY, scanner_id TEXT NOT NULL, run_number INTEGER,
                session_date TEXT NOT NULL, started_at TEXT NOT NULL, completed_at TEXT NOT NULL,
                scanned INTEGER NOT NULL, valid_results INTEGER NOT NULL,
                directional_candidates INTEGER NOT NULL, qualified_setups INTEGER NOT NULL,
                armed INTEGER NOT NULL, trigger_reached INTEGER NOT NULL,
                trade_entered INTEGER NOT NULL, blocker_counts_json TEXT NOT NULL,
                thresholds_json TEXT NOT NULL, created_at TEXT NOT NULL,
                confidence_qualified INTEGER NOT NULL DEFAULT 0,
                visible_setup_qualified INTEGER NOT NULL DEFAULT 0,
                not_entered INTEGER NOT NULL DEFAULT 0
            )""").close()
            self.repository._execute(connection, """CREATE TABLE IF NOT EXISTS authoritative_entry_funnel_symbols (
                cycle_id TEXT NOT NULL, symbol TEXT NOT NULL, direction TEXT, score REAL,
                state TEXT NOT NULL, primary_blocker TEXT, failed_conditions_json TEXT NOT NULL,
                trigger_price REAL, current_price REAL, distance_to_trigger_pct REAL,
                last_updated TEXT NOT NULL, trade_entered INTEGER NOT NULL,
                candidate_confidence REAL, candidate_age_minutes REAL,
                lifecycle_state TEXT, authoritative_disposition TEXT,
                opportunity_id TEXT, confidence_qualified INTEGER NOT NULL DEFAULT 0,
                visible_setup_qualified INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(cycle_id,symbol)
            )""").close()
            self._ensure_columns(connection, "authoritative_entry_funnel_cycles", {
                "confidence_qualified": "INTEGER NOT NULL DEFAULT 0",
                "visible_setup_qualified": "INTEGER NOT NULL DEFAULT 0",
                "not_entered": "INTEGER NOT NULL DEFAULT 0",
            })
            self._ensure_columns(connection, "authoritative_entry_funnel_symbols", {
                "candidate_confidence": "REAL",
                "candidate_age_minutes": "REAL",
                "lifecycle_state": "TEXT",
                "authoritative_disposition": "TEXT",
                "opportunity_id": "TEXT",
                "confidence_qualified": "INTEGER NOT NULL DEFAULT 0",
                "visible_setup_qualified": "INTEGER NOT NULL DEFAULT 0",
            })
            self.repository._execute(connection, "CREATE INDEX IF NOT EXISTS idx_auth_funnel_session ON authoritative_entry_funnel_cycles(session_date,completed_at)").close()

    def _ensure_columns(self, connection, table, definitions):
        if self.repository.backend == "postgresql":
            rows = self.repository._fetchall(connection, """SELECT column_name AS name
                FROM information_schema.columns WHERE table_name=?""", (table,))
        else:
            rows = self.repository._fetchall(connection, f"PRAGMA table_info({table})")
        existing = {row["name"] for row in rows}
        for name, definition in definitions.items():
            if name not in existing:
                self.repository._execute(
                    connection, f"ALTER TABLE {table} ADD COLUMN {name} {definition}"
                ).close()

    def save_cycle(self, *, scanner_id, run_number, started_at, completed_at, symbols,
                   entered_events, candidate_records=()):
        candidates_by_symbol = {}
        for record in candidate_records or ():
            candidates_by_symbol.setdefault(record.symbol.upper(), []).append(record)
        entered_by_id = {
            str(event.get("opportunity_id") or event.get("trade_id") or "")
            for event in entered_events
        }
        diagnostics = [
            classify_symbol(
                symbol, result,
                candidate=_candidate_for_cycle(
                    candidates_by_symbol.get(str(symbol).upper(), []), entered_by_id
                ),
                completed_at=completed_at,
            )
            for symbol, result in symbols
        ]
        entered_by_symbol = Counter(str(event.get("symbol") or "").upper() for event in entered_events)
        for row in diagnostics:
            row["trade_entered"] = 1 if entered_by_symbol.get(row["symbol"]) else 0
            if row["trade_entered"]:
                row["primary_blocker"] = None
                row["authoritative_disposition"] = "TRADE_ENTERED_THIS_CYCLE"
        counts = funnel_counts(diagnostics, entered_count=len(entered_events))
        blockers = Counter(row["primary_blocker"] for row in diagnostics if row.get("primary_blocker"))
        cycle_id = hashlib.sha256(f"{scanner_id}|{run_number}|{utc_iso(started_at)}".encode()).hexdigest()
        session_date = _aware(completed_at).astimezone(EASTERN).date().isoformat()
        thresholds = configured_thresholds()
        with self.repository.connection() as connection:
            self.repository._execute(connection, """INSERT INTO authoritative_entry_funnel_cycles
                (cycle_id,scanner_id,run_number,session_date,started_at,completed_at,scanned,
                 valid_results,directional_candidates,qualified_setups,armed,trigger_reached,
                 trade_entered,blocker_counts_json,thresholds_json,created_at)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(cycle_id) DO UPDATE SET
                 completed_at=excluded.completed_at,scanned=excluded.scanned,
                 valid_results=excluded.valid_results,
                 directional_candidates=excluded.directional_candidates,
                 qualified_setups=excluded.qualified_setups,armed=excluded.armed,
                 trigger_reached=excluded.trigger_reached,trade_entered=excluded.trade_entered,
                 blocker_counts_json=excluded.blocker_counts_json,
                 thresholds_json=excluded.thresholds_json""", (
                cycle_id, scanner_id, run_number, session_date, utc_iso(started_at), utc_iso(completed_at),
                counts["scanned"], counts["valid_results"], counts["directional_candidates"],
                counts["qualified_setups"], counts["armed"], counts["trigger_reached"],
                counts["trade_entered"], json.dumps(dict(sorted(blockers.items())), sort_keys=True),
                json.dumps(thresholds, sort_keys=True), utc_iso(),
            )).close()
            self.repository._execute(connection, """UPDATE authoritative_entry_funnel_cycles SET
                confidence_qualified=?,visible_setup_qualified=?,not_entered=? WHERE cycle_id=?""", (
                counts["confidence_qualified"], counts["visible_setup_qualified"],
                counts["not_entered"], cycle_id,
            )).close()
            for row in diagnostics:
                self.repository._execute(connection, """INSERT INTO authoritative_entry_funnel_symbols
                    (cycle_id,symbol,direction,score,state,primary_blocker,failed_conditions_json,
                     trigger_price,current_price,distance_to_trigger_pct,last_updated,trade_entered)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(cycle_id,symbol) DO UPDATE SET
                     direction=excluded.direction,score=excluded.score,state=excluded.state,
                     primary_blocker=excluded.primary_blocker,
                     failed_conditions_json=excluded.failed_conditions_json,
                     trigger_price=excluded.trigger_price,current_price=excluded.current_price,
                     distance_to_trigger_pct=excluded.distance_to_trigger_pct,
                     last_updated=excluded.last_updated,trade_entered=excluded.trade_entered""", (
                    cycle_id, row["symbol"], row["direction"], row["score"], row["state"],
                    row["primary_blocker"], json.dumps(row["failed_conditions"], sort_keys=True),
                    row["trigger_price"], row["current_price"], row["distance_to_trigger_pct"],
                    utc_iso(completed_at), row["trade_entered"],
                )).close()
                self.repository._execute(connection, """UPDATE authoritative_entry_funnel_symbols SET
                    candidate_confidence=?,candidate_age_minutes=?,lifecycle_state=?,
                    authoritative_disposition=?,opportunity_id=?,confidence_qualified=?,
                    visible_setup_qualified=? WHERE cycle_id=? AND symbol=?""", (
                    row["candidate_confidence"], row["candidate_age_minutes"],
                    row["lifecycle_state"], row["authoritative_disposition"],
                    row["opportunity_id"], 1 if row["confidence_qualified"] else 0,
                    1 if row["visible_setup_qualified"] else 0, cycle_id, row["symbol"],
                )).close()
        return {"cycle_id": cycle_id, **counts, "blockers": dict(blockers)}

    def latest_cycle(self, session_date=None):
        query = "SELECT * FROM authoritative_entry_funnel_cycles"
        params = ()
        if session_date:
            query += " WHERE session_date=?"
            params = (str(session_date),)
        query += " ORDER BY completed_at DESC LIMIT 1"
        with self.repository.connection() as connection:
            row = self.repository._fetchone(connection, query, params)
        return _decode_cycle(row)

    def previous_session_cycle(self, current_session_date):
        with self.repository.connection() as connection:
            row = self.repository._fetchone(connection, """SELECT * FROM authoritative_entry_funnel_cycles
                WHERE session_date < ? ORDER BY session_date DESC,completed_at DESC LIMIT 1""",
                (str(current_session_date),))
        return _decode_cycle(row)

    def symbol_rows(self, cycle_id):
        with self.repository.connection() as connection:
            rows = self.repository._fetchall(connection, """SELECT * FROM authoritative_entry_funnel_symbols
                WHERE cycle_id=? ORDER BY trade_entered DESC,
                CASE WHEN distance_to_trigger_pct IS NULL THEN 1 ELSE 0 END,
                ABS(distance_to_trigger_pct),score DESC,symbol""", (cycle_id,))
        for row in rows:
            row["failed_conditions"] = _json(row.get("failed_conditions_json"), [])
        return rows


def classify_symbol(symbol, result, *, candidate=None, completed_at=None):
    """Classify only real production stages and conditions; never change a result."""
    result = result or {}
    symbol = str(result.get("symbol") or symbol or "").upper()
    price = _number(result.get("price"))
    direction = str(result.get("bias") or "")
    score = _number(result.get("confidence"))
    signal = str(result.get("signal") or "")
    stage = str(result.get("setup_stage") or "Unavailable")
    timing = str(result.get("entry_timing") or "")
    plan = result.get("trade_plan") or {}
    trigger = _number(plan.get("trigger_price") or result.get("trigger_price"))
    valid = bool(result) and price is not None and price > 0
    directional = direction in {"Bullish", "Bearish"}
    candidate = candidate or (scanner_result_to_trade_outcome(result) if valid else None)
    visible_setup_qualified = signal in {"BULLISH SETUP", "BEARISH SETUP"}
    confidence_qualified = bool(candidate and entry_confidence_eligible(candidate))
    armed = directional and stage == "Armed"
    trigger_reached = directional and (
        stage == "Triggered" or _trigger_reached(direction, price, trigger)
    )
    blocker = None
    failed = []
    if not valid:
        blocker = "INSUFFICIENT_DATA"
    elif signal == "MARKET CLOSED / WAIT":
        blocker = "ENTRY_WINDOW"
    elif not directional:
        blocker = "DIRECTION_UNCLEAR"
    elif stage == "Failed" or timing == "Setup invalidated":
        blocker = "SETUP_INVALIDATED"
    elif stage == "Extended" or timing == "Do not chase":
        blocker = "DO_NOT_CHASE"
    elif candidate is None:
        blocker = "NO_VALID_AUTHORITATIVE_CANDIDATE"
    elif not trigger_reached:
        blocker = "TRIGGER_NOT_REACHED"
    elif not confidence_qualified:
        blocker = "ENTRY_CONFIDENCE_BELOW_MINIMUM"
    else:
        blocker = "AWAITING_AUTHORITATIVE_LIFECYCLE"
    if directional:
        threshold = DEFAULT_CALL_SCORE_THRESHOLD if direction == "Bullish" else DEFAULT_PUT_SCORE_THRESHOLD
        if score is None or score < threshold:
            failed.append("SCORE_BELOW_DIRECTIONAL_THRESHOLD")
    if stage == "Armed" or (directional and trigger is not None and not trigger_reached):
        failed.append("TRIGGER_NOT_REACHED")
    if candidate is None:
        failed.append("NO_VALID_AUTHORITATIVE_CANDIDATE")
    return {
        "symbol": symbol, "valid": valid, "directional": directional,
        "candidate": candidate is not None, "qualified": visible_setup_qualified,
        "visible_setup_qualified": visible_setup_qualified,
        "confidence_qualified": confidence_qualified, "armed": armed,
        "trigger_reached": trigger_reached, "trade_entered": 0,
        "direction": "CALL" if direction == "Bullish" else "PUT" if direction == "Bearish" else None,
        "score": score, "candidate_confidence": candidate.confidence if candidate else None,
        "candidate_age_minutes": _candidate_age(candidate, completed_at),
        "lifecycle_state": _lifecycle_state(candidate),
        "authoritative_disposition": blocker or "AWAITING_AUTHORITATIVE_LIFECYCLE",
        "opportunity_id": candidate.trade_id if candidate else None,
        "state": stage, "primary_blocker": blocker,
        "failed_conditions": list(dict.fromkeys(failed)), "trigger_price": trigger,
        "current_price": price, "distance_to_trigger_pct": _distance(direction, price, trigger),
    }


def funnel_counts(rows, *, entered_count=0):
    return {
        "scanned": len(rows),
        "valid_results": sum(row["valid"] for row in rows),
        "directional_candidates": sum(row["directional"] for row in rows),
        "qualified_setups": sum(row["visible_setup_qualified"] for row in rows),
        "visible_setup_qualified": sum(row["visible_setup_qualified"] for row in rows),
        "confidence_qualified": sum(row["confidence_qualified"] for row in rows),
        "armed": sum(row["armed"] for row in rows),
        "trigger_reached": sum(row["trigger_reached"] for row in rows),
        "trade_entered": int(entered_count),
        "not_entered": sum(not row.get("trade_entered") for row in rows),
    }


def _candidate_for_cycle(records, entered_ids):
    entered = [record for record in records if record.trade_id in entered_ids]
    values = entered or [record for record in records if record.exit_time is None] or list(records)
    return max(values, key=lambda record: _aware(record.timestamp), default=None)


def _candidate_age(candidate, completed_at):
    if candidate is None or completed_at is None:
        return None
    return round(max(0, (_aware(completed_at) - _aware(candidate.timestamp)).total_seconds()) / 60, 3)


def _lifecycle_state(candidate):
    if candidate is None:
        return "NO_CANDIDATE"
    if candidate.exit_time is not None:
        return str(candidate.exit_reason or "CLOSED")
    return "ENTERED" if candidate.entry_time is not None else "CANDIDATE"


def configured_thresholds():
    return {
        "call_score_threshold": DEFAULT_CALL_SCORE_THRESHOLD,
        "put_score_threshold": DEFAULT_PUT_SCORE_THRESHOLD,
        "authoritative_entry_confidence": DEFAULT_MIN_ENTRY_CONFIDENCE,
        "breakout_buffer_up": BREAKOUT_BUFFER_UP,
        "breakout_buffer_down": BREAKOUT_BUFFER_DOWN,
        "volume_multiplier": VOLUME_MULTIPLIER,
        "score_armed_threshold": 70,
        "armed_distance_atr": 0.4,
        "extended_distance_atr": 0.5,
        "scanner_entry_window_et": "09:45-14:59",
        "authoritative_entry_cutoff_et": "15:55",
        "candidate_max_age_minutes": 60,
    }


def near_entry_rows(rows, limit=10):
    candidates = [row for row in rows if not row.get("trade_entered") and row.get("direction")]
    candidates.sort(key=lambda row: (
        0 if row.get("state") in {"Armed", "Triggered"} else 1,
        abs(row["distance_to_trigger_pct"]) if row.get("distance_to_trigger_pct") is not None else math.inf,
        -(row.get("score") or 0), row.get("symbol") or "",
    ))
    return candidates[:limit]


def _trigger_reached(direction, price, trigger):
    if price is None or trigger is None:
        return False
    return price >= trigger if direction == "Bullish" else price <= trigger if direction == "Bearish" else False


def _distance(direction, price, trigger):
    if price is None or trigger in (None, 0) or direction not in {"Bullish", "Bearish"}:
        return None
    raw = (trigger - price) / trigger * 100
    return raw if direction == "Bullish" else -raw


def _number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _aware(value):
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _json(value, fallback):
    try:
        return json.loads(value) if isinstance(value, str) else value or fallback
    except (TypeError, ValueError):
        return fallback


def _decode_cycle(row):
    if not row:
        return None
    row["blocker_counts"] = _json(row.get("blocker_counts_json"), {})
    row["thresholds"] = _json(row.get("thresholds_json"), {})
    return row
