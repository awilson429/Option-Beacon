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
            ):
                self.repository._execute(connection, ddl).close()
            self.repository._execute(connection, "CREATE INDEX IF NOT EXISTS idx_mirror_status ON mirror_execution_trades(status)").close()
            self.repository._execute(connection, "CREATE INDEX IF NOT EXISTS idx_mirror_journal_at ON mirror_execution_journal(event_at)").close()

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

    def get(self, opportunity_id):
        with self.repository.connection() as connection:
            return self.repository._fetchone(connection, "SELECT * FROM mirror_execution_trades WHERE opportunity_id=?", (opportunity_id,))

    def dispositioned_source_signal_ids(self):
        return {row["opportunity_id"] for row in self.rows()}

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
        return self.get(opportunity_id)

    def update_mark(self, row, quote, now):
        bid, ask = _number(quote.get("bid")), _number(quote.get("ask"))
        mark = _exit_fill(bid, ask)
        value = mark * MIRROR_MULTIPLIER
        pnl = value - float(row["total_debit"])
        with self.repository.connection() as connection:
            self.repository._execute(connection, """UPDATE mirror_execution_trades SET current_bid=?,current_ask=?,
                current_mark=?,current_value=?,unrealized_pnl=?,last_quote_at=?,updated_at=? WHERE opportunity_id=?""",
                (bid, ask, mark, value, pnl, utc_iso(now), utc_iso(now), row["opportunity_id"])).close()

    def close(self, row, exit_event, quote, now):
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
        self.journal(row["opportunity_id"], row["mirror_trade_id"], "mirror_trade_closed", "MIRROR_CLOSED", now,
                     {"authoritative_exit_reason": exit_event.get("exit_reason"), "realized_pnl": pnl})

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
    return [event for event in repository.list_trade_events(limit=5000) if event.get("event_type") == "TRADE_ENTERED"]


def pending_mirror_entries(repository, latest_results, mirror_repository):
    """Project every undisposed authoritative entry, isolating malformed payloads."""
    by_symbol = {str((result or {}).get("symbol") or symbol).upper(): result
                 for symbol, result in (latest_results or {}).items()} if isinstance(latest_results, dict) else {}
    disposed = mirror_repository.dispositioned_source_signal_ids()
    candidates = []
    for event in reversed(_entry_events(repository)):
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
            for event in repository.list_trade_events(limit=5000) if event.get("event_type") == "TRADE_CLOSED"}


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
                         experiment_start_date=None, stale_minutes=60):
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
    entry_events = {event.get("opportunity_id") or event.get("trade_id"): event for event in _entry_events(repository)}
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
    exits = _exit_by_opportunity(repository)
    for row in mirror_repository.rows():
        if row["status"] not in {"OPEN", "EXIT_PENDING"}:
            continue
        exit_event = exits.get(row["opportunity_id"])
        quote, error = quote_provider(row["option_symbol"])
        if exit_event:
            LOGGER.info(json.dumps({"event": "mirror_authoritative_exit_received", "opportunity_id": row["opportunity_id"],
                                    "authoritative_exit_reason": exit_event.get("exit_reason")}, sort_keys=True))
            if error or not quote or not _usable_quote(quote):
                mirror_repository.exit_pending(row, exit_event, now, str(error or "Executable exit quote unavailable.")[:240])
                pending += 1
            else:
                mirror_repository.close(row, exit_event, quote, now)
                closed += 1
        elif not error and quote and _usable_quote(quote):
            mirror_repository.update_mark(row, quote, now)
            LOGGER.info(json.dumps({"event": "mirror_position_updated", "opportunity_id": row["opportunity_id"]}, sort_keys=True))
    open_state = mirror_repository.rows()
    pending_total = sum(row["status"] == "EXIT_PENDING" for row in open_state)
    status = "DEGRADED" if pending_total or any(code in disposition_codes for code in {
        "MIRROR_PROVIDER_FAILURE", "MIRROR_AUTHORITATIVE_DATA_FAILURE"
    }) else "ACTIVE"
    mirror_repository.save_runtime_state(scanner_id, enabled=True, status=status, now=now,
                                         experiment_start_date=experiment_start_date)
    result = {"status": status, "opened": opened, "unexecutable": unexecutable,
              "closed": closed, "pending": pending_total, "entries_received": len(eligible_entry_ids),
              "already_disposed": already_disposed,
              "dispositions_total": len(mirror_repository.dispositioned_source_signal_ids())}
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
    debits = [float(row["total_debit"] or 0) for row in opened]
    peak_capital = _peak_capital(opened)
    max_drawdown = _max_drawdown(closed)
    return {"authoritative_entries": len(rows), "attempted": len(rows), "opened": len(opened),
            "unexecutable": len(rows) - len(opened), "open_positions": len(open_rows), "closed_trades": len(closed),
            "realized_pnl": realized, "unrealized_pnl": unrealized, "total_pnl": realized + unrealized,
            "winning_trades": len(winners), "losing_trades": len(losers),
            "win_rate": len(winners) / len(closed) * 100 if closed else 0,
            "average_winner": sum(winners) / len(winners) if winners else 0,
            "average_loser": sum(losers) / len(losers) if losers else 0,
            "profit_factor": sum(winners) / abs(sum(losers)) if losers else math.inf if winners else 0,
            "current_capital_required": sum(float(row["total_debit"] or 0) for row in open_rows),
            "peak_capital_required": peak_capital, "cumulative_gross_debit": sum(debits),
            "average_entry_debit": sum(debits) / len(debits) if debits else 0,
            "largest_entry_debit": max(debits, default=0), "max_drawdown": max_drawdown,
            "max_drawdown_percent_of_peak_capital": max_drawdown / peak_capital * 100 if peak_capital else 0}


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
