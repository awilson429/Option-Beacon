"""Separate paper execution and persistence for INDEX INTRADAY."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from trade_repository import utc_iso


EASTERN = ZoneInfo("America/New_York")
FILL_MODEL = "INTRADAY_CONSERVATIVE_QUARTER_SPREAD_V1"
CONTRACT_MULTIPLIER = 100


@dataclass(frozen=True)
class ManagedConfig:
    hard_stop_pct: float = -20.0
    breakeven_activation_pct: float = 15.0
    trailing_activation_pct: float = 25.0
    trailing_giveback_pct: float = 10.0
    max_hold_minutes: int = 45
    forced_eod_close: bool = True
    last_entry_time: time = time(15, 30)
    forced_exit_time: time = time(15, 55)


def _number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def usable_quote(quote, *, max_spread_pct=0.35):
    bid, ask = _number(quote.get("bid")), _number(quote.get("ask"))
    if bid is None or ask is None or bid < 0 or ask <= 0 or bid > ask:
        return False
    midpoint = (bid + ask) / 2
    return bool(midpoint and (ask - bid) / midpoint <= max_spread_pct)


def entry_fill(bid, ask):
    midpoint = (float(bid) + float(ask)) / 2
    return round(midpoint + (float(ask) - midpoint) * 0.25, 4)


def exit_fill(bid, ask):
    midpoint = (float(bid) + float(ask)) / 2
    return round(midpoint - (midpoint - float(bid)) * 0.25, 4)


def select_contracts(chains, option_type, underlying_price, signal_date):
    """Return immutable best liquid contracts for both 0DTE and 1DTE."""
    selected = []
    for target_dte in (0, 1):
        candidates = []
        for contract in chains:
            expiration = contract.get("expiration") or contract.get("expiration_date")
            try:
                dte = (date.fromisoformat(str(expiration)) - signal_date).days
            except ValueError:
                continue
            if dte != target_dte or str(contract.get("option_type", "")).lower() != option_type:
                continue
            if not usable_quote(contract):
                continue
            greeks = contract.get("greeks") or {}
            delta = _number(contract.get("delta"))
            delta = _number(greeks.get("delta")) if delta is None else delta
            delta_distance = abs(abs(delta) - 0.525) if delta is not None else 0.20
            strike_distance = abs(float(contract.get("strike", underlying_price)) - underlying_price) / underlying_price
            midpoint = (_number(contract.get("bid")) + _number(contract.get("ask"))) / 2
            spread_pct = (_number(contract.get("ask")) - _number(contract.get("bid"))) / midpoint
            # Delta is preferred (0.45-0.60), with ATM distance and liquidity as fallbacks.
            penalty = delta_distance * 4 + strike_distance * 5 + spread_pct
            if delta is not None and not 0.35 <= abs(delta) <= 0.70:
                penalty += 1
            candidates.append((penalty, contract, delta, spread_pct))
        if candidates:
            _, contract, delta, spread_pct = min(candidates, key=lambda item: item[0])
            selected.append({"option_symbol": contract.get("symbol") or contract.get("option_symbol"),
                             "expiration": contract.get("expiration") or contract.get("expiration_date"),
                             "dte": target_dte, "strike": _number(contract.get("strike")),
                             "option_type": option_type, "delta": delta,
                             "bid": _number(contract.get("bid")), "ask": _number(contract.get("ask")),
                             "spread_pct": spread_pct * 100,
                             "volume": int(_number(contract.get("volume")) or 0),
                             "open_interest": int(_number(contract.get("open_interest")) or 0)})
    return selected


def managed_update(position, quote, now, config=ManagedConfig()):
    """Pure option-native state transition; returns auditable updated fields."""
    mark = exit_fill(quote["bid"], quote["ask"])
    entry = float(position["entry_fill"])
    return_pct = (mark / entry - 1) * 100
    mfe = max(float(position.get("mfe_pct") or 0), return_pct)
    mae = min(float(position.get("mae_pct") or 0), return_pct)
    protection = bool(position.get("protection_armed")) or mfe >= config.breakeven_activation_pct
    trailing = bool(position.get("trailing_active")) or mfe >= config.trailing_activation_pct
    stop_pct = config.hard_stop_pct
    if protection: stop_pct = max(stop_pct, 0.0)
    trailing_threshold = mfe - config.trailing_giveback_pct if trailing else None
    if trailing_threshold is not None: stop_pct = max(stop_pct, trailing_threshold)
    opened = datetime.fromisoformat(str(position["opened_at"]).replace("Z", "+00:00"))
    local = now.astimezone(EASTERN)
    reason = None
    if return_pct <= config.hard_stop_pct: reason = "HARD_STOP"
    elif trailing and return_pct <= trailing_threshold: reason = "TRAILING_STOP"
    elif protection and return_pct <= 0: reason = "BREAKEVEN_STOP"
    elif now >= opened + timedelta(minutes=config.max_hold_minutes): reason = "MAX_HOLD"
    elif config.forced_eod_close and local.time() >= config.forced_exit_time: reason = "EOD_CLOSE"
    return {"current_mark": mark, "return_pct": return_pct, "mfe_pct": mfe, "mae_pct": mae,
            "protection_armed": protection, "trailing_active": trailing,
            "management_state": "CLOSED" if reason else "TRAILING" if trailing else "PROFIT_PROTECTION_ARMED" if protection else "OPEN",
            "trailing_threshold_pct": trailing_threshold, "stop_pct": stop_pct,
            "exit_reason": reason, "profit_giveback_pct": max(0, mfe - return_pct) if reason else None}


class IntradayRepository:
    """Additive strategy schema. The dashboard only calls read methods."""

    def __init__(self, repository, *, initialize=True):
        self.repository = repository
        if initialize: self.initialize()

    def initialize(self):
        ddls = (
            """CREATE TABLE IF NOT EXISTS intraday_signals (
                opportunity_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, direction TEXT NOT NULL,
                setup TEXT NOT NULL, confidence INTEGER NOT NULL, underlying_price REAL NOT NULL,
                trigger_price REAL NOT NULL, state TEXT NOT NULL, session_bucket TEXT NOT NULL,
                regime TEXT NOT NULL, reasons_json TEXT NOT NULL, cross_market_json TEXT NOT NULL,
                detected_at TEXT NOT NULL, updated_at TEXT NOT NULL, closed_at TEXT, close_reason TEXT)""",
            """CREATE TABLE IF NOT EXISTS intraday_paper_trades (
                trade_id TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL, variant TEXT NOT NULL,
                symbol TEXT NOT NULL, direction TEXT NOT NULL, option_symbol TEXT NOT NULL,
                option_type TEXT NOT NULL, expiration TEXT NOT NULL, dte INTEGER NOT NULL, strike REAL,
                delta REAL, quantity INTEGER NOT NULL, contract_multiplier INTEGER NOT NULL,
                underlying_entry_price REAL, entry_bid REAL, entry_ask REAL, entry_fill REAL,
                spread_percent REAL, open_interest INTEGER, option_volume INTEGER, total_debit REAL,
                status TEXT NOT NULL, management_state TEXT NOT NULL, opened_at TEXT NOT NULL,
                current_mark REAL, mfe_pct REAL NOT NULL, mae_pct REAL NOT NULL,
                protection_armed INTEGER NOT NULL, trailing_active INTEGER NOT NULL,
                trailing_threshold_pct REAL, stop_pct REAL, exit_fill REAL, exit_reason TEXT,
                closed_at TEXT, realized_pnl REAL, realized_return_percent REAL,
                profit_giveback_pct REAL, fill_model TEXT NOT NULL, config_json TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(opportunity_id,variant,dte))""",
            """CREATE TABLE IF NOT EXISTS intraday_paper_journal (
                journal_id TEXT PRIMARY KEY, dedup_key TEXT NOT NULL UNIQUE, opportunity_id TEXT,
                trade_id TEXT, event_type TEXT NOT NULL, event_at TEXT NOT NULL, payload_json TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS intraday_runtime_state (
                scanner_id TEXT PRIMARY KEY, status TEXT NOT NULL, last_cycle_at TEXT,
                symbols_processed INTEGER, call_count INTEGER, duration_ms REAL,
                last_error TEXT, fill_model TEXT NOT NULL, updated_at TEXT NOT NULL)""",
        )
        with self.repository.connection() as connection:
            for ddl in ddls: self.repository._execute(connection, ddl).close()

    def save_signal(self, candidate, state="ARMED"):
        row = asdict(candidate) if hasattr(candidate, "__dataclass_fields__") else dict(candidate)
        now = utc_iso()
        with self.repository.connection() as connection:
            existing = self.repository._fetchone(connection, "SELECT opportunity_id FROM intraday_signals WHERE opportunity_id=?", (row["opportunity_id"],))
            if not existing:
                self.repository._execute(connection, """INSERT INTO intraday_signals
                    (opportunity_id,symbol,direction,setup,confidence,underlying_price,trigger_price,state,
                    session_bucket,regime,reasons_json,cross_market_json,detected_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (row["opportunity_id"], row["symbol"], row["direction"],
                    row["setup"], row["confidence"], row.get("price", row.get("underlying_price")),
                    row.get("trigger", row.get("trigger_price")), state, row["session_bucket"], row["regime"],
                    json.dumps(row.get("reasons", [])), json.dumps(row.get("cross_market", {}), sort_keys=True),
                    utc_iso(row["detected_at"]), now)).close()
        return self.signal(row["opportunity_id"])

    def signal(self, opportunity_id):
        with self.repository.connection() as connection:
            return self.repository._fetchone(connection, "SELECT * FROM intraday_signals WHERE opportunity_id=?", (opportunity_id,))

    def transition_signal(self, opportunity_id, expected, target, *, reason=None, now=None):
        from intraday_strategy import transition
        transition(expected, target)
        now = now or datetime.now(timezone.utc)
        with self.repository.connection() as connection:
            cursor = self.repository._execute(connection, """UPDATE intraday_signals SET state=?,updated_at=?,
                closed_at=?,close_reason=? WHERE opportunity_id=? AND state=?""",
                (str(getattr(target, "value", target)), utc_iso(now), utc_iso(now) if str(getattr(target, "value", target)) == "CLOSED" else None,
                 reason, opportunity_id, str(getattr(expected, "value", expected))))
            changed = cursor.rowcount == 1; cursor.close()
        return changed

    def open_variants(self, candidate, contract, *, now=None, config=ManagedConfig()):
        now = now or datetime.now(timezone.utc)
        if not usable_quote(contract): return []
        fill = entry_fill(contract["bid"], contract["ask"])
        opened = []
        for variant in ("INTRADAY_MIRROR", "INTRADAY_MANAGED"):
            trade_id = hashlib.sha256(f"{candidate.opportunity_id}|{variant}|{contract['dte']}".encode()).hexdigest()
            values = (trade_id, candidate.opportunity_id, variant, candidate.symbol, candidate.direction,
                      contract["option_symbol"], contract["option_type"], contract["expiration"], contract["dte"],
                      contract.get("strike"), contract.get("delta"), 1, CONTRACT_MULTIPLIER, candidate.price,
                      contract["bid"], contract["ask"], fill, contract.get("spread_pct"), contract.get("open_interest"),
                      contract.get("volume"), fill * CONTRACT_MULTIPLIER, "OPEN", "OPEN", utc_iso(now), fill,
                      0.0, 0.0, 0, 0, FILL_MODEL, json.dumps(asdict(config), default=str, sort_keys=True), utc_iso(now), utc_iso(now))
            with self.repository.connection() as connection:
                try:
                    self.repository._execute(connection, """INSERT INTO intraday_paper_trades
                    (trade_id,opportunity_id,variant,symbol,direction,option_symbol,option_type,expiration,dte,strike,
                    delta,quantity,contract_multiplier,underlying_entry_price,entry_bid,entry_ask,entry_fill,spread_percent,
                    open_interest,option_volume,total_debit,status,management_state,opened_at,current_mark,mfe_pct,mae_pct,
                    protection_armed,trailing_active,fill_model,config_json,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", values).close()
                    opened.append(trade_id)
                except Exception:
                    # Unique key makes retries idempotent across worker restarts.
                    pass
        return opened

    def list_signals(self, limit=100):
        with self.repository.connection() as connection:
            return self.repository._fetchall(connection, "SELECT * FROM intraday_signals ORDER BY updated_at DESC LIMIT ?", (int(limit),))

    def list_trades(self, *, status=None, limit=500):
        sql, params = "SELECT * FROM intraday_paper_trades", []
        if status: sql += " WHERE status=?"; params.append(status)
        sql += " ORDER BY opened_at DESC LIMIT ?"; params.append(int(limit))
        with self.repository.connection() as connection:
            return self.repository._fetchall(connection, sql, tuple(params))

    def update_managed(self, trade_id, quote, *, now=None, config=ManagedConfig()):
        now = now or datetime.now(timezone.utc)
        with self.repository.connection() as connection:
            row = self.repository._fetchone(connection, "SELECT * FROM intraday_paper_trades WHERE trade_id=? AND variant='INTRADAY_MANAGED'", (trade_id,))
        if not row or row.get("status") != "OPEN" or not usable_quote(quote): return row
        update = managed_update(row, quote, now, config)
        mark, reason = update["current_mark"], update["exit_reason"]
        pnl = (mark - float(row["entry_fill"])) * CONTRACT_MULTIPLIER
        with self.repository.connection() as connection:
            self.repository._execute(connection, """UPDATE intraday_paper_trades SET current_mark=?,mfe_pct=?,mae_pct=?,
                protection_armed=?,trailing_active=?,management_state=?,trailing_threshold_pct=?,stop_pct=?,
                status=?,exit_fill=?,exit_reason=?,closed_at=?,realized_pnl=?,realized_return_percent=?,
                profit_giveback_pct=?,updated_at=? WHERE trade_id=?""", (mark, update["mfe_pct"], update["mae_pct"],
                1 if update["protection_armed"] else 0, 1 if update["trailing_active"] else 0,
                update["management_state"], update["trailing_threshold_pct"], update["stop_pct"],
                "CLOSED" if reason else "OPEN", mark if reason else None, reason,
                utc_iso(now) if reason else None, pnl if reason else None, update["return_pct"] if reason else None,
                update["profit_giveback_pct"], utc_iso(now), trade_id)).close()
        with self.repository.connection() as connection:
            return self.repository._fetchone(connection, "SELECT * FROM intraday_paper_trades WHERE trade_id=?", (trade_id,))

    def close_mirror(self, opportunity_id, quote, *, reason="UNDERLYING_SIGNAL_CLOSED", now=None):
        now = now or datetime.now(timezone.utc)
        if not usable_quote(quote): return 0
        mark = exit_fill(quote["bid"], quote["ask"])
        with self.repository.connection() as connection:
            rows = self.repository._fetchall(connection, "SELECT * FROM intraday_paper_trades WHERE opportunity_id=? AND variant='INTRADAY_MIRROR' AND status='OPEN'", (opportunity_id,))
            for row in rows:
                pnl = (mark - float(row["entry_fill"])) * CONTRACT_MULTIPLIER
                return_pct = pnl / float(row["total_debit"]) * 100
                self.repository._execute(connection, """UPDATE intraday_paper_trades SET status='CLOSED',management_state='CLOSED',
                    current_mark=?,exit_fill=?,exit_reason=?,closed_at=?,realized_pnl=?,realized_return_percent=?,updated_at=?
                    WHERE trade_id=?""", (mark, mark, reason, utc_iso(now), pnl, return_pct, utc_iso(now), row["trade_id"])).close()
        return len(rows)

    def runtime_state(self):
        with self.repository.connection() as connection:
            return self.repository._fetchone(connection, "SELECT * FROM intraday_runtime_state ORDER BY updated_at DESC LIMIT 1")

    def performance(self):
        rows = self.list_trades(status="CLOSED", limit=10000)
        result = {}
        for variant in ("INTRADAY_MIRROR", "INTRADAY_MANAGED"):
            group = [row for row in rows if row["variant"] == variant]
            pnl = sum(float(row.get("realized_pnl") or 0) for row in group)
            result[variant] = {"trades": len(group), "wins": sum(float(row.get("realized_pnl") or 0) > 0 for row in group),
                               "realized_pnl": pnl, "average_return": sum(float(row.get("realized_return_percent") or 0) for row in group) / len(group) if group else 0}
        return result
