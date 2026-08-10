"""Forward-only MIRROR V2 research shadow; never submits broker orders."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
from datetime import date, datetime, timezone

from mirror_execution import MIRROR_MULTIPLIER, _aware, _entry_fill, _exit_fill, _number, _usable_quote
from option_trade_engine import TradierOptionChainProvider, normalized_contracts, preferred_expiration
from trade_repository import utc_iso
from tradier_options import option_quote


V2_FILL_MODEL = "MIRROR_V2_CONSERVATIVE_QUARTER_SPREAD_V1"
V2_MAX_SPREAD_PERCENT = 12.5
V2_MAX_MONEYNESS_PERCENT = 0.5
V2_TARGET_PERCENT = 10.0
V2_STOP_PERCENT = -10.0
LOGGER = logging.getLogger(__name__)


def mirror_v2_enabled(environ=None):
    value = (environ or os.environ).get("OPTIONBEACON_MIRROR_V2_SHADOW_ENABLED", "false")
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def mirror_v2_experiment_start(environ=None):
    value = str((environ or os.environ).get("MIRROR_V2_EXPERIMENT_START_DATE", "")).strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


class CachedChainProvider:
    """One-cycle read-through cache shared by CONTROL and V2."""

    def __init__(self, provider=None):
        self.provider = provider or TradierOptionChainProvider()
        self._expirations = {}
        self._chains = {}

    def expirations(self, ticker):
        key = str(ticker).upper()
        if key not in self._expirations:
            self._expirations[key] = self.provider.expirations(ticker)
        return self._expirations[key]

    def chain(self, ticker, expiration):
        key = (str(ticker).upper(), str(expiration))
        if key not in self._chains:
            self._chains[key] = self.provider.chain(ticker, expiration)
        return self._chains[key]


class MirrorV2Repository:
    def __init__(self, repository, *, initialize=True):
        self.repository = repository
        if initialize:
            self.initialize()

    def initialize(self):
        ddls = (
            """CREATE TABLE IF NOT EXISTS mirror_v2_shadow_trades (
                v2_trade_id TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL UNIQUE,
                symbol TEXT NOT NULL, direction TEXT, decision TEXT NOT NULL,
                rejection_reasons_json TEXT NOT NULL, selected_contract_json TEXT NOT NULL,
                considered_contracts_json TEXT NOT NULL, option_symbol TEXT, option_type TEXT,
                strike REAL, expiration TEXT, dte INTEGER, underlying_entry_price REAL,
                moneyness_percent REAL, entry_bid REAL, entry_ask REAL, entry_mid REAL,
                entry_fill REAL, spread_dollars REAL, spread_percent REAL, total_debit REAL,
                target_percent REAL NOT NULL, stop_percent REAL NOT NULL, status TEXT NOT NULL,
                opened_at TEXT, current_mark REAL, current_return_percent REAL,
                mfe_percent REAL, mae_percent REAL, exit_at TEXT, exit_fill REAL,
                exit_reason TEXT, realized_pnl REAL, realized_return_percent REAL,
                fill_model TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS mirror_v2_shadow_marks (
                mark_id TEXT PRIMARY KEY, v2_trade_id TEXT NOT NULL, opportunity_id TEXT NOT NULL,
                observed_at TEXT NOT NULL, bid REAL, ask REAL, midpoint REAL,
                conservative_mark REAL, return_percent REAL, unrealized_pnl REAL,
                mfe_percent REAL, mae_percent REAL, update_status TEXT NOT NULL,
                UNIQUE(v2_trade_id,observed_at)
            )""",
            """CREATE TABLE IF NOT EXISTS mirror_v2_shadow_runtime_state (
                scanner_id TEXT PRIMARY KEY, enabled INTEGER NOT NULL, status TEXT NOT NULL,
                experiment_start_date TEXT, last_cycle_at TEXT, last_error TEXT, updated_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS mirror_v2_shadow_comparisons (
                opportunity_id TEXT PRIMARY KEY, authoritative_outcome TEXT,
                control_disposition TEXT, control_contract TEXT, control_pnl REAL,
                v2_decision TEXT NOT NULL, v2_rejection_reasons_json TEXT NOT NULL,
                v2_contract TEXT, v2_pnl REAL, v2_capital REAL, v2_spread_percent REAL,
                v2_moneyness_percent REAL, updated_at TEXT NOT NULL
            )""",
        )
        with self.repository.connection() as connection:
            for ddl in ddls:
                self.repository._execute(connection, ddl).close()
            self.repository._execute(connection, "CREATE INDEX IF NOT EXISTS idx_mirror_v2_status ON mirror_v2_shadow_trades(status)").close()

    def rows(self):
        with self.repository.connection() as connection:
            return self.repository._fetchall(connection, "SELECT * FROM mirror_v2_shadow_trades ORDER BY created_at,opportunity_id")

    def get(self, opportunity_id):
        with self.repository.connection() as connection:
            return self.repository._fetchone(connection, "SELECT * FROM mirror_v2_shadow_trades WHERE opportunity_id=?", (opportunity_id,))

    def dispositioned_source_signal_ids(self):
        return {row["opportunity_id"] for row in self.rows()}

    def comparisons(self):
        with self.repository.connection() as connection:
            return self.repository._fetchall(connection, "SELECT * FROM mirror_v2_shadow_comparisons ORDER BY updated_at,opportunity_id")

    def runtime_state(self):
        with self.repository.connection() as connection:
            return self.repository._fetchone(connection, "SELECT * FROM mirror_v2_shadow_runtime_state ORDER BY updated_at DESC LIMIT 1")

    def save_decision(self, candidate, event, evaluation, now):
        opportunity_id = str(candidate["_authoritative_entry_id"])
        existing = self.get(opportunity_id)
        if existing:
            return existing
        selected = evaluation.get("selected") or {}
        decision = evaluation["decision"]
        bid, ask = _number(selected.get("bid")), _number(selected.get("ask"))
        mid = (bid + ask) / 2 if bid is not None and ask is not None else None
        fill = _entry_fill(bid, ask) if decision == "TAKE" else None
        expiration = selected.get("expiration")
        try:
            dte = (date.fromisoformat(str(expiration)) - _aware(event["event_timestamp"]).date()).days
        except (TypeError, ValueError):
            dte = None
        values = (
            hashlib.sha256(f"{opportunity_id}|MIRROR_V2".encode()).hexdigest(), opportunity_id,
            candidate.get("symbol"), (candidate.get("trade_plan") or {}).get("direction") or candidate.get("bias"),
            decision, json.dumps(evaluation["reasons"], sort_keys=True), json.dumps(selected, sort_keys=True),
            json.dumps(evaluation.get("considered") or [], sort_keys=True), selected.get("option_symbol"),
            selected.get("option_type"), selected.get("strike"), expiration, dte, candidate.get("price"),
            evaluation.get("moneyness_percent"), bid, ask, mid, fill,
            (ask - bid) if bid is not None and ask is not None else None, evaluation.get("spread_percent"),
            fill * MIRROR_MULTIPLIER if fill is not None else None, V2_TARGET_PERCENT, V2_STOP_PERCENT,
            "OPEN" if decision == "TAKE" else "REJECTED", utc_iso(now) if decision == "TAKE" else None,
            fill, 0.0 if fill else None, 0.0 if fill else None, 0.0 if fill else None,
            V2_FILL_MODEL, utc_iso(now), utc_iso(now),
        )
        with self.repository.connection() as connection:
            self.repository._execute(connection, """INSERT INTO mirror_v2_shadow_trades (
                v2_trade_id,opportunity_id,symbol,direction,decision,rejection_reasons_json,
                selected_contract_json,considered_contracts_json,option_symbol,option_type,strike,
                expiration,dte,underlying_entry_price,moneyness_percent,entry_bid,entry_ask,entry_mid,
                entry_fill,spread_dollars,spread_percent,total_debit,target_percent,stop_percent,status,
                opened_at,current_mark,current_return_percent,mfe_percent,mae_percent,fill_model,
                created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", values).close()
        return self.get(opportunity_id)

    def mark(self, row, quote, now, *, fallback_exit_reason=None):
        bid, ask = _number((quote or {}).get("bid")), _number((quote or {}).get("ask"))
        usable = _usable_quote(quote or {})
        mark = _exit_fill(bid, ask) if usable else None
        entry = _number(row.get("entry_fill"))
        ret = (mark / entry - 1) * 100 if mark is not None and entry else None
        pnl = (mark - entry) * MIRROR_MULTIPLIER if ret is not None else None
        mfe = max(v for v in (_number(row.get("mfe_percent")), ret) if v is not None) if ret is not None else _number(row.get("mfe_percent"))
        mae = min(v for v in (_number(row.get("mae_percent")), ret) if v is not None) if ret is not None else _number(row.get("mae_percent"))
        reason = "TARGET_10" if ret is not None and ret >= V2_TARGET_PERCENT else "STOP_10" if ret is not None and ret <= V2_STOP_PERCENT else fallback_exit_reason if ret is not None else None
        status = "CLOSED" if reason else "OPEN"
        observed = utc_iso(now)
        with self.repository.connection() as connection:
            self.repository._execute(connection, """INSERT INTO mirror_v2_shadow_marks
                (mark_id,v2_trade_id,opportunity_id,observed_at,bid,ask,midpoint,conservative_mark,
                return_percent,unrealized_pnl,mfe_percent,mae_percent,update_status)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(v2_trade_id,observed_at) DO NOTHING""", (
                hashlib.sha256(f"{row['v2_trade_id']}|{observed}".encode()).hexdigest(), row["v2_trade_id"],
                row["opportunity_id"], observed, bid, ask, (bid + ask) / 2 if usable else None, mark,
                ret, pnl, mfe, mae, "QUOTE_UNAVAILABLE" if not usable else status)).close()
            self.repository._execute(connection, """UPDATE mirror_v2_shadow_trades SET current_mark=?,
                current_return_percent=?,mfe_percent=?,mae_percent=?,status=?,exit_at=?,exit_fill=?,
                exit_reason=?,realized_pnl=?,realized_return_percent=?,updated_at=? WHERE v2_trade_id=?""", (
                mark, ret, mfe, mae, status, observed if reason else None, mark if reason else None,
                reason, pnl if reason else None, ret if reason else None, observed, row["v2_trade_id"])).close()
        return reason

    def save_runtime(self, scanner_id, enabled, status, now, error=None, experiment_start_date=None):
        values = (1 if enabled else 0, status, str(experiment_start_date or "") or None,
                  utc_iso(now), str(error or "")[:240] or None, utc_iso(now), scanner_id)
        with self.repository.connection() as connection:
            self.repository._execute(connection, """INSERT INTO mirror_v2_shadow_runtime_state
                (enabled,status,experiment_start_date,last_cycle_at,last_error,updated_at,scanner_id) VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(scanner_id) DO UPDATE SET enabled=excluded.enabled,status=excluded.status,
                experiment_start_date=excluded.experiment_start_date,last_cycle_at=excluded.last_cycle_at,
                last_error=excluded.last_error,updated_at=excluded.updated_at""", values).close()

    def save_comparison(self, row, control, authoritative_outcome, now):
        values = (authoritative_outcome, (control or {}).get("disposition_code"),
                  (control or {}).get("option_symbol"), (control or {}).get("realized_pnl"),
                  row["decision"], row["rejection_reasons_json"], row.get("option_symbol"),
                  row.get("realized_pnl"), row.get("total_debit"), row.get("spread_percent"),
                  row.get("moneyness_percent"), utc_iso(now), row["opportunity_id"])
        with self.repository.connection() as connection:
            self.repository._execute(connection, """INSERT INTO mirror_v2_shadow_comparisons
                (authoritative_outcome,control_disposition,control_contract,control_pnl,v2_decision,
                v2_rejection_reasons_json,v2_contract,v2_pnl,v2_capital,v2_spread_percent,
                v2_moneyness_percent,updated_at,opportunity_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(opportunity_id) DO UPDATE SET authoritative_outcome=excluded.authoritative_outcome,
                control_disposition=excluded.control_disposition,control_contract=excluded.control_contract,
                control_pnl=excluded.control_pnl,v2_pnl=excluded.v2_pnl,updated_at=excluded.updated_at""", values).close()


def evaluate_v2_contracts(candidate, event, provider, now, stale_minutes=60):
    reasons = []
    if candidate.get("_mirror_projection_error"):
        return {"decision": "REJECT", "reasons": ["AUTHORITATIVE_DATA_FAILURE"], "considered": []}
    if (now - _aware(event["event_timestamp"])).total_seconds() > stale_minutes * 60:
        return {"decision": "REJECT", "reasons": ["STALE_ENTRY"], "considered": []}
    direction = (candidate.get("trade_plan") or {}).get("direction") or candidate.get("bias")
    option_type = {"Bullish": "call", "Bearish": "put"}.get(direction)
    spot = _number(candidate.get("price"))
    if not option_type or not spot or spot <= 0:
        return {"decision": "REJECT", "reasons": ["INVALID_DIRECTION_OR_SPOT"], "considered": []}
    try:
        expirations, error = provider.expirations(str(candidate.get("symbol") or "").upper())
    except Exception:
        return {"decision": "REJECT", "reasons": ["PROVIDER_FAILURE"], "considered": []}
    if error:
        return {"decision": "REJECT", "reasons": ["PROVIDER_FAILURE"], "considered": []}
    expiration = preferred_expiration(expirations, _aware(event["event_timestamp"]).date())
    if not expiration:
        return {"decision": "REJECT", "reasons": ["NO_EXPIRATION"], "considered": []}
    try:
        chain, error = provider.chain(str(candidate.get("symbol") or "").upper(), expiration)
    except Exception:
        return {"decision": "REJECT", "reasons": ["PROVIDER_FAILURE"], "considered": []}
    if error:
        return {"decision": "REJECT", "reasons": ["PROVIDER_FAILURE"], "considered": []}
    considered = normalized_contracts(chain, option_type)
    enriched = []
    for contract in considered:
        item = dict(contract)
        item["moneyness_percent"] = abs(float(item["strike"]) / spot - 1) * 100
        alternative_reasons = []
        if not _usable_quote(item):
            alternative_reasons.append("MISSING_OR_UNRELIABLE_BID_ASK")
        if item["moneyness_percent"] > V2_MAX_MONEYNESS_PERCENT:
            alternative_reasons.append("NOT_NEAR_ATM")
        if item.get("spread_percent") is None or item["spread_percent"] > V2_MAX_SPREAD_PERCENT:
            alternative_reasons.append("SPREAD_ABOVE_12_5_PERCENT")
        item["estimated_entry_fill"] = _entry_fill(item["bid"], item["ask"]) if _usable_quote(item) else None
        item["estimated_debit"] = item["estimated_entry_fill"] * MIRROR_MULTIPLIER if item["estimated_entry_fill"] is not None else None
        item["eligible"] = not alternative_reasons
        item["rejection_reasons"] = alternative_reasons
        enriched.append(item)
    quoted = [c for c in enriched if _usable_quote(c)]
    eligible = [c for c in quoted if c["moneyness_percent"] <= V2_MAX_MONEYNESS_PERCENT and
                c.get("spread_percent") is not None and c["spread_percent"] <= V2_MAX_SPREAD_PERCENT]
    selected = min(eligible, key=lambda c: (c["moneyness_percent"], c["spread_percent"],
                    -(c.get("open_interest") or 0), -(c.get("volume") or 0), c["option_symbol"])) if eligible else None
    if not quoted:
        reasons.append("MISSING_OR_UNRELIABLE_BID_ASK")
    elif not any(c["moneyness_percent"] <= V2_MAX_MONEYNESS_PERCENT for c in quoted):
        reasons.append("NO_NEAR_ATM_CONTRACT")
    elif not any(c.get("spread_percent") is not None and c["spread_percent"] <= V2_MAX_SPREAD_PERCENT
                 for c in quoted if c["moneyness_percent"] <= V2_MAX_MONEYNESS_PERCENT):
        reasons.append("SPREAD_ABOVE_12_5_PERCENT")
    if not selected and not reasons:
        reasons.append("NO_ELIGIBLE_CONTRACT")
    return {"decision": "TAKE" if selected else "REJECT", "reasons": reasons,
            "selected": selected, "considered": enriched,
            "moneyness_percent": selected.get("moneyness_percent") if selected else None,
            "spread_percent": selected.get("spread_percent") if selected else None}


def run_mirror_v2_shadow(repository, v2_repository, candidates, *, enabled, scanner_id, now=None,
                         chain_provider=None, quote_provider=None, control_repository=None,
                         experiment_start_date=None):
    now = now or datetime.now(timezone.utc)
    LOGGER.info(json.dumps({"event": "mirror_v2_shadow_cycle_started", "scanner_id": scanner_id,
                            "enabled": enabled}, sort_keys=True))
    if not enabled:
        v2_repository.save_runtime(scanner_id, False, "DISABLED", now,
                                   experiment_start_date=experiment_start_date)
        return {"status": "DISABLED", "taken": 0, "rejected": 0, "closed": 0}
    provider = chain_provider or CachedChainProvider()
    quote_provider = quote_provider or option_quote
    entries = {e.get("opportunity_id") or e.get("trade_id"): e for e in
               repository.list_trade_event_summaries(limit=5000, event_type="TRADE_ENTERED")}
    taken = rejected = closed = 0
    for candidate in candidates or []:
        identity = candidate.get("_authoritative_entry_id")
        if not identity or v2_repository.get(identity) or identity not in entries:
            continue
        if experiment_start_date and _aware(entries[identity]["event_timestamp"]).date() < experiment_start_date:
            continue
        evaluation = evaluate_v2_contracts(candidate, entries[identity], provider, now)
        v2_repository.save_decision(candidate, entries[identity], evaluation, now)
        taken += evaluation["decision"] == "TAKE"
        rejected += evaluation["decision"] == "REJECT"
        LOGGER.info(json.dumps({"event": "mirror_v2_shadow_decision", "scanner_id": scanner_id,
            "opportunity_id": identity, "symbol": candidate.get("symbol"),
            "decision": evaluation["decision"], "reasons": evaluation["reasons"]}, sort_keys=True))
    exits = {e.get("opportunity_id") or e.get("trade_id"): e for e in
             repository.list_trade_event_summaries(limit=5000, event_type="TRADE_CLOSED")}
    for row in v2_repository.rows():
        if row["status"] != "OPEN":
            continue
        quote, _error = quote_provider(row["option_symbol"])
        authoritative_exit = exits.get(row["opportunity_id"])
        reason = v2_repository.mark(
            row, quote or {}, now,
            fallback_exit_reason="AUTHORITATIVE_EXIT" if authoritative_exit else None,
        )
        if reason:
            closed += 1
        LOGGER.info(json.dumps({"event": "mirror_v2_shadow_position_closed" if reason else "mirror_v2_shadow_position_marked",
            "scanner_id": scanner_id, "opportunity_id": row["opportunity_id"], "exit_reason": reason}, sort_keys=True))
    controls = {r["opportunity_id"]: r for r in (control_repository.rows() if control_repository else [])}
    for row in v2_repository.rows():
        outcome = exits.get(row["opportunity_id"])
        result = "WIN" if outcome and _number(outcome.get("realized_return")) is not None and float(outcome["realized_return"]) > 0 else "LOSS" if outcome else "OPEN"
        v2_repository.save_comparison(row, controls.get(row["opportunity_id"]), result, now)
    v2_repository.save_runtime(scanner_id, True, "ACTIVE", now,
                               experiment_start_date=experiment_start_date)
    result = {"status": "ACTIVE", "taken": taken, "rejected": rejected, "closed": closed}
    LOGGER.info(json.dumps({"event": "mirror_v2_shadow_cycle_completed", "scanner_id": scanner_id,
                            **result}, sort_keys=True))
    return result


def mirror_v2_summary(rows, comparisons=()):
    rows = list(rows or [])
    taken = [r for r in rows if r.get("decision") == "TAKE"]
    closed = [r for r in taken if r.get("status") == "CLOSED"]
    pnl = sum(_number(r.get("realized_pnl")) or 0 for r in closed)
    cumulative = sum(_number(r.get("total_debit")) or 0 for r in taken)
    current = sum(_number(r.get("total_debit")) or 0 for r in taken if r.get("status") == "OPEN")
    sessions = {str(r.get("created_at"))[:10] for r in rows if r.get("created_at")}
    comparisons = list(comparisons or [])
    events = []
    for row in taken:
        debit = _number(row.get("total_debit")) or 0
        if row.get("opened_at"):
            events.append((_aware(row["opened_at"]), 0, debit))
        if row.get("exit_at"):
            events.append((_aware(row["exit_at"]), 1, -debit))
    deployed = peak = 0.0
    for _at, _order, change in sorted(events):
        deployed += change
        peak = max(peak, deployed)
    return {"research_only": True, "evaluated": len(rows), "accepted": len(taken),
            "rejected": len(rows) - len(taken), "completed": len(closed),
            "sessions": len(sessions),
            "participation_percent": len(taken) / len(rows) * 100 if rows else 0.0,
            "winner_destruction": sum(c.get("authoritative_outcome") == "WIN" and
                                      c.get("v2_decision") == "REJECT" for c in comparisons),
            "winners": sum((_number(r.get("realized_pnl")) or 0) > 0 for r in closed),
            "losses": sum((_number(r.get("realized_pnl")) or 0) < 0 for r in closed),
            "net_pnl": pnl, "cumulative_debit": cumulative, "current_capital": current,
            "peak_capital": peak,
            "return_on_cumulative_debit": pnl / cumulative * 100 if cumulative else None,
            "return_on_peak_capital": pnl / peak * 100 if peak else None}
