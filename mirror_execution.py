"""Railway-owned MIRROR PAPER execution of authoritative trade lifecycles."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from option_trade_engine import TradierOptionChainProvider, preferred_expiration, select_contract
from signal_history import deserialize_trade_outcome
from trade_repository import utc_iso
from tradier_options import option_quote


LOGGER = logging.getLogger(__name__)
MIRROR_FILL_MODEL = "MIRROR_CONSERVATIVE_QUARTER_SPREAD_V1"
MIRROR_MULTIPLIER = 100
EASTERN = ZoneInfo("America/New_York")


def mirror_enabled(environ=None):
    value = (environ or os.environ).get("OPTIONBEACON_MIRROR_ENABLED", "false")
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def mirror_experiment_start(environ=None):
    value = str((environ or os.environ).get("MIRROR_EXPERIMENT_START_DATE", "")).strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        LOGGER.warning(json.dumps({"event": "mirror_config_invalid", "setting": "MIRROR_EXPERIMENT_START_DATE"}))
        return None


def _aware(value):
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result


def _number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _entry_fill(bid, ask):
    midpoint = (bid + ask) / 2
    return round(midpoint + (ask - midpoint) * 0.25, 4)


def _exit_fill(bid, ask):
    midpoint = (bid + ask) / 2
    return round(midpoint - (midpoint - bid) * 0.25, 4)


def _usable_quote(values):
    bid, ask = _number(values.get("bid")), _number(values.get("ask"))
    return bid is not None and ask is not None and bid >= 0 and ask > 0 and bid <= ask


class MirrorExecutionRepository:
    """Separate durable MIRROR ledger; never aliases BROAD PAPER rows."""

    def __init__(self, repository, *, initialize=True):
        self.repository = repository
        if initialize:
            self.initialize()

    def initialize(self):
        with self.repository.connection() as connection:
            for ddl in (
                """CREATE TABLE IF NOT EXISTS mirror_execution_trades (
                    mirror_trade_id TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL UNIQUE,
                    authoritative_trade_id TEXT, authoritative_entry_event_id TEXT,
                    authoritative_exit_event_id TEXT, symbol TEXT NOT NULL, direction TEXT,
                    option_symbol TEXT, option_type TEXT, strike REAL, expiration TEXT, dte INTEGER,
                    quantity INTEGER NOT NULL, contract_multiplier INTEGER NOT NULL,
                    underlying_entry_price REAL, entry_bid REAL, entry_ask REAL, entry_mid REAL,
                    entry_fill REAL, spread_dollars REAL, spread_percent REAL,
                    open_interest INTEGER, option_volume INTEGER, total_debit REAL,
                    entry_event_at TEXT, opened_at TEXT, status TEXT NOT NULL,
                    disposition_code TEXT NOT NULL, disposition_detail TEXT,
                    authoritative_exit_at TEXT, authoritative_exit_reason TEXT,
                    exit_quote_at TEXT, exit_bid REAL, exit_ask REAL, exit_mid REAL, exit_fill REAL,
                    exit_value REAL, realized_pnl REAL, realized_return_percent REAL,
                    current_bid REAL, current_ask REAL, current_mark REAL,
                    current_value REAL, unrealized_pnl REAL, last_quote_at TEXT,
                    fill_model TEXT NOT NULL, metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                )""",
                """CREATE TABLE IF NOT EXISTS mirror_execution_journal (
                    journal_id TEXT PRIMARY KEY, dedup_key TEXT NOT NULL UNIQUE,
                    opportunity_id TEXT, mirror_trade_id TEXT, event_type TEXT NOT NULL,
                    reason_code TEXT, event_at TEXT NOT NULL, metadata_json TEXT NOT NULL
                )""",
                """CREATE TABLE IF NOT EXISTS mirror_execution_runtime_state (
                    scanner_id TEXT PRIMARY KEY, enabled INTEGER NOT NULL, status TEXT NOT NULL,
                    experiment_start_date TEXT, fill_model TEXT NOT NULL,
                    last_cycle_at TEXT, last_error TEXT, updated_at TEXT NOT NULL
                )""",
                """CREATE TABLE IF NOT EXISTS mirror_execution_marks (
                    mark_id TEXT PRIMARY KEY, mirror_trade_id TEXT NOT NULL,
                    opportunity_id TEXT NOT NULL, symbol TEXT NOT NULL, option_symbol TEXT,
                    observed_at TEXT NOT NULL, underlying_price REAL,
                    bid REAL, ask REAL, midpoint REAL, conservative_mark REAL,
                    entry_fill REAL, return_pct REAL, unrealized_pnl REAL,
                    spread_dollars REAL, spread_percent REAL,
                    mfe_pct REAL, mae_pct REAL, peak_return_pct REAL,
                    peak_unrealized_pnl REAL, time_since_entry_seconds REAL,
                    update_status TEXT NOT NULL,
                    UNIQUE(mirror_trade_id,observed_at)
                )""",
            ):
                self.repository._execute(connection, ddl).close()
            additions = (
                ("mfe_pct", "REAL"), ("mae_pct", "REAL"),
                ("peak_return_pct", "REAL"), ("peak_unrealized_pnl", "REAL"),
            )
            if self.repository.backend == "postgresql":
                for name, definition in additions:
                    self.repository._execute(connection,
                        f"ALTER TABLE mirror_execution_trades ADD COLUMN IF NOT EXISTS {name} {definition}").close()
            else:
                existing = {row["name"] for row in self.repository._fetchall(
                    connection, "PRAGMA table_info(mirror_execution_trades)")}
                for name, definition in additions:
                    if name not in existing:
                        self.repository._execute(connection,
                            f"ALTER TABLE mirror_execution_trades ADD COLUMN {name} {definition}").close()
            self.repository._execute(connection, "CREATE INDEX IF NOT EXISTS idx_mirror_status ON mirror_execution_trades(status)").close()
            self.repository._execute(connection, "CREATE INDEX IF NOT EXISTS idx_mirror_journal_at ON mirror_execution_journal(event_at)").close()
            self.repository._execute(connection, "CREATE INDEX IF NOT EXISTS idx_mirror_marks_trade_at ON mirror_execution_marks(mirror_trade_id,observed_at)").close()

    def save_runtime_state(self, scanner_id, *, enabled, status, experiment_start_date=None, error=None, now=None):
        now = now or datetime.now(timezone.utc)
        values = (1 if enabled else 0, status, str(experiment_start_date or "") or None,
                  MIRROR_FILL_MODEL, utc_iso(now), str(error or "")[:240] or None, utc_iso(now))
        with self.repository.connection() as connection:
            current = self.repository._fetchone(connection, "SELECT scanner_id FROM mirror_execution_runtime_state WHERE scanner_id=?", (scanner_id,))
            if current:
                self.repository._execute(connection, """UPDATE mirror_execution_runtime_state SET
                    enabled=?,status=?,experiment_start_date=?,fill_model=?,last_cycle_at=?,last_error=?,updated_at=?
                    WHERE scanner_id=?""", (*values, scanner_id)).close()
            else:
                self.repository._execute(connection, """INSERT INTO mirror_execution_runtime_state
                    (enabled,status,experiment_start_date,fill_model,last_cycle_at,last_error,updated_at,scanner_id)
                    VALUES (?,?,?,?,?,?,?,?)""", (*values, scanner_id)).close()

    def runtime_state(self):
        with self.repository.connection() as connection:
            return self.repository._fetchone(connection, "SELECT * FROM mirror_execution_runtime_state ORDER BY updated_at DESC LIMIT 1")

    def rows(self):
        with self.repository.connection() as connection:
            return self.repository._fetchall(connection, "SELECT * FROM mirror_execution_trades ORDER BY entry_event_at,created_at")

    def open_rows(self):
        """Return only lifecycle-active rows for the worker hot path."""
        with self.repository.connection() as connection:
            return self.repository._fetchall(connection, """SELECT mirror_trade_id,opportunity_id,
                symbol,option_symbol,quantity,contract_multiplier,total_debit,entry_fill,opened_at,
                status,mfe_pct,mae_pct,peak_unrealized_pnl FROM mirror_execution_trades
                WHERE status IN ('OPEN','EXIT_PENDING') ORDER BY opened_at,mirror_trade_id""")

    def status_count(self, status):
        with self.repository.connection() as connection:
            row = self.repository._fetchone(connection,
                "SELECT COUNT(*) AS count FROM mirror_execution_trades WHERE status=?", (status,))
        return int((row or {}).get("count") or 0)

    def disposition_count(self):
        with self.repository.connection() as connection:
            row = self.repository._fetchone(connection, "SELECT COUNT(*) AS count FROM mirror_execution_trades")
        return int((row or {}).get("count") or 0)

    def comparison_rows(self, opportunity_ids):
        identities = sorted({str(value) for value in opportunity_ids if value})
        if not identities:
            return []
        placeholders = ",".join("?" for _ in identities)
        with self.repository.connection() as connection:
            return self.repository._fetchall(connection, f"""SELECT opportunity_id,
                disposition_code,option_symbol,realized_pnl FROM mirror_execution_trades
                WHERE opportunity_id IN ({placeholders})""", tuple(identities))

    def analytics_rows(self, opportunity_ids, *, limit=5000):
        """Project only analytics columns for exact authoritative IDs."""
        identities = sorted({str(value) for value in opportunity_ids if value})[:int(limit)]
        if not identities:
            return []
        placeholders = ",".join("?" for _ in identities)
        query = f"""SELECT mirror_trade_id,opportunity_id,symbol,direction,option_symbol,
            option_type,strike,expiration,dte,quantity,contract_multiplier,
            underlying_entry_price,entry_bid,entry_ask,entry_mid,entry_fill,
            spread_dollars,spread_percent,open_interest,option_volume,total_debit,
            entry_event_at,opened_at,status,disposition_code,exit_quote_at,
            exit_bid,exit_ask,exit_mid,exit_fill,realized_pnl,
            realized_return_percent,authoritative_exit_reason,mfe_pct,mae_pct,
            peak_return_pct,peak_unrealized_pnl,updated_at,metadata_json
            FROM mirror_execution_trades WHERE opportunity_id IN ({placeholders})
            ORDER BY entry_event_at,opportunity_id LIMIT ?"""
        with self.repository.connection() as connection:
            return self.repository._fetchall(connection, query, (*identities, int(limit)))

    def get(self, opportunity_id):
        with self.repository.connection() as connection:
            return self.repository._fetchone(connection, "SELECT * FROM mirror_execution_trades WHERE opportunity_id=?", (opportunity_id,))

    def marks(self, mirror_trade_id=None):
        query, params = "SELECT * FROM mirror_execution_marks", ()
        if mirror_trade_id:
            query += " WHERE mirror_trade_id=?"
            params = (mirror_trade_id,)
        query += " ORDER BY observed_at,mark_id"
        with self.repository.connection() as connection:
            return self.repository._fetchall(connection, query, params)

    def mark_summaries(self, mirror_trade_ids, *, observed_after=None):
        """Return one telemetry summary per requested trade without transferring raw marks."""
        identities = sorted({str(value) for value in mirror_trade_ids if value})
        if not identities:
            return []
        placeholders = ",".join("?" for _ in identities)
        query = f"""SELECT mirror_trade_id,
            COUNT(return_pct) AS valid_mark_count,
            MAX(mfe_pct) AS mfe_pct,MIN(mae_pct) AS mae_pct,
            MAX(peak_return_pct) AS peak_return_pct,
            MAX(peak_unrealized_pnl) AS peak_unrealized_pnl,
            MIN(observed_at) AS first_observed_at,MAX(observed_at) AS last_observed_at
            FROM mirror_execution_marks
            WHERE mirror_trade_id IN ({placeholders})"""
        params = list(identities)
        if observed_after is not None:
            query += " AND observed_at>=?"
            params.append(utc_iso(observed_after) if isinstance(observed_after, datetime) else str(observed_after))
        query += " GROUP BY mirror_trade_id ORDER BY mirror_trade_id"
        with self.repository.connection() as connection:
            return self.repository._fetchall(connection, query, tuple(params))

    def analytics_marks(self, mirror_trade_ids, *, observed_after=None, limit=20000):
        """Return bounded persisted marks for exact MIRROR trade identities."""
        identities = sorted({str(value) for value in mirror_trade_ids if value})
        if not identities:
            return []
        placeholders = ",".join("?" for _ in identities)
        query = f"""SELECT mark_id,mirror_trade_id,opportunity_id,symbol,option_symbol,
            observed_at,underlying_price,bid,ask,midpoint,conservative_mark,entry_fill,
            return_pct,unrealized_pnl,spread_dollars,spread_percent,mfe_pct,mae_pct,
            peak_return_pct,peak_unrealized_pnl,time_since_entry_seconds,update_status
            FROM mirror_execution_marks WHERE mirror_trade_id IN ({placeholders})"""
        params = list(identities)
        if observed_after is not None:
            query += " AND observed_at>=?"
            params.append(utc_iso(observed_after) if isinstance(observed_after, datetime) else str(observed_after))
        query += " ORDER BY observed_at,mark_id LIMIT ?"
        params.append(int(limit))
        with self.repository.connection() as connection:
            return self.repository._fetchall(connection, query, tuple(params))

    def dispositioned_source_signal_ids(self):
        with self.repository.connection() as connection:
            rows = self.repository._fetchall(connection,
                "SELECT opportunity_id FROM mirror_execution_trades")
        return {row["opportunity_id"] for row in rows}

    def record_disposition(self, candidate, event, *, code, detail, contract=None, now=None):
        now = now or datetime.now(timezone.utc)
        opportunity_id = str(candidate.get("_authoritative_entry_id"))
        existing = self.get(opportunity_id)
        if existing:
            return existing
        contract = contract or {}
        trade_id = hashlib.sha256(f"{opportunity_id}|MIRROR".encode()).hexdigest()
        bid, ask = _number(contract.get("bid")), _number(contract.get("ask"))
        mid = (bid + ask) / 2 if bid is not None and ask is not None else None
        fill = _entry_fill(bid, ask) if code == "MIRROR_OPENED" else None
        debit = fill * MIRROR_MULTIPLIER if fill is not None else None
        expiration = contract.get("expiration")
        try:
            dte = (date.fromisoformat(str(expiration)) - _aware(event["event_timestamp"]).date()).days
        except (TypeError, ValueError):
            dte = None
        spread = ask - bid if bid is not None and ask is not None else None
        spread_pct = spread / mid * 100 if mid else None
        values = (
            trade_id, opportunity_id, event.get("trade_id"), event.get("id"), candidate.get("symbol"),
            (candidate.get("trade_plan") or {}).get("direction") or candidate.get("bias"),
            contract.get("option_symbol"), contract.get("option_type"), contract.get("strike"), expiration, dte,
            1, MIRROR_MULTIPLIER, candidate.get("price"), bid, ask, mid, fill, spread, spread_pct,
            contract.get("open_interest"), contract.get("volume"), debit,
            utc_iso(_aware(event["event_timestamp"])), utc_iso(now) if fill is not None else None,
            "OPEN" if fill is not None else "UNEXECUTABLE", code, detail, fill, debit,
            (debit and 0.0), utc_iso(now) if fill is not None else None,
            MIRROR_FILL_MODEL, json.dumps({"entry_quote_timestamp": contract.get("quote_timestamp")}, sort_keys=True),
            utc_iso(now), utc_iso(now),
        )
        with self.repository.connection() as connection:
            self.repository._execute(connection, """INSERT INTO mirror_execution_trades (
                mirror_trade_id,opportunity_id,authoritative_trade_id,authoritative_entry_event_id,
                symbol,direction,option_symbol,option_type,strike,expiration,dte,quantity,contract_multiplier,
                underlying_entry_price,entry_bid,entry_ask,entry_mid,entry_fill,spread_dollars,spread_percent,
                open_interest,option_volume,total_debit,entry_event_at,opened_at,status,disposition_code,
                disposition_detail,current_mark,current_value,unrealized_pnl,last_quote_at,fill_model,
                metadata_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", values).close()
        self.journal(opportunity_id, trade_id, "mirror_entry_opened" if fill else "mirror_entry_unexecutable", code, now, {"detail": detail})
        try:
            from opportunity_context import dte_bucket, spread_bucket
            self.repository.enrich_opportunity_context(opportunity_id, {
                "lifecycle": {"mirror_contract_selected_at": utc_iso(now), "mirror_opened_at": utc_iso(now) if fill is not None else None},
                "option_execution": {"contract": contract.get("option_symbol"), "option_type": contract.get("option_type"),
                    "expiration": expiration, "dte": dte, "strike": contract.get("strike"), "bid": bid, "ask": ask,
                    "midpoint": mid, "conservative_fill": fill, "spread_dollars": spread, "spread_percent": spread_pct,
                    "volume": contract.get("volume"), "open_interest": contract.get("open_interest"), "delta": contract.get("delta"),
                    "iv": contract.get("iv"), "spread_bucket": spread_bucket(spread_pct), "dte_bucket": dte_bucket(dte)},
            })
        except Exception:
            LOGGER.exception("Could not enrich shadow opportunity context %s", opportunity_id)
        return self.get(opportunity_id)

    def _snapshot(self, connection, row, quote, now, *, underlying_price=None,
                  update_status="CURRENT", conservative_mark=None):
        observed_at = utc_iso(now)
        bid = _number((quote or {}).get("bid"))
        ask = _number((quote or {}).get("ask"))
        midpoint = (bid + ask) / 2 if bid is not None and ask is not None else None
        spread = ask - bid if bid is not None and ask is not None else None
        spread_pct = spread / midpoint * 100 if midpoint else None
        entry_fill = _number(row.get("entry_fill"))
        mark = conservative_mark
        if mark is None and _usable_quote(quote or {}):
            mark = _exit_fill(bid, ask)
        return_pct = (mark / entry_fill - 1) * 100 if mark is not None and entry_fill else None
        pnl = (mark - entry_fill) * int(row.get("quantity") or 1) * int(row.get("contract_multiplier") or 100) if return_pct is not None else None
        prior_mfe, prior_mae = _number(row.get("mfe_pct")), _number(row.get("mae_pct"))
        mfe = max(value for value in (prior_mfe, return_pct) if value is not None) if any(value is not None for value in (prior_mfe, return_pct)) else None
        mae = min(value for value in (prior_mae, return_pct) if value is not None) if any(value is not None for value in (prior_mae, return_pct)) else None
        prior_peak_pnl = _number(row.get("peak_unrealized_pnl"))
        peak_pnl = max(value for value in (prior_peak_pnl, pnl) if value is not None) if any(value is not None for value in (prior_peak_pnl, pnl)) else None
        opened = _aware(row["opened_at"]) if row.get("opened_at") else None
        elapsed = (now - opened).total_seconds() if opened else None
        mark_id = hashlib.sha256(f"{row['mirror_trade_id']}|{observed_at}".encode()).hexdigest()
        cursor = self.repository._execute(connection, """INSERT INTO mirror_execution_marks (
            mark_id,mirror_trade_id,opportunity_id,symbol,option_symbol,observed_at,
            underlying_price,bid,ask,midpoint,conservative_mark,entry_fill,return_pct,
            unrealized_pnl,spread_dollars,spread_percent,mfe_pct,mae_pct,peak_return_pct,
            peak_unrealized_pnl,time_since_entry_seconds,update_status
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(mirror_trade_id,observed_at) DO NOTHING""", (
            mark_id,row["mirror_trade_id"],row["opportunity_id"],row["symbol"],row.get("option_symbol"),
            observed_at,underlying_price,bid,ask,midpoint,mark,entry_fill,return_pct,pnl,
            spread,spread_pct,mfe,mae,mfe,peak_pnl,elapsed,update_status))
        inserted = cursor.rowcount > 0
        cursor.close()
        if not inserted:
            existing = self.repository._fetchone(connection,
                "SELECT * FROM mirror_execution_marks WHERE mirror_trade_id=? AND observed_at=?",
                (row["mirror_trade_id"], observed_at)) or {}
            return {"mark_id": existing.get("mark_id"),
                    "mark": existing.get("conservative_mark"),
                    "return_pct": existing.get("return_pct"),
                    "unrealized_pnl": existing.get("unrealized_pnl"),
                    "mfe_pct": existing.get("mfe_pct"), "mae_pct": existing.get("mae_pct"),
                    "peak_return_pct": existing.get("peak_return_pct"),
                    "peak_unrealized_pnl": existing.get("peak_unrealized_pnl"),
                    "update_status": existing.get("update_status")}
        if return_pct is not None:
            self.repository._execute(connection, """UPDATE mirror_execution_trades SET
                mfe_pct=?,mae_pct=?,peak_return_pct=?,peak_unrealized_pnl=?
                WHERE mirror_trade_id=?""", (mfe,mae,mfe,peak_pnl,row["mirror_trade_id"])).close()
        return {"mark_id": mark_id, "mark": mark, "return_pct": return_pct, "unrealized_pnl": pnl,
                "mfe_pct": mfe, "mae_pct": mae, "peak_return_pct": mfe,
                "peak_unrealized_pnl": peak_pnl, "update_status": update_status}

    def record_quote_unavailable(self, row, now, *, underlying_price=None):
        with self.repository.connection() as connection:
            return self._snapshot(connection, row, None, now, underlying_price=underlying_price,
                                  update_status="QUOTE_UNAVAILABLE")

    def update_mark(self, row, quote, now, *, underlying_price=None):
        bid, ask = _number(quote.get("bid")), _number(quote.get("ask"))
        mark = _exit_fill(bid, ask)
        value = mark * MIRROR_MULTIPLIER
        pnl = value - float(row["total_debit"])
        with self.repository.connection() as connection:
            self.repository._execute(connection, """UPDATE mirror_execution_trades SET current_bid=?,current_ask=?,
                current_mark=?,current_value=?,unrealized_pnl=?,last_quote_at=?,updated_at=? WHERE opportunity_id=?""",
                (bid, ask, mark, value, pnl, utc_iso(now), utc_iso(now), row["opportunity_id"])).close()
            return self._snapshot(connection, row, quote, now, underlying_price=underlying_price,
                                  conservative_mark=mark)

    def close(self, row, exit_event, quote, now, *, underlying_price=None):
        bid, ask = _number(quote.get("bid")), _number(quote.get("ask"))
        mid, fill = (bid + ask) / 2, _exit_fill(bid, ask)
        value = fill * MIRROR_MULTIPLIER
        pnl = value - float(row["total_debit"])
        return_pct = pnl / float(row["total_debit"]) * 100 if row["total_debit"] else 0
        with self.repository.connection() as connection:
            self.repository._execute(connection, """UPDATE mirror_execution_trades SET
                authoritative_exit_event_id=?,authoritative_exit_at=?,authoritative_exit_reason=?,
                exit_quote_at=?,exit_bid=?,exit_ask=?,exit_mid=?,exit_fill=?,exit_value=?,realized_pnl=?,
                realized_return_percent=?,current_mark=?,current_value=?,unrealized_pnl=0,status='CLOSED',
                disposition_code='MIRROR_CLOSED',updated_at=? WHERE opportunity_id=?""", (
                exit_event.get("id"), utc_iso(_aware(exit_event["event_timestamp"])), exit_event.get("exit_reason"),
                utc_iso(now), bid, ask, mid, fill, value, pnl, return_pct, fill, value, utc_iso(now), row["opportunity_id"],
            )).close()
            snapshot = self._snapshot(connection, row, quote, now, underlying_price=underlying_price,
                                      update_status="CLOSED", conservative_mark=fill)
        self.journal(row["opportunity_id"], row["mirror_trade_id"], "mirror_trade_closed", "MIRROR_CLOSED", now,
                     {"authoritative_exit_reason": exit_event.get("exit_reason"), "realized_pnl": pnl})
        return snapshot

    def exit_pending(self, row, exit_event, now, reason):
        with self.repository.connection() as connection:
            self.repository._execute(connection, """UPDATE mirror_execution_trades SET
                authoritative_exit_event_id=?,authoritative_exit_at=?,authoritative_exit_reason=?,
                status='EXIT_PENDING',disposition_code='MIRROR_EXIT_PENDING',disposition_detail=?,updated_at=?
                WHERE opportunity_id=?""", (exit_event.get("id"), utc_iso(_aware(exit_event["event_timestamp"])),
                exit_event.get("exit_reason"), reason, utc_iso(now), row["opportunity_id"])).close()
        self.journal(row["opportunity_id"], row["mirror_trade_id"], "mirror_exit_pending", "MIRROR_EXIT_PENDING", now, {"reason": reason})

    def journal(self, opportunity_id, trade_id, event_type, reason, now, metadata=None):
        dedup = hashlib.sha256(f"{opportunity_id}|{event_type}|{reason}".encode()).hexdigest()
        with self.repository.connection() as connection:
            self.repository._execute(connection, """INSERT INTO mirror_execution_journal
                (journal_id,dedup_key,opportunity_id,mirror_trade_id,event_type,reason_code,event_at,metadata_json)
                VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(dedup_key) DO NOTHING""", (
                hashlib.sha256(f"{dedup}|journal".encode()).hexdigest(), dedup, opportunity_id, trade_id,
                event_type, reason, utc_iso(now), json.dumps(metadata or {}, sort_keys=True))).close()


def _entry_events(repository):
    return repository.list_trade_event_summaries(limit=5000, event_type="TRADE_ENTERED")


def pending_mirror_entries(repository, latest_results, mirror_repository, *, entry_events=None):
    """Project every undisposed authoritative entry, isolating malformed payloads."""
    by_symbol = {str((result or {}).get("symbol") or symbol).upper(): result
                 for symbol, result in (latest_results or {}).items()} if isinstance(latest_results, dict) else {}
    disposed = mirror_repository.dispositioned_source_signal_ids()
    candidates = []
    for event in reversed(entry_events if entry_events is not None else _entry_events(repository)):
        opportunity_id = event.get("opportunity_id") or event.get("trade_id")
        if not opportunity_id or opportunity_id in disposed:
            continue
        opportunity = repository.get_opportunity(opportunity_id=opportunity_id) or {}
        payload = (opportunity.get("metadata") or {}).get("trade_outcome")
        try:
            record = deserialize_trade_outcome(payload) if payload else None
        except Exception:
            record = None
        if record is None:
            candidates.append({
                "_authoritative_entry_id": opportunity_id,
                "_authoritative_event_id": event.get("id"),
                "_mirror_projection_error": "Authoritative outcome payload is missing or invalid.",
                "symbol": event.get("symbol"), "price": event.get("underlying_price") or event.get("entry_price"),
                "bias": event.get("direction"), "trade_plan": {"direction": event.get("direction")},
            })
            continue
        result = dict(by_symbol.get(record.symbol.upper()) or {})
        result.update({
            "_authoritative_entry_id": opportunity_id, "_authoritative_event_id": event.get("id"),
            "symbol": record.symbol, "price": result.get("price") or event.get("underlying_price") or record.entry,
            "timestamp": record.entry_time or record.timestamp, "confidence": record.confidence,
            "score": event.get("rule_score") if event.get("rule_score") is not None else result.get("score"),
            "bias": record.direction, "trade_plan": {"direction": record.direction, "setup_type": record.setup,
                "trigger_price": record.entry, "technical_stop": record.stop,
                "target_1": record.target_1, "target_2": record.target_2, "target_3": record.target_3},
        })
        candidates.append(result)
    return candidates


def _exit_by_opportunity(repository):
    return {event.get("opportunity_id") or event.get("trade_id"): event
            for event in repository.list_trade_event_summaries(limit=5000, event_type="TRADE_CLOSED")}


def _entry_disposition(candidate, entry_event, provider, now, stale_minutes):
    if candidate.get("_mirror_projection_error"):
        return "MIRROR_AUTHORITATIVE_DATA_FAILURE", candidate["_mirror_projection_error"], None
    direction = (candidate.get("trade_plan") or {}).get("direction") or candidate.get("bias")
    option_type = {"Bullish": "call", "Bearish": "put"}.get(direction)
    if not option_type:
        return "MIRROR_NO_VALID_CONTRACT", "Invalid authoritative CALL/PUT direction.", None
    if (now - _aware(entry_event["event_timestamp"])).total_seconds() > stale_minutes * 60:
        return "MIRROR_STALE_ENTRY", "Authoritative entry exceeded the MIRROR entry-age limit.", None
    ticker, underlying = str(candidate.get("symbol") or "").upper(), _number(candidate.get("price"))
    try:
        expirations, error = provider.expirations(ticker)
        if error:
            return "MIRROR_PROVIDER_FAILURE", str(error)[:240], None
        expiration = preferred_expiration(expirations, _aware(entry_event["event_timestamp"]).date())
        if not expiration:
            return "MIRROR_NO_VALID_CONTRACT", "No listed expiration available.", None
        contracts, error = provider.chain(ticker, expiration)
        if error:
            return "MIRROR_PROVIDER_FAILURE", str(error)[:240], None
        selected = select_contract(contracts, option_type=option_type, underlying_price=underlying or 0)
        if not selected:
            return "MIRROR_NO_VALID_CONTRACT", "No valid deterministic contract available.", None
        if not _usable_quote(selected):
            return "MIRROR_QUOTE_UNAVAILABLE", "Selected contract has no executable non-inverted bid/ask.", None
        return "MIRROR_OPENED", "One-contract authoritative lifecycle mirror opened.", selected
    except Exception as exc:
        return "MIRROR_PROVIDER_FAILURE", type(exc).__name__, None


def run_mirror_execution(repository, mirror_repository, candidates, *, enabled, scanner_id,
                         run_number=None, now=None, chain_provider=None, quote_provider=None,
                         experiment_start_date=None, stale_minutes=60, underlying_prices=None,
                         entry_events=None, exit_events=None):
    """Reconcile entries and authoritative exits exactly once; never place an order."""
    now = now or datetime.now(timezone.utc)
    LOGGER.info(json.dumps({"event": "mirror_cycle_started", "scanner_id": scanner_id,
                            "run_number": run_number, "enabled": enabled}, sort_keys=True))
    if not enabled:
        mirror_repository.save_runtime_state(scanner_id, enabled=False, status="DISABLED", now=now,
                                             experiment_start_date=experiment_start_date)
        return {"status": "DISABLED", "opened": 0, "unexecutable": 0, "closed": 0, "pending": 0}
    provider = chain_provider or TradierOptionChainProvider()
    quote_provider = quote_provider or option_quote
    underlying_prices = underlying_prices or {}
    entry_events = {event.get("opportunity_id") or event.get("trade_id"): event for event in
                    (entry_events if entry_events is not None else _entry_events(repository))}
    eligible_entry_ids = {identity for identity, event in entry_events.items()
                          if not experiment_start_date or _aware(event["event_timestamp"]).astimezone(EASTERN).date() >= experiment_start_date}
    existing_ids = mirror_repository.dispositioned_source_signal_ids()
    already_disposed = len(eligible_entry_ids & existing_ids)
    candidates = list(candidates or [])
    LOGGER.info(json.dumps({"event": "mirror_authoritative_handoff", "scanner_id": scanner_id,
                            "entries_received": len(candidates)}, sort_keys=True))
    opened = unexecutable = closed = pending = 0
    disposition_codes = []
    for candidate in candidates:
        opportunity_id = candidate.get("_authoritative_entry_id")
        event = entry_events.get(opportunity_id)
        if not event or (experiment_start_date and _aware(event["event_timestamp"]).astimezone(EASTERN).date() < experiment_start_date):
            continue
        code, detail, contract = _entry_disposition(candidate, event, provider, now, stale_minutes)
        disposition_codes.append(code)
        mirror_repository.record_disposition(candidate, event, code=code, detail=detail, contract=contract, now=now)
        opened += code == "MIRROR_OPENED"
        unexecutable += code != "MIRROR_OPENED"
        LOGGER.info(json.dumps({
            "event": "mirror_authoritative_handoff", "scanner_id": scanner_id,
            "run_number": run_number, "opportunity_id": opportunity_id,
            "symbol": candidate.get("symbol"),
            "disposition": "OPENED" if code == "MIRROR_OPENED" else "UNEXECUTABLE",
            "reason": code,
        }, sort_keys=True))
    exits = {event.get("opportunity_id") or event.get("trade_id"): event for event in
             (exit_events if exit_events is not None else _exit_by_opportunity(repository).values())}
    for row in mirror_repository.open_rows():
        if row["status"] not in {"OPEN", "EXIT_PENDING"}:
            continue
        exit_event = exits.get(row["opportunity_id"])
        quote, error = quote_provider(row["option_symbol"])
        underlying_price = _number(underlying_prices.get(row["symbol"]))
        if exit_event:
            LOGGER.info(json.dumps({"event": "mirror_authoritative_exit_received", "opportunity_id": row["opportunity_id"],
                                    "authoritative_exit_reason": exit_event.get("exit_reason")}, sort_keys=True))
            if error or not quote or not _usable_quote(quote):
                snapshot = mirror_repository.record_quote_unavailable(
                    row, now, underlying_price=underlying_price
                )
                LOGGER.info(json.dumps({"event": "mirror_position_marked",
                    "opportunity_id": row["opportunity_id"], "trade_id": row["mirror_trade_id"],
                    "symbol": row["symbol"], "option_symbol": row["option_symbol"],
                    **snapshot}, sort_keys=True))
                mirror_repository.exit_pending(row, exit_event, now, str(error or "Executable exit quote unavailable.")[:240])
                pending += 1
            else:
                snapshot = mirror_repository.close(
                    row, exit_event, quote, now, underlying_price=underlying_price
                )
                LOGGER.info(json.dumps({"event": "mirror_position_marked",
                    "opportunity_id": row["opportunity_id"], "trade_id": row["mirror_trade_id"],
                    "symbol": row["symbol"], "option_symbol": row["option_symbol"],
                    **snapshot}, sort_keys=True))
                closed += 1
        elif not error and quote and _usable_quote(quote):
            snapshot = mirror_repository.update_mark(
                row, quote, now, underlying_price=underlying_price
            )
            LOGGER.info(json.dumps({"event": "mirror_position_updated", "opportunity_id": row["opportunity_id"]}, sort_keys=True))
            LOGGER.info(json.dumps({"event": "mirror_position_marked",
                "opportunity_id": row["opportunity_id"], "trade_id": row["mirror_trade_id"],
                "symbol": row["symbol"], "option_symbol": row["option_symbol"],
                **snapshot}, sort_keys=True))
        else:
            snapshot = mirror_repository.record_quote_unavailable(
                row, now, underlying_price=underlying_price
            )
            LOGGER.info(json.dumps({"event": "mirror_position_marked",
                "opportunity_id": row["opportunity_id"], "trade_id": row["mirror_trade_id"],
                "symbol": row["symbol"], "option_symbol": row["option_symbol"],
                **snapshot}, sort_keys=True))
    pending_total = mirror_repository.status_count("EXIT_PENDING")
    status = "DEGRADED" if pending_total or any(code in disposition_codes for code in {
        "MIRROR_PROVIDER_FAILURE", "MIRROR_AUTHORITATIVE_DATA_FAILURE"
    }) else "ACTIVE"
    mirror_repository.save_runtime_state(scanner_id, enabled=True, status=status, now=now,
                                         experiment_start_date=experiment_start_date)
    result = {"status": status, "opened": opened, "unexecutable": unexecutable,
              "closed": closed, "pending": pending_total, "entries_received": len(eligible_entry_ids),
              "already_disposed": already_disposed,
              "dispositions_total": mirror_repository.disposition_count()}
    LOGGER.info(json.dumps({"event": "mirror_cycle_completed", "scanner_id": scanner_id, **result}, sort_keys=True))
    return result


def mirror_summary(rows):
    opened = [row for row in rows if row["opened_at"]]
    closed = [row for row in rows if row["status"] == "CLOSED"]
    open_rows = [row for row in rows if row["status"] in {"OPEN", "EXIT_PENDING"}]
    pnl = [float(row["realized_pnl"] or 0) for row in closed]
    winners, losers = [x for x in pnl if x > 0], [x for x in pnl if x < 0]
    realized = sum(pnl)
    unrealized = sum(float(row["unrealized_pnl"] or 0) for row in open_rows)
    capital = mirror_capital_summary(rows)
    debits = [float(row["total_debit"]) for row in opened if row.get("total_debit") is not None]
    max_drawdown = _max_drawdown(closed)
    return {"authoritative_entries": len(rows), "attempted": len(rows), "opened": len(opened),
            "unexecutable": len(rows) - len(opened), "open_positions": len(open_rows), "closed_trades": len(closed),
            "realized_pnl": realized, "unrealized_pnl": unrealized, "total_pnl": realized + unrealized,
            "winning_trades": len(winners), "losing_trades": len(losers),
            "win_rate": len(winners) / len(closed) * 100 if closed else 0,
            "average_winner": sum(winners) / len(winners) if winners else 0,
            "average_loser": sum(losers) / len(losers) if losers else 0,
            "profit_factor": sum(winners) / abs(sum(losers)) if losers else math.inf if winners else 0,
            "current_capital_required": capital["current_capital_required"],
            "peak_capital_required": capital["peak_capital_required"],
            "cumulative_gross_debit": capital["cumulative_gross_debit"],
            "open_contracts": capital["open_contracts"],
            "return_on_peak_capital_percent": capital["return_on_peak_capital_percent"],
            "average_entry_debit": (
                sum(debits) / len(debits) if len(debits) == len(opened) and debits
                else 0 if not opened else None
            ),
            "largest_entry_debit": (
                max(debits) if len(debits) == len(opened) and debits
                else 0 if not opened else None
            ), "max_drawdown": max_drawdown,
            "max_drawdown_percent_of_peak_capital": (
                max_drawdown / capital["peak_capital_required"] * 100
                if capital["peak_capital_required"] else 0
                if capital["peak_capital_required"] == 0 else None
            )}


def mirror_capital_summary(rows):
    """Derive capital requirements only from immutable persisted MIRROR debits."""
    opened = [row for row in rows if row.get("opened_at")]
    open_rows = [row for row in opened if str(row.get("status") or "").upper() in {"OPEN", "EXIT_PENDING"}]
    open_contracts = sum(int(row.get("quantity") or 0) for row in open_rows)
    current = (
        sum(float(row["total_debit"]) for row in open_rows)
        if all(row.get("total_debit") is not None for row in open_rows) else None
    )
    cumulative = (
        sum(float(row["total_debit"]) for row in opened)
        if all(row.get("total_debit") is not None for row in opened) else None
    )
    peak_known = all(
        row.get("total_debit") is not None
        and (str(row.get("status") or "").upper() in {"OPEN", "EXIT_PENDING"} or row.get("exit_quote_at"))
        for row in opened
    )
    peak = _peak_capital(opened) if peak_known else None
    pnl_known = all(
        row.get("realized_pnl") is not None
        if str(row.get("status") or "").upper() == "CLOSED"
        else row.get("unrealized_pnl") is not None
        for row in opened
    )
    total_pnl = sum(
        float(row["realized_pnl"])
        if str(row.get("status") or "").upper() == "CLOSED"
        else float(row["unrealized_pnl"])
        for row in opened
    ) if pnl_known else None
    return {
        "current_capital_required": current,
        "peak_capital_required": peak,
        "cumulative_gross_debit": cumulative,
        "open_contracts": open_contracts,
        "return_on_peak_capital_percent": (
            total_pnl / peak * 100 if total_pnl is not None and peak else None
        ),
        "capital_limit": None,
    }


def _peak_capital(rows):
    events = []
    for row in rows:
        events.append((_aware(row["opened_at"]), 1, float(row["total_debit"] or 0)))
        if row["exit_quote_at"]:
            events.append((_aware(row["exit_quote_at"]), 0, -float(row["total_debit"] or 0)))
    current = peak = 0
    for _, _, change in sorted(events, key=lambda item: (item[0], item[1])):
        current += change
        peak = max(peak, current)
    return peak


def _max_drawdown(rows):
    equity = peak = drawdown = 0
    for row in sorted(rows, key=lambda item: item["exit_quote_at"] or ""):
        equity += float(row["realized_pnl"] or 0)
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown
