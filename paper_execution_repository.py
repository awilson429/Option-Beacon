"""Authoritative SQL repository for PAPER execution state."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone

from option_position_tracker import PaperOptionPosition, _deserialize, _serialize
from option_trade_engine import PaperOptionTrade
from trade_repository import parse_utc, utc_iso


class PaperExecutionRepository:
    """Adapts TradeRepository into ledger, position-store, and journal interfaces."""

    def __init__(self, repository, *, initialize=True):
        self.repository = repository
        if initialize:
            self.initialize()

    def initialize(self):
        with self.repository.connection() as connection:
            for ddl in (
                """CREATE TABLE IF NOT EXISTS paper_execution_positions (
                    position_id TEXT PRIMARY KEY, trade_id TEXT NOT NULL UNIQUE,
                    opportunity_id TEXT, symbol TEXT NOT NULL, option_symbol TEXT NOT NULL,
                    option_type TEXT NOT NULL, strike REAL NOT NULL, expiration TEXT NOT NULL,
                    quantity INTEGER NOT NULL, entry_underlying_price REAL,
                    entry_option_price REAL NOT NULL, total_debit REAL NOT NULL,
                    current_option_price REAL NOT NULL, current_value REAL NOT NULL,
                    unrealized_pnl_dollars REAL NOT NULL, unrealized_return_pct REAL NOT NULL,
                    mfe_dollars REAL NOT NULL, mae_dollars REAL NOT NULL,
                    mfe_pct REAL NOT NULL, mae_pct REAL NOT NULL, opened_at TEXT NOT NULL,
                    last_updated_at TEXT NOT NULL, status TEXT NOT NULL,
                    stop_threshold REAL, target_threshold REAL, max_hold_minutes INTEGER,
                    eod_cutoff TEXT, metadata_json TEXT NOT NULL
                )""",
                """CREATE TABLE IF NOT EXISTS paper_execution_trades (
                    trade_id TEXT PRIMARY KEY, source_signal_id TEXT NOT NULL UNIQUE,
                    opportunity_id TEXT, symbol TEXT NOT NULL, option_symbol TEXT,
                    option_type TEXT, strike REAL, expiration TEXT, quantity INTEGER,
                    entry_option_price REAL, total_debit REAL, opened_at TEXT,
                    exit_option_price REAL, exit_value REAL, realized_pnl_dollars REAL,
                    realized_return_pct REAL, exit_reason TEXT, duration_minutes INTEGER,
                    mfe_dollars REAL, mae_dollars REAL, mfe_pct REAL, mae_pct REAL,
                    closed_at TEXT, status TEXT NOT NULL, execution_mode TEXT NOT NULL,
                    contract_metadata_json TEXT NOT NULL, created_at TEXT NOT NULL
                )""",
                """CREATE TABLE IF NOT EXISTS paper_execution_journal (
                    journal_id TEXT PRIMARY KEY, dedup_key TEXT NOT NULL UNIQUE,
                    scanner_id TEXT, run_number INTEGER, trade_id TEXT, position_id TEXT,
                    symbol TEXT, option_symbol TEXT, accepted INTEGER NOT NULL,
                    reason_code TEXT NOT NULL, risk_state_json TEXT NOT NULL,
                    allocation_dollars REAL, quantity INTEGER, created_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                )""",
                """CREATE TABLE IF NOT EXISTS paper_execution_runtime_state (
                    scanner_id TEXT PRIMARY KEY, simulation_profile TEXT NOT NULL,
                    effective_min_score REAL NOT NULL,
                    resolved_config_json TEXT NOT NULL, updated_at TEXT NOT NULL
                )""",
            ):
                self.repository._execute(connection, ddl).close()
            self.repository._execute(connection, "CREATE INDEX IF NOT EXISTS idx_paper_positions_status ON paper_execution_positions(status)").close()
            self.repository._execute(connection, "CREATE INDEX IF NOT EXISTS idx_paper_journal_created ON paper_execution_journal(created_at)").close()

    def save_runtime_config(self, scanner_id, config):
        """Persist the Railway worker's effective non-secret execution policy."""
        from execution_config import resolved_execution_config

        scanner_id = str(scanner_id or "optionbeacon-scanner")
        state = resolved_execution_config(config)
        now = utc_iso()
        with self.repository.connection() as connection:
            existing = self.repository._fetchone(
                connection,
                "SELECT scanner_id FROM paper_execution_runtime_state WHERE scanner_id=?",
                (scanner_id,),
            )
            if existing:
                self.repository._execute(connection, """
                    UPDATE paper_execution_runtime_state SET simulation_profile=?,
                    effective_min_score=?,resolved_config_json=?,updated_at=?
                    WHERE scanner_id=?
                """, (
                    config.simulation_profile, config.min_beacon_score,
                    json.dumps(state, sort_keys=True), now, scanner_id,
                )).close()
            else:
                self.repository._execute(connection, """
                    INSERT INTO paper_execution_runtime_state
                    (scanner_id,simulation_profile,effective_min_score,
                     resolved_config_json,updated_at) VALUES (?,?,?,?,?)
                """, (
                    scanner_id, config.simulation_profile, config.min_beacon_score,
                    json.dumps(state, sort_keys=True), now,
                )).close()
        return self.get_runtime_config(scanner_id)

    def get_runtime_config(self, scanner_id=None):
        with self.repository.connection() as connection:
            if scanner_id:
                row = self.repository._fetchone(
                    connection,
                    "SELECT * FROM paper_execution_runtime_state WHERE scanner_id=?",
                    (scanner_id,),
                )
            else:
                row = self.repository._fetchone(
                    connection,
                    "SELECT * FROM paper_execution_runtime_state "
                    "ORDER BY updated_at DESC,scanner_id ASC LIMIT 1",
                )
        if row:
            row["resolved_config"] = json.loads(row["resolved_config_json"])
        return row

    # OptionTradeLedger-compatible API
    def records(self):
        with self.repository.connection() as connection:
            rows = self.repository._fetchall(connection, "SELECT contract_metadata_json FROM paper_execution_trades ORDER BY created_at")
        records = []
        for row in rows:
            try:
                values = json.loads(row["contract_metadata_json"])["capture"]
                values["created_timestamp"] = parse_utc(values["created_timestamp"])
                records.append(PaperOptionTrade(**values))
            except Exception:
                continue
        return records

    def find_source_signal(self, source_signal_id):
        with self.repository.connection() as connection:
            row = self.repository._fetchone(connection, "SELECT contract_metadata_json FROM paper_execution_trades WHERE source_signal_id = ?", (source_signal_id,))
        if not row:
            return None
        values = json.loads(row["contract_metadata_json"])["capture"]
        values["created_timestamp"] = parse_utc(values["created_timestamp"])
        return PaperOptionTrade(**values)

    def append_once(self, record):
        existing = self.find_source_signal(record.source_signal_id)
        if existing:
            return existing
        capture = asdict(record)
        capture["created_timestamp"] = utc_iso(record.created_timestamp)
        with self.repository.connection() as connection:
            try:
                self.repository._execute(connection, """INSERT INTO paper_execution_trades
                    (trade_id,source_signal_id,opportunity_id,symbol,option_symbol,option_type,strike,expiration,
                     status,execution_mode,contract_metadata_json,created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (
                    record.trade_id, record.source_signal_id, record.source_signal_id,
                    record.ticker, record.option_symbol,
                    record.option_type, record.strike, record.expiration, "CAPTURED", "PAPER",
                    json.dumps({"capture": capture}, sort_keys=True), utc_iso(record.created_timestamp),
                )).close()
            except Exception:
                existing = self.find_source_signal(record.source_signal_id)
                if existing:
                    return existing
                raise
        return record

    # OptionPositionStore-compatible API
    def load(self):
        with self.repository.connection() as connection:
            rows = self.repository._fetchall(connection, "SELECT metadata_json FROM paper_execution_positions ORDER BY opened_at")
        positions = []
        for row in rows:
            try:
                positions.append(_deserialize(json.loads(row["metadata_json"])["position"]))
            except Exception:
                continue
        return positions

    def save(self, positions):
        for position in positions:
            self.upsert_position(position)

    def upsert_position(self, position):
        position_id = position.trade_id
        quantity = int(position.quantity or 1)
        current_value = position.current_mid * 100 * quantity
        pnl = (position.current_mid - position.entry_mid) * 100 * quantity
        payload = json.dumps({"position": _serialize(position)}, sort_keys=True)
        values = (
            position_id, position.trade_id, position.ticker, position.option_symbol,
            position.option_type, position.strike, position.expiration, quantity,
            position.last_underlying_price, position.entry_mid, position.total_entry_cost,
            position.current_mid, current_value, pnl, position.current_return_percent,
            position.max_favorable_excursion_percent * position.total_entry_cost / 100,
            position.max_adverse_excursion_percent * position.total_entry_cost / 100,
            position.max_favorable_excursion_percent, position.max_adverse_excursion_percent,
            utc_iso(position.entry_time), utc_iso(position.last_update), position.status, payload,
        )
        with self.repository.connection() as connection:
            existing = self.repository._fetchone(connection, "SELECT position_id,status FROM paper_execution_positions WHERE position_id = ?", (position_id,))
            if existing:
                self.repository._execute(connection, """UPDATE paper_execution_positions SET
                    current_option_price=?,current_value=?,unrealized_pnl_dollars=?,unrealized_return_pct=?,
                    mfe_dollars=?,mae_dollars=?,mfe_pct=?,mae_pct=?,last_updated_at=?,status=?,metadata_json=?
                    WHERE position_id=?""", (
                    position.current_mid,current_value,pnl,position.current_return_percent,
                    position.max_favorable_excursion_percent * position.total_entry_cost / 100,
                    position.max_adverse_excursion_percent * position.total_entry_cost / 100,
                    position.max_favorable_excursion_percent,position.max_adverse_excursion_percent,
                    utc_iso(position.last_update),position.status,payload,position_id,
                )).close()
            else:
                self.repository._execute(connection, """INSERT INTO paper_execution_positions
                    (position_id,trade_id,symbol,option_symbol,option_type,strike,expiration,quantity,
                     entry_underlying_price,entry_option_price,total_debit,current_option_price,current_value,
                     unrealized_pnl_dollars,unrealized_return_pct,mfe_dollars,mae_dollars,mfe_pct,mae_pct,
                     opened_at,last_updated_at,status,metadata_json)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", values).close()
            if position.status != "OPEN" and position.exit_time is not None:
                duration = int((position.exit_time - position.entry_time).total_seconds() / 60)
                self.repository._execute(connection, """UPDATE paper_execution_trades SET
                    quantity=?,entry_option_price=?,total_debit=?,opened_at=?,exit_option_price=?,exit_value=?,
                    realized_pnl_dollars=?,realized_return_pct=?,exit_reason=?,duration_minutes=?,mfe_dollars=?,
                    mae_dollars=?,mfe_pct=?,mae_pct=?,closed_at=?,status=? WHERE trade_id=? AND closed_at IS NULL""", (
                    quantity,position.entry_mid,position.total_entry_cost,utc_iso(position.entry_time),
                    position.exit_mid,(position.exit_mid or 0)*100*quantity,
                    ((position.exit_mid or position.entry_mid)-position.entry_mid)*100*quantity,
                    position.exit_return_percent,position.exit_reason,duration,
                    position.max_favorable_excursion_percent*position.total_entry_cost/100,
                    position.max_adverse_excursion_percent*position.total_entry_cost/100,
                    position.max_favorable_excursion_percent,position.max_adverse_excursion_percent,
                    utc_iso(position.exit_time),"CLOSED",position.trade_id,
                )).close()

    def append(self, *, checked_at, result, trade, decision, scanner_id=None, run_number=None, risk_state=None, execution_config=None, journal_type="ENTRY_DECISION"):
        import hashlib
        identity = f"{getattr(trade, 'trade_id', '')}|{decision.reason}|{utc_iso(checked_at)}"
        dedup = hashlib.sha256(identity.encode()).hexdigest()
        metadata = {
            "paper_fill_price": decision.paper_fill_price,
            "journal_type": journal_type,
        }
        if execution_config is not None:
            metadata.update(
                simulation_profile=execution_config.simulation_profile,
                effective_min_score=execution_config.min_beacon_score,
            )
        with self.repository.connection() as connection:
            if self.repository._fetchone(connection, "SELECT journal_id FROM paper_execution_journal WHERE dedup_key=?", (dedup,)):
                return
            self.repository._execute(connection, """INSERT INTO paper_execution_journal
                (journal_id,dedup_key,scanner_id,run_number,trade_id,position_id,symbol,option_symbol,
                 accepted,reason_code,risk_state_json,allocation_dollars,quantity,created_at,metadata_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                dedup,dedup,scanner_id,run_number,getattr(trade,"trade_id",None),
                getattr(trade,"trade_id",None),str((result or {}).get("symbol") or "").upper(),
                getattr(trade,"option_symbol",None),1 if decision.eligible else 0,decision.reason,
                json.dumps(risk_state or {},sort_keys=True),decision.maximum_cost,decision.position_size,
                utc_iso(checked_at),json.dumps(metadata,sort_keys=True),
            )).close()

    def journal_rows(self, limit=200):
        with self.repository.connection() as connection:
            return self.repository._fetchall(connection, "SELECT * FROM paper_execution_journal ORDER BY created_at DESC LIMIT ?", (limit,))

    def has_disposition(self, opportunity_id):
        """Return whether an authoritative entry already has an audited PAPER decision."""
        return opportunity_id in self.dispositioned_source_signal_ids()

    def dispositioned_source_signal_ids(self):
        """Return authoritative IDs that have an accepted or rejected PAPER decision."""
        with self.repository.connection() as connection:
            rows = self.repository._fetchall(connection, """
                SELECT DISTINCT t.source_signal_id
                FROM paper_execution_trades t
                JOIN paper_execution_journal j ON j.trade_id = t.trade_id
            """)
        return {row["source_signal_id"] for row in rows}

    def append_refresh_failure(self, *, position, reason, checked_at, scanner_id=None, run_number=None):
        from types import SimpleNamespace
        self.append(
            checked_at=checked_at, result={"symbol": position.ticker},
            trade=SimpleNamespace(trade_id=position.trade_id, option_symbol=position.option_symbol),
            decision=SimpleNamespace(
                eligible=False, reason=reason, position_size=position.quantity,
                maximum_cost=position.total_entry_cost, paper_fill_price=None,
            ),
            scanner_id=scanner_id, run_number=run_number,
            risk_state={"position_preserved": True},
            journal_type="POSITION_REFRESH_FAILURE",
        )

    def get_open_positions(self):
        return [position for position in self.load() if position.status == "OPEN"]

    def get_trade_history(self):
        return [position for position in self.load() if position.status != "OPEN"]

    def daily_risk_state(self, now=None):
        from execution_risk import daily_risk_state
        return daily_risk_state(self.load(), now)

    def daily_pnl(self, now=None):
        return self.daily_risk_state(now).realized_pnl

    def daily_loss_count(self, now=None):
        return self.daily_risk_state(now).losses

    def cooldown_state(self, now=None):
        state = self.daily_risk_state(now)
        return {"consecutive_losses": state.consecutive_losses, "last_loss_time": state.last_loss_time}

    def max_concurrent_positions(self):
        return len(self.get_open_positions())

    def duplicate_position_exists(self, trade_id):
        return any(position.trade_id == trade_id and position.status == "OPEN" for position in self.load())

    def counts(self):
        with self.repository.connection() as connection:
            return {
                "positions": self.repository._fetchone(connection, "SELECT COUNT(*) AS count FROM paper_execution_positions")["count"],
                "trades": self.repository._fetchone(connection, "SELECT COUNT(*) AS count FROM paper_execution_trades")["count"],
                "journal": self.repository._fetchone(connection, "SELECT COUNT(*) AS count FROM paper_execution_journal")["count"],
            }
