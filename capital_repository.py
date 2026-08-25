"""Canonical persistence for independent OB/BROAD simulated-capital accounts."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from capital_readiness import (
    AccountSnapshot,
    DrawdownState,
    LaneCapitalConfig,
    capital_efficiency,
    classify_readiness,
    drawdown_state,
    execution_outcome,
)
from trade_repository import parse_utc, utc_iso


LOGGER = logging.getLogger(__name__)


class CapitalRepository:
    def __init__(self, repository, *, configs=None, initialize=True):
        self.repository = repository
        self.configs = configs or {}
        if initialize:
            self.initialize()

    def initialize(self):
        with self.repository.connection() as connection:
            for ddl in (
                """CREATE TABLE IF NOT EXISTS lane_capital_state (
                    lane TEXT PRIMARY KEY, starting_equity REAL NOT NULL,
                    current_equity REAL NOT NULL, cash_available REAL NOT NULL,
                    capital_committed REAL NOT NULL, realized_pnl REAL NOT NULL,
                    unrealized_pnl REAL NOT NULL, fees REAL NOT NULL,
                    slippage REAL NOT NULL, peak_equity REAL NOT NULL,
                    current_drawdown_pct REAL NOT NULL, maximum_drawdown_pct REAL NOT NULL,
                    daily_starting_equity REAL NOT NULL, daily_pnl REAL NOT NULL,
                    open_risk REAL NOT NULL, open_positions INTEGER NOT NULL,
                    risk_state TEXT NOT NULL, readiness_status TEXT NOT NULL,
                    config_json TEXT NOT NULL, metrics_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )""",
                """CREATE TABLE IF NOT EXISTS capital_decisions (
                    decision_id TEXT PRIMARY KEY, lane TEXT NOT NULL,
                    opportunity_id TEXT NOT NULL, symbol TEXT NOT NULL,
                    direction TEXT, decision_state TEXT NOT NULL,
                    reason_code TEXT NOT NULL, explanation TEXT NOT NULL,
                    proposed_contract TEXT, proposed_quantity INTEGER NOT NULL,
                    proposed_capital_required REAL NOT NULL,
                    proposed_dollar_risk REAL NOT NULL,
                    proposed_account_risk_pct REAL NOT NULL,
                    theoretical_entry REAL, realistic_entry REAL, stop_fill REAL,
                    risk_per_contract REAL, drawdown_state TEXT NOT NULL,
                    decided_at TEXT NOT NULL, hypothetical_realistic_pnl REAL,
                    hypothetical_outcome TEXT, metadata_json TEXT NOT NULL
                )""",
                """CREATE TABLE IF NOT EXISTS capital_positions (
                    position_id TEXT PRIMARY KEY, lane TEXT NOT NULL,
                    source_trade_id TEXT NOT NULL, opportunity_id TEXT NOT NULL,
                    symbol TEXT NOT NULL, direction TEXT, strategy TEXT NOT NULL,
                    option_symbol TEXT, strike REAL, expiration TEXT, dte INTEGER,
                    quantity INTEGER NOT NULL, theoretical_entry REAL,
                    realistic_entry REAL NOT NULL, current_premium REAL,
                    realistic_exit REAL, stop_price REAL, targets_json TEXT NOT NULL,
                    capital_committed REAL NOT NULL, initial_dollar_risk REAL NOT NULL,
                    unrealized_pnl REAL NOT NULL, theoretical_pnl REAL,
                    realistic_pnl REAL, fees REAL NOT NULL, slippage REAL NOT NULL,
                    opened_at TEXT NOT NULL, last_mark_at TEXT, closed_at TEXT,
                    status TEXT NOT NULL, metadata_json TEXT NOT NULL,
                    UNIQUE(lane,source_trade_id)
                )""",
                """CREATE TABLE IF NOT EXISTS capital_risk_events (
                    event_id TEXT PRIMARY KEY, lane TEXT NOT NULL,
                    previous_state TEXT, new_state TEXT NOT NULL,
                    reason_code TEXT NOT NULL, current_equity REAL NOT NULL,
                    drawdown_pct REAL NOT NULL, event_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                )""",
                """CREATE TABLE IF NOT EXISTS capital_equity_history (
                    snapshot_id TEXT PRIMARY KEY, lane TEXT NOT NULL,
                    observed_at TEXT NOT NULL, equity REAL NOT NULL,
                    cash_available REAL NOT NULL, capital_committed REAL NOT NULL,
                    realized_pnl REAL NOT NULL, unrealized_pnl REAL NOT NULL,
                    open_risk REAL NOT NULL, drawdown_pct REAL NOT NULL,
                    UNIQUE(lane,observed_at)
                )""",
                """CREATE TABLE IF NOT EXISTS capital_daily_state (
                    lane TEXT NOT NULL, trading_date TEXT NOT NULL,
                    starting_equity REAL NOT NULL, ending_equity REAL,
                    realized_pnl REAL NOT NULL, unrealized_pnl REAL NOT NULL,
                    daily_pnl REAL NOT NULL, entries_locked INTEGER NOT NULL,
                    lock_reason TEXT, updated_at TEXT NOT NULL,
                    PRIMARY KEY(lane,trading_date)
                )""",
            ):
                self.repository._execute(connection, ddl).close()
            for index in (
                "CREATE INDEX IF NOT EXISTS idx_capital_decisions_at ON capital_decisions(decided_at DESC)",
                "CREATE INDEX IF NOT EXISTS idx_capital_positions_lane_status ON capital_positions(lane,status)",
                "CREATE INDEX IF NOT EXISTS idx_capital_equity_lane_at ON capital_equity_history(lane,observed_at)",
            ):
                self.repository._execute(connection, index).close()
        for config in self.configs.values():
            self.ensure_lane(config)

    def ensure_lane(self, config: LaneCapitalConfig, *, now=None):
        now = now or datetime.now(timezone.utc)
        with self.repository.connection() as connection:
            current = self.repository._fetchone(
                connection, "SELECT lane FROM lane_capital_state WHERE lane=?", (config.lane,)
            )
            if current:
                return
            self.repository._execute(connection, """INSERT INTO lane_capital_state
                (lane,starting_equity,current_equity,cash_available,capital_committed,
                 realized_pnl,unrealized_pnl,fees,slippage,peak_equity,
                 current_drawdown_pct,maximum_drawdown_pct,daily_starting_equity,
                 daily_pnl,open_risk,open_positions,risk_state,readiness_status,
                 config_json,metrics_json,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                    config.lane, config.starting_capital, config.starting_capital,
                    config.starting_capital, 0, 0, 0, 0, 0, config.starting_capital,
                    0, 0, config.starting_capital, 0, 0, 0, DrawdownState.NORMAL,
                    "NOT_READY", json.dumps(asdict(config), sort_keys=True),
                    json.dumps({}, sort_keys=True), utc_iso(now),
                )).close()

    def record_decision(self, decision, *, metadata=None):
        payload = decision.to_dict() if hasattr(decision, "to_dict") else dict(decision)
        decided_at = utc_iso(payload["timestamp"])
        identity = "|".join((payload["lane"], payload["opportunity_id"], decided_at,
                             payload["reason_code"]))
        decision_id = hashlib.sha256(identity.encode()).hexdigest()
        with self.repository.connection() as connection:
            self.repository._execute(connection, """INSERT INTO capital_decisions
                (decision_id,lane,opportunity_id,symbol,direction,decision_state,
                 reason_code,explanation,proposed_contract,proposed_quantity,
                 proposed_capital_required,proposed_dollar_risk,
                 proposed_account_risk_pct,theoretical_entry,realistic_entry,
                 stop_fill,risk_per_contract,drawdown_state,decided_at,metadata_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(decision_id) DO NOTHING""", (
                    decision_id,payload["lane"],payload["opportunity_id"],payload["symbol"],
                    payload.get("direction"),payload["state"],payload["reason_code"],
                    payload["explanation"],payload.get("proposed_contract"),
                    int(payload.get("proposed_quantity") or 0),
                    float(payload.get("proposed_capital_required") or 0),
                    float(payload.get("proposed_dollar_risk") or 0),
                    float(payload.get("proposed_account_risk_pct") or 0),
                    payload.get("theoretical_entry"),payload.get("realistic_entry"),
                    payload.get("stop_fill"),payload.get("risk_per_contract"),
                    payload.get("drawdown_state") or DrawdownState.NORMAL,decided_at,
                    json.dumps(metadata or {},sort_keys=True),
                )).close()
        observation = None
        try:
            observation_reader = getattr(
                self.repository, "provenance_observation_for_opportunity", None
            )
            observation = observation_reader(payload["opportunity_id"]) \
                if callable(observation_reader) else None
            link_writer = getattr(self.repository, "record_provenance_decision_link", None)
            if callable(link_writer):
                link_writer(
                    decision_id=decision_id,
                    observation_id=(observation or {}).get("observation_id"),
                    opportunity_id=payload["opportunity_id"], lane=payload["lane"],
                    decision_state=payload["state"], decided_at=payload["timestamp"],
                    link_status="DECIDED" if str(payload["state"]).upper() == "TAKE"
                        else "NO_TRADE",
                    source="capital_repository.record_decision",
                )
        except Exception as exc:
            LOGGER.exception(json.dumps({
                "event": "provenance_capital_decision_link_failed",
                "decision_id": decision_id,
                "opportunity_id": payload["opportunity_id"],
                "lane": payload["lane"],
                "exception_type": type(exc).__name__,
            }, sort_keys=True))
            if observation:
                try:
                    self.repository.mark_provenance_degraded(
                        observation["scan_cycle_id"],
                        f"capital decision link failed: {type(exc).__name__}",
                    )
                except Exception:
                    LOGGER.exception("Could not mark provenance cycle degraded")
        return decision_id

    def recent_decisions(self, *, lane=None, limit=50):
        query = "SELECT * FROM capital_decisions"
        params = []
        if lane:
            query += " WHERE lane=?"; params.append(str(lane).upper())
        query += " ORDER BY decided_at DESC,decision_id DESC LIMIT ?"; params.append(int(limit))
        with self.repository.connection() as connection:
            return self.repository._fetchall(connection, query, tuple(params))

    def record_hypothetical_outcome(self, decision_id, *, realistic_pnl, outcome):
        """Attach later research evidence without touching the capital ledger."""
        with self.repository.connection() as connection:
            self.repository._execute(connection,"""UPDATE capital_decisions SET
                hypothetical_realistic_pnl=?,hypothetical_outcome=?
                WHERE decision_id=? AND decision_state<>'TAKE'""",(
                    float(realistic_pnl),str(outcome),str(decision_id),
                )).close()

    def account_snapshot(self, lane, *, now=None):
        lane = str(lane).upper(); config = self.configs[lane]
        now = now or datetime.now(timezone.utc)
        today = now.astimezone(ZoneInfo("America/New_York")).date().isoformat()
        with self.repository.connection() as connection:
            rows = self.repository._fetchall(
                connection, "SELECT * FROM capital_positions WHERE lane=?", (lane,)
            )
            prior = self.repository._fetchone(
                connection, "SELECT * FROM lane_capital_state WHERE lane=?", (lane,)
            ) or {}
            daily = self.repository._fetchone(connection,
                "SELECT * FROM capital_daily_state WHERE lane=? AND trading_date=?",(lane,today)) or {}
        opened = [row for row in rows if row["status"] == "OPEN"]
        closed = [row for row in rows if row["status"] != "OPEN"]
        realized = sum(float(row.get("realistic_pnl") or 0) for row in closed)
        unrealized = sum(float(row.get("unrealized_pnl") or 0) for row in opened)
        committed = sum(float(row.get("capital_committed") or 0) for row in opened)
        fees = sum(float(row.get("fees") or 0) for row in rows)
        slippage = sum(float(row.get("slippage") or 0) for row in rows)
        current = config.starting_capital + realized + unrealized
        peak = max(config.starting_capital, float(prior.get("peak_equity") or 0), current)
        drawdown = (peak - current) / peak * 100 if peak else 0.0
        maximum_drawdown = max(float(prior.get("maximum_drawdown_pct") or 0), drawdown)
        eastern = ZoneInfo("America/New_York")
        today_closed = [
            row
            for row in closed
            if row.get("closed_at")
            and parse_utc(row["closed_at"]).astimezone(eastern).date().isoformat() == today
        ]
        today_realized = sum(float(row.get("realistic_pnl") or 0) for row in today_closed)
        daily_start = float(daily.get("starting_equity") or current - today_realized - unrealized)
        duplicate = tuple(sorted({f'{row["symbol"].upper()}:{str(row.get("direction") or "").upper()}' for row in opened}))
        return AccountSnapshot(
            lane=lane, starting_equity=config.starting_capital, current_equity=current,
            cash_available=max(0.0,config.starting_capital+realized-committed), capital_committed=committed,
            realized_pnl=realized, unrealized_pnl=unrealized, fees=fees, slippage=slippage,
            peak_equity=peak, current_drawdown_pct=drawdown,
            maximum_drawdown_pct=maximum_drawdown, daily_starting_equity=daily_start,
            daily_pnl=today_realized+unrealized,
            open_risk=sum(float(row.get("initial_dollar_risk") or 0) for row in opened),
            open_positions=len(opened), duplicate_exposures=duplicate,
        )

    def sync_paper_positions(self, positions, *, now=None):
        now = now or datetime.now(timezone.utc)
        with self.repository.connection() as connection:
            trade_rows = self.repository._fetchall(connection,
                "SELECT trade_id,source_signal_id FROM paper_execution_trades")
        opportunities = {row["trade_id"]: row["source_signal_id"] for row in trade_rows}
        decisions = self.recent_decisions(limit=10_000)
        accepted = {(row["lane"],row["opportunity_id"]):row for row in reversed(decisions)
                    if row["decision_state"] == "TAKE"}
        for position in positions:
            opportunity = opportunities.get(position.trade_id)
            if not opportunity:
                continue
            for lane in self.configs:
                decision = accepted.get((lane, opportunity))
                if decision:
                    self._upsert_from_paper(position, opportunity, decision, now=now)
        for lane in self.configs:
            self.refresh_lane_state(lane, now=now)

    def _upsert_from_paper(self, position, opportunity, decision, *, now):
        lane = decision["lane"]; config = self.configs[lane]
        quantity = int(decision["proposed_quantity"] or 0)
        if quantity < 1:
            return
        entry = float(decision["realistic_entry"])
        theoretical_entry = float(decision.get("theoretical_entry") or entry)
        closed = position.status != "OPEN" and position.exit_time is not None
        outcome = execution_outcome(
            quantity=quantity, theoretical_entry=theoretical_entry,
            realistic_entry=entry, exit_bid=position.exit_bid, exit_ask=position.exit_ask,
            config=config,
        ) if closed else None
        if closed and outcome is None and position.exit_mid is not None:
            outcome = execution_outcome(
                quantity=quantity, theoretical_entry=theoretical_entry,
                realistic_entry=entry, exit_bid=position.exit_mid,
                exit_ask=position.exit_mid, config=config,
            )
        if closed:
            unrealized = 0.0; realistic_pnl = (outcome or {}).get("realistic_pnl")
            theoretical_pnl = (outcome or {}).get("theoretical_pnl")
            fees = (outcome or {}).get("fees", config.commission_per_contract*2*quantity)
            slippage = (outcome or {}).get("slippage", 0.0)
            exit_fill = (outcome or {}).get("realistic_exit")
        else:
            bid = position.current_bid if position.current_bid is not None else position.current_mid
            ask = position.current_ask if position.current_ask is not None else position.current_mid
            mark = execution_outcome(quantity=quantity,theoretical_entry=theoretical_entry,
                realistic_entry=entry,exit_bid=bid,exit_ask=ask,config=config)
            unrealized = float((mark or {}).get("realistic_pnl") or 0)
            theoretical_pnl = (mark or {}).get("theoretical_pnl")
            realistic_pnl = None; fees = config.commission_per_contract*quantity
            slippage = max(0.0,(entry-theoretical_entry)*config.contract_multiplier*quantity)
            exit_fill = None
        position_id = f"{lane}:{position.trade_id}"
        values = (
            position_id,lane,position.trade_id,opportunity,position.ticker,position.direction,
            lane,position.option_symbol,position.strike,position.expiration,None,quantity,
            theoretical_entry,entry,position.current_mid,exit_fill,decision.get("stop_fill"),
            json.dumps([],sort_keys=True),0 if closed else decision["proposed_capital_required"],
            decision["proposed_dollar_risk"],unrealized,theoretical_pnl,realistic_pnl,
            fees,slippage,utc_iso(position.entry_time),utc_iso(position.last_update),
            utc_iso(position.exit_time) if position.exit_time else None,
            "CLOSED" if closed else "OPEN",json.dumps({"exit_reason":position.exit_reason},sort_keys=True),
        )
        with self.repository.connection() as connection:
            current = self.repository._fetchone(connection,
                "SELECT position_id FROM capital_positions WHERE position_id=?",(position_id,))
            if current:
                self.repository._execute(connection,"""UPDATE capital_positions SET
                    current_premium=?,realistic_exit=?,capital_committed=?,unrealized_pnl=?,
                    theoretical_pnl=?,realistic_pnl=?,fees=?,slippage=?,last_mark_at=?,
                    closed_at=?,status=?,metadata_json=? WHERE position_id=?""",(
                    position.current_mid,exit_fill,0 if closed else decision["proposed_capital_required"],
                    unrealized,theoretical_pnl,realistic_pnl,fees,slippage,utc_iso(position.last_update),
                    utc_iso(position.exit_time) if position.exit_time else None,"CLOSED" if closed else "OPEN",
                    json.dumps({"exit_reason":position.exit_reason},sort_keys=True),position_id,
                )).close()
            else:
                self.repository._execute(connection,"""INSERT INTO capital_positions
                    (position_id,lane,source_trade_id,opportunity_id,symbol,direction,strategy,
                     option_symbol,strike,expiration,dte,quantity,theoretical_entry,realistic_entry,
                     current_premium,realistic_exit,stop_price,targets_json,capital_committed,
                     initial_dollar_risk,unrealized_pnl,theoretical_pnl,realistic_pnl,fees,slippage,
                     opened_at,last_mark_at,closed_at,status,metadata_json)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",values).close()
        try:
            linker = getattr(self.repository, "link_provenance_decision_trade", None)
            if callable(linker):
                linker(
                    decision["decision_id"], opportunity_id=opportunity, lane=lane,
                    trade_id=position_id, position_id=position_id,
                    source="capital_repository._upsert_from_paper",
                )
        except Exception as exc:
            LOGGER.exception(json.dumps({
                "event": "provenance_decision_trade_link_failed",
                "decision_id": decision.get("decision_id"),
                "opportunity_id": opportunity, "lane": lane,
                "trade_id": position_id, "exception_type": type(exc).__name__,
            }, sort_keys=True))
            try:
                observation = self.repository.provenance_observation_for_opportunity(
                    opportunity
                )
                if observation:
                    self.repository.mark_provenance_degraded(
                        observation["scan_cycle_id"],
                        f"decision trade link failed: {type(exc).__name__}",
                    )
            except Exception:
                LOGGER.exception("Could not mark provenance cycle degraded")
        self._record_management_snapshot(
            position=position,
            position_id=position_id,
            opportunity_id=opportunity,
            lane=lane,
            quantity=quantity,
            entry=entry,
            stop=decision.get("stop_fill"),
            unrealized_pnl=unrealized,
            initial_risk=decision["proposed_dollar_risk"],
            closed=closed,
            now=now,
        )

    def _record_management_snapshot(self, *, position, position_id, opportunity_id,
                                    lane, quantity, entry, stop, unrealized_pnl,
                                    initial_risk, closed, now):
        writer = getattr(self.repository, "record_trade_management_snapshot", None)
        if not callable(writer):
            return None
        updated_at = parse_utc(position.last_update)
        observed_at = parse_utc(now)
        stale = bool(updated_at and observed_at and observed_at - updated_at > timedelta(minutes=5))
        missing_data = [
            "exit_score", "exit_label", "trade_coach_state", "thesis_state",
            "momentum_state", "structure_state", "target_progress",
            "stop_management_state", "management_reason",
        ]
        try:
            return writer({
                "trade_id": position_id,
                "opportunity_id": opportunity_id,
                "lane": lane,
                "lane_role": "AUTHORITATIVE" if lane == "OB" else "PAPER",
                "symbol": position.ticker,
                "contract_symbol": position.option_symbol,
                "captured_at": now,
                "source_timestamp": position.last_update,
                "trade_status": "CLOSED" if closed else "OPEN",
                "quantity": quantity,
                "entry_timestamp": position.entry_time,
                "entry_premium": entry,
                "latest_option_mark": position.current_mid,
                "latest_underlying": position.last_underlying_price,
                "mark_timestamp": position.last_option_quote_time or position.last_update,
                "time_in_trade_seconds": max(0, int((observed_at - parse_utc(
                    position.entry_time
                )).total_seconds())) if observed_at and position.entry_time else None,
                "current_stop": stop,
                "target_1": None,
                "target_2": None,
                "target_3": None,
                "unrealized_pnl": unrealized_pnl,
                "unrealized_return_pct": position.current_return_percent,
                "current_managed_risk": 0 if closed else initial_risk,
                "data_freshness": "stale" if stale else "fresh",
                "stale": stale,
                "missing_data": missing_data,
                "management_version": "capital-position-v1",
                "management_source": "capital_repository.sync_paper_positions",
            })
        except Exception:
            LOGGER.exception(json.dumps({
                "event": "trade_management_snapshot_write_failed",
                "trade_id": position_id,
                "opportunity_id": opportunity_id,
                "lane": lane,
            }, sort_keys=True))
            return None

    def refresh_lane_state(self, lane, *, now=None):
        now = now or datetime.now(timezone.utc); config = self.configs[lane]
        account = self.account_snapshot(lane, now=now)
        metrics = self.performance_metrics(lane)
        readiness = classify_readiness(metrics)
        risk = drawdown_state(account, config)
        with self.repository.connection() as connection:
            prior = self.repository._fetchone(connection,
                "SELECT risk_state FROM lane_capital_state WHERE lane=?",(lane,)) or {}
            self.repository._execute(connection,"""UPDATE lane_capital_state SET
                current_equity=?,cash_available=?,capital_committed=?,realized_pnl=?,
                unrealized_pnl=?,fees=?,slippage=?,peak_equity=?,current_drawdown_pct=?,
                maximum_drawdown_pct=?,daily_starting_equity=?,daily_pnl=?,open_risk=?,
                open_positions=?,risk_state=?,readiness_status=?,config_json=?,metrics_json=?,updated_at=?
                WHERE lane=?""",(
                    account.current_equity,account.cash_available,account.capital_committed,
                    account.realized_pnl,account.unrealized_pnl,account.fees,account.slippage,
                    account.peak_equity,account.current_drawdown_pct,account.maximum_drawdown_pct,
                    account.daily_starting_equity,account.daily_pnl,account.open_risk,
                    account.open_positions,risk,readiness,json.dumps(asdict(config),sort_keys=True),
                    json.dumps(metrics,sort_keys=True),utc_iso(now),lane,
                )).close()
            observed = utc_iso(now)
            snapshot_id = hashlib.sha256(f"{lane}|{observed}".encode()).hexdigest()
            self.repository._execute(connection,"""INSERT INTO capital_equity_history
                (snapshot_id,lane,observed_at,equity,cash_available,capital_committed,
                 realized_pnl,unrealized_pnl,open_risk,drawdown_pct)
                VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(snapshot_id) DO NOTHING""",(
                    snapshot_id,lane,observed,account.current_equity,account.cash_available,
                    account.capital_committed,account.realized_pnl,account.unrealized_pnl,
                    account.open_risk,account.current_drawdown_pct,
                )).close()
            previous = prior.get("risk_state")
            if previous and previous != risk:
                identity = hashlib.sha256(f"{lane}|{previous}|{risk}|{observed}".encode()).hexdigest()
                self.repository._execute(connection,"""INSERT INTO capital_risk_events
                    (event_id,lane,previous_state,new_state,reason_code,current_equity,
                     drawdown_pct,event_at,metadata_json) VALUES (?,?,?,?,?,?,?,?,?)""",(
                        identity,lane,previous,risk,f"DRAWDOWN_{risk}",account.current_equity,
                        account.current_drawdown_pct,observed,json.dumps({},sort_keys=True),
                    )).close()
            trading_date=now.astimezone(ZoneInfo("America/New_York")).date().isoformat()
            locked=(account.daily_pnl <= -(account.daily_starting_equity*config.max_daily_loss_pct/100)
                    or risk == DrawdownState.HALTED)
            lock_reason=("DAILY_LOSS_LIMIT_REACHED" if account.daily_pnl <= -(account.daily_starting_equity*config.max_daily_loss_pct/100)
                         else "DRAWDOWN_HALT" if risk == DrawdownState.HALTED else None)
            current_daily=self.repository._fetchone(connection,
                "SELECT lane FROM capital_daily_state WHERE lane=? AND trading_date=?",(lane,trading_date))
            daily_values=(account.daily_starting_equity,account.current_equity,
                account.daily_pnl-account.unrealized_pnl,account.unrealized_pnl,
                account.daily_pnl,1 if locked else 0,lock_reason,observed,lane,trading_date)
            if current_daily:
                self.repository._execute(connection,"""UPDATE capital_daily_state SET
                    starting_equity=?,ending_equity=?,realized_pnl=?,unrealized_pnl=?,
                    daily_pnl=?,entries_locked=?,lock_reason=?,updated_at=?
                    WHERE lane=? AND trading_date=?""",daily_values).close()
            else:
                self.repository._execute(connection,"""INSERT INTO capital_daily_state
                    (starting_equity,ending_equity,realized_pnl,unrealized_pnl,daily_pnl,
                     entries_locked,lock_reason,updated_at,lane,trading_date)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",daily_values).close()
        return {**asdict(account),"risk_state":risk,"readiness_status":readiness,"metrics":metrics}

    def performance_metrics(self, lane):
        with self.repository.connection() as connection:
            positions = self.repository._fetchall(connection,
                "SELECT * FROM capital_positions WHERE lane=? AND status<>'OPEN' ORDER BY closed_at",(lane,))
            decisions = self.repository._fetchall(connection,
                "SELECT * FROM capital_decisions WHERE lane=?",(lane,))
            history = self.repository._fetchall(connection,
                "SELECT * FROM capital_equity_history WHERE lane=?",(lane,))
        pnl = [float(row["realistic_pnl"]) for row in positions if row.get("realistic_pnl") is not None]
        wins = [value for value in pnl if value > 0]; losses = [value for value in pnl if value < 0]
        average_deployed = (sum(float(row.get("capital_committed") or 0) for row in history)/len(history)) if history else 0
        rejected = [row for row in decisions if row["decision_state"] != "TAKE"]
        hypothetical = [row for row in rejected if row.get("hypothetical_realistic_pnl") is not None]
        completeness = (sum(bool(row.get("proposed_contract")) for row in decisions)/len(decisions)) if decisions else 0
        execution_evidence = (sum(row.get("realistic_pnl") is not None and row.get("theoretical_pnl") is not None for row in positions)/len(positions)) if positions else 0
        net = sum(pnl)
        return {
            "trades":len(pnl),"sessions":len({str(row.get("closed_at"))[:10] for row in positions if row.get("closed_at")}),
            "win_rate":len(wins)/len(pnl)*100 if pnl else None,
            "average_winner":sum(wins)/len(wins) if wins else None,
            "average_loser":sum(losses)/len(losses) if losses else None,
            "expectancy":net/len(pnl) if pnl else None,
            "profit_factor":sum(wins)/abs(sum(losses)) if losses else None,
            "maximum_drawdown_pct":max((float(row.get("drawdown_pct") or 0) for row in history),default=0),
            "average_capital_deployed":average_deployed,
            "peak_capital_deployed":max((float(row.get("capital_committed") or 0) for row in history),default=0),
            "average_risk_per_trade":sum(float(row.get("initial_dollar_risk") or 0) for row in positions)/len(positions) if positions else None,
            "maximum_risk_per_trade":max((float(row.get("initial_dollar_risk") or 0) for row in positions),default=None),
            "rejected_opportunities":len(rejected),
            "missed_winners":sum(float(row["hypothetical_realistic_pnl"])>0 for row in hypothetical),
            "avoided_losers":sum(float(row["hypothetical_realistic_pnl"])<0 for row in hypothetical),
            "capital_efficiency_pct":capital_efficiency(net,average_deployed),
            "data_completeness":completeness,"execution_evidence":execution_evidence,
            "risk_control_coverage":bool(decisions),"regimes":0,"stable_across_regimes":False,
        }

    def lane_state(self, lane):
        with self.repository.connection() as connection:
            row = self.repository._fetchone(connection,
                "SELECT * FROM lane_capital_state WHERE lane=?",(str(lane).upper(),))
        return _decode_state(row)

    def lane_states(self):
        with self.repository.connection() as connection:
            rows = self.repository._fetchall(connection,
                "SELECT * FROM lane_capital_state ORDER BY lane")
        return [_decode_state(row) for row in rows]


def _decode_state(row):
    if not row:
        return None
    row = dict(row)
    for source,target in (("config_json","config"),("metrics_json","metrics")):
        try: row[target]=json.loads(row.get(source) or "{}")
        except Exception: row[target]={}
    return row
