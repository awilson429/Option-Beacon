"""Read-only adapters over existing OptionBeacon persistence services."""
from __future__ import annotations

import os
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas_market_calendars as market_calendars

from trade_repository import RepositoryUnavailable, TradeRepository, parse_utc
from capital_readiness import LaneCapitalConfig

UTC = timezone.utc
EASTERN = ZoneInfo("America/New_York")
SUPPORTED_SYMBOLS = frozenset({"SPY", "QQQ"})


class ReadOnlyTradeRepository(TradeRepository):
    """Reuse authoritative reads without running TradeRepository schema DDL."""

    def initialize(self):
        return None

    @contextmanager
    def connection(self):
        """Open a Neon-compatible transaction that cannot write."""
        import psycopg2
        from psycopg2.extras import RealDictCursor

        options = {"cursor_factory": RealDictCursor, "connect_timeout": self.connect_timeout_seconds}
        if "sslmode=" not in self.database_url:
            options["sslmode"] = "require"
        connection = None
        try:
            connection = psycopg2.connect(self.database_url, **options)
            connection.autocommit = False
            cursor = connection.cursor()
            cursor.execute("BEGIN")
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.close()
            yield connection
        except RepositoryUnavailable:
            raise
        except Exception as exc:
            raise RepositoryUnavailable(f"Trade repository unavailable: {type(exc).__name__}") from exc
        finally:
            if connection is not None:
                connection.rollback()
                connection.close()

    def list_scalp_observations(self, *, symbol, limit=5000):
        """Read additive scalp state; return no state before its schema is deployed."""
        with self.connection() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute("""SELECT payload FROM scalp_research_observations
                    WHERE symbol=%s AND strategy='SCALP_RESEARCH' AND mode='SHADOW'
                    ORDER BY observed_at DESC LIMIT %s""", (symbol, int(limit)))
                rows = cursor.fetchall()
                return [dict(row.get("payload") or {}) for row in rows]
            except Exception as exc:
                if type(exc).__name__ == "UndefinedTable":
                    return []
                raise
            finally:
                cursor.close()

    def list_capital_states(self):
        return self._optional_capital_rows(
            "SELECT * FROM lane_capital_state ORDER BY lane", ()
        )

    def list_capital_decisions(self, limit=50):
        return self._optional_capital_rows(
            "SELECT * FROM capital_decisions ORDER BY decided_at DESC,decision_id DESC LIMIT %s",
            (int(limit),),
        )

    def list_capital_positions(self):
        return self._optional_capital_rows(
            "SELECT * FROM capital_positions ORDER BY opened_at DESC", ()
        )

    def _optional_capital_rows(self, query, params):
        try:
            with self.connection() as connection:
                cursor = connection.cursor()
                cursor.execute(query, params)
                rows = [dict(row) for row in cursor.fetchall()]
                cursor.close()
                return rows
        except RepositoryUnavailable as exc:
            if "UndefinedTable" in str(exc):
                return []
            raise


def market_is_open(now: datetime | None = None) -> bool:
    current = now or datetime.now(UTC)
    schedule = market_calendars.get_calendar("NYSE").schedule(
        start_date=current.astimezone(EASTERN).date(),
        end_date=current.astimezone(EASTERN).date(),
    )
    if schedule.empty:
        return False
    return schedule.iloc[0]["market_open"].to_pydatetime() <= current <= schedule.iloc[0]["market_close"].to_pydatetime()


def _number(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _trade_lane(trade):
    metadata = trade.get("metadata") or {}
    values = " ".join(str(metadata.get(key) or "") for key in
                      ("execution_lane", "simulation_profile", "variant", "source_strategy"))
    values = f'{values} {trade.get("setup") or ""}'.upper()
    if "MIRROR" in values or "CONTROL" in values:
        return "CONTROL_RESEARCH", "MIRROR / CONTROL RESEARCH", "RESEARCH_CONTROL"
    if "BROAD" in values:
        return "BROAD", "BROAD", "PAPER"
    return "OB", "OB", "AUTHORITATIVE"


def _home_trade(trade, *, event):
    metadata = trade.get("metadata") or {}
    key, label, role = _trade_lane(trade)
    return {"id": str(trade.get("id")), "symbol": trade.get("symbol"),
            "direction": trade.get("direction"), "strategy": label, "lane_role": role,
            "status": str(trade.get("status") or "UNKNOWN"), "setup": trade.get("setup"),
            "entry_price": _number(trade.get("entry_price")),
            "current_price": _number(trade.get("last_price")),
            "contract": metadata.get("option_symbol") or metadata.get("contract"),
            "pnl": _number(trade.get("realized_result") if event == "CLOSED" else metadata.get("unrealized_pnl")),
            "opened_at": parse_utc(trade.get("opened_at")), "closed_at": parse_utc(trade.get("closed_at")),
            "event": event, "_lane_key": key}


class OptionBeaconReadService:
    def __init__(self, repository=None, *, now=None):
        self._repository = repository
        self._now = now or (lambda: datetime.now(UTC))

    def repository(self):
        if self._repository is not None:
            return self._repository
        database_url = os.getenv("DATABASE_URL", "").strip()
        if not database_url:
            raise RepositoryUnavailable("Authoritative database is not configured.")
        self._repository = ReadOnlyTradeRepository(database_url=database_url, require_durable=True)
        return self._repository

    def database_available(self) -> bool:
        try:
            with self.repository().connection() as connection:
                cursor = connection.cursor()
                cursor.execute("SELECT 1")
                cursor.fetchone()
                cursor.close()
            return True
        except Exception:
            return False

    def _opportunities(self, symbol, limit=100):
        return [row for row in self.repository().list_opportunities(limit=limit) if str(row.get("symbol") or "").upper() == symbol]

    def _enrich_trades(self, trades):
        opportunities = {row.get("id"): row for row in self.repository().list_opportunities(limit=500)}
        return [{**trade, "symbol": (opportunities.get(trade.get("opportunity_id")) or {}).get("symbol"),
            "direction": (opportunities.get(trade.get("opportunity_id")) or {}).get("direction"),
            "setup": (opportunities.get(trade.get("opportunity_id")) or {}).get("playbook")} for trade in trades]

    def active_trades(self):
        return self._enrich_trades(self.repository().list_open_trades())

    def recent_trades(self, limit):
        return self._enrich_trades(self.repository().list_recent_trades(limit=limit))

    def market(self, symbol):
        rows = self._opportunities(symbol, 25)
        row = rows[0] if rows else {}
        metadata = row.get("metadata") or {}
        evidence = row.get("evidence") or {}
        updated = parse_utc(row.get("updated_at") or row.get("signal_timestamp"))
        return {"symbol": symbol, "market_status": "open" if market_is_open(self._now()) else "closed",
            "data_status": "persisted" if row else "unavailable", "price": _number(row.get("entry_reference")),
            "bias": row.get("direction"), "regime": metadata.get("regime") or evidence.get("regime"),
            "last_updated": updated, "source": "persisted_state", "metadata": {}}

    def trade_desk(self, symbol):
        rows = self._opportunities(symbol, 100)
        row = rows[0] if rows else {}
        evidence = row.get("evidence") or {}; metadata = row.get("metadata") or {}
        direction = row.get("direction"); state = str(row.get("state") or "unavailable").lower()
        today = self._now().astimezone(EASTERN).date()
        session_rows = [trade for trade in self.recent_trades(100) if trade.get("symbol") == symbol and (parse_utc(trade.get("opened_at")) or datetime.min.replace(tzinfo=UTC)).astimezone(EASTERN).date() == today]
        results = [_number(trade.get("realized_result")) for trade in session_rows]
        results = [value for value in results if value is not None]
        wins = sum(value > 0 for value in results); losses = sum(value < 0 for value in results)
        contract = metadata.get("contract") or metadata.get("option_symbol")
        factors = [key for key, value in evidence.items() if isinstance(value, bool) and value]
        return {"symbol": symbol, "price": _number(row.get("entry_reference")),
            "market_status": "open" if market_is_open(self._now()) else "closed", "data_status": "persisted" if row else "unavailable",
            "last_updated": parse_utc(row.get("updated_at") or row.get("signal_timestamp")),
            "bias": {"direction": direction, "label": f"{direction} BIAS" if direction else None},
            "trade_coverage": {"direction": direction, "entry_trigger": _number(row.get("entry_reference")), "state": state},
            "setup": {"state": "selected" if contract else "awaiting_contract" if row else "unavailable", "strike": _number(metadata.get("strike")),
                "expiration": metadata.get("expiration"), "dte": metadata.get("dte"), "spread": _number(metadata.get("spread_percent")), "contract": contract},
            "context": {"level": metadata.get("context_level") or "unavailable", "known_factors": factors, "details": None},
            "confirmations": {"state": "unavailable", "items": []}, "market_condition": {"regime": metadata.get("regime") or evidence.get("regime")},
            "session": {"pnl": sum(results) if results else None, "trades": len(session_rows), "wins": wins, "losses": losses,
                "win_rate": wins / (wins + losses) * 100 if wins + losses else None}}

    def options_desk(self):
        """Independent persisted projections; a peer is never used as fallback."""
        return {"instruments": {symbol: self.trade_desk(symbol) for symbol in ("SPY", "QQQ")}}

    def trade_desk_home(self):
        now = self._now(); today = now.astimezone(EASTERN).date()
        active_rows = self.active_trades(); recent_rows = self.recent_trades(200)
        today_rows = [row for row in recent_rows if
                      (parse_utc(row.get("opened_at")) or datetime.min.replace(tzinfo=UTC)).astimezone(EASTERN).date() == today]
        closed_today = [row for row in today_rows if str(row.get("status") or "").upper() == "CLOSED"]
        realized_values = [_number(row.get("realized_result")) for row in closed_today]
        realized_values = [value for value in realized_values if value is not None]
        unrealized_values = [_number((row.get("metadata") or {}).get("unrealized_pnl")) for row in active_rows]
        known_unrealized = [value for value in unrealized_values if value is not None]
        realized = sum(realized_values) if realized_values else None
        unrealized = sum(known_unrealized) if known_unrealized else None
        wins = sum(value > 0 for value in realized_values); losses = sum(value < 0 for value in realized_values)
        lane_definitions = {
            "OB": ("OB", "AUTHORITATIVE", "Authoritative OptionBeacon strategy"),
            "BROAD": ("BROAD", "PAPER", "Broad-universe paper participation"),
            "CONTROL_RESEARCH": ("MIRROR / CONTROL RESEARCH", "RESEARCH_CONTROL", "Research/control comparison only; not a primary live lane"),
        }
        lanes = []
        for key, (label, role, description) in lane_definitions.items():
            lane_today = [row for row in today_rows if _trade_lane(row)[0] == key]
            lane_active = [row for row in active_rows if _trade_lane(row)[0] == key]
            lane_realized = [_number(row.get("realized_result")) for row in lane_today
                             if str(row.get("status") or "").upper() == "CLOSED"]
            lane_realized = [value for value in lane_realized if value is not None]
            lanes.append({"key": key, "label": label, "role": role, "active_trades": len(lane_active),
                          "trades_today": len(lane_today), "realized_pnl": sum(lane_realized) if lane_realized else None,
                          "description": description})
        active = [_home_trade(row, event="ACTIVE") for row in active_rows]
        activity = [_home_trade(row, event="CLOSED" if str(row.get("status") or "").upper() == "CLOSED" else "OPENED")
                    for row in recent_rows[:12]]
        for row in active + activity: row.pop("_lane_key", None)
        accounts = self.capital_overview()["lanes"]
        capital_decisions = self.capital_decisions(6)
        capital_persisted=any(item.get("data_status")=="persisted" for item in accounts)
        return {"as_of": now, "data_status": "persisted" if active_rows or recent_rows or capital_persisted else "unavailable",
                "session": {"realized_pnl": realized, "unrealized_pnl": unrealized,
                            "total_pnl": ((realized or 0) + (unrealized or 0)) if realized is not None or unrealized is not None else None,
                            "trades": len(today_rows), "wins": wins, "losses": losses,
                            "win_rate": wins / (wins + losses) * 100 if wins + losses else None,
                            "active_trades": len(active_rows)},
                "active": active, "lanes": lanes, "recent_activity": activity,
                "accounts": accounts, "capital_decisions": capital_decisions}

    def _capital_state_rows(self):
        repository = self.repository()
        reader = getattr(repository, "list_capital_states", None)
        if callable(reader):
            return reader()
        try:
            with repository.connection() as connection:
                return repository._fetchall(connection, "SELECT * FROM lane_capital_state ORDER BY lane")
        except Exception:
            return []

    def _capital_decision_rows(self, limit):
        repository = self.repository()
        reader = getattr(repository, "list_capital_decisions", None)
        if callable(reader):
            return reader(limit)
        try:
            with repository.connection() as connection:
                return repository._fetchall(connection,
                    "SELECT * FROM capital_decisions ORDER BY decided_at DESC,decision_id DESC LIMIT ?",(int(limit),))
        except Exception:
            return []

    def _capital_position_rows(self):
        repository=self.repository(); reader=getattr(repository,"list_capital_positions",None)
        if callable(reader): return reader()
        try:
            with repository.connection() as connection:
                return repository._fetchall(connection,"SELECT * FROM capital_positions ORDER BY opened_at DESC")
        except Exception: return []

    def _capital_lane_payload(self, lane, row=None, positions=None):
        config = LaneCapitalConfig.for_lane(lane)
        if not row:
            return {"lane":lane,"data_status":"unavailable","starting_capital":config.starting_capital,
                    "current_equity":None,"cash_available":None,"capital_committed":None,
                    "net_pnl":None,"return_pct":None,"realized_pnl":None,"unrealized_pnl":None,
                    "fees":None,"slippage":None,"peak_equity":None,"current_drawdown_pct":None,
                    "maximum_drawdown_pct":None,"daily_pnl":None,"open_risk":None,
                    "open_positions":0,"risk_state":"UNAVAILABLE","readiness_status":"NOT_READY",
                    "metrics":{},"positions":[],"updated_at":None}
        try: metrics=json.loads(row.get("metrics_json") or "{}")
        except Exception: metrics={}
        starting=float(row.get("starting_equity") or config.starting_capital)
        current=_number(row.get("current_equity")); net=(current-starting) if current is not None else None
        position_payload=[]
        for position in positions or []:
            opened=parse_utc(position.get("opened_at")); closed=parse_utc(position.get("closed_at"))
            endpoint=closed or self._now()
            try: targets=json.loads(position.get("targets_json") or "[]")
            except Exception: targets=[]
            position_payload.append({"position_id":str(position.get("position_id")),"lane":lane,
                "opportunity_id":str(position.get("opportunity_id")),"symbol":position.get("symbol"),
                "direction":position.get("direction"),"strategy":position.get("strategy") or lane,
                "contract_symbol":position.get("option_symbol"),"strike":_number(position.get("strike")),
                "expiration":position.get("expiration"),"dte":position.get("dte"),
                "entry_premium":_number(position.get("realistic_entry")),"current_premium":_number(position.get("current_premium")),
                "quantity":int(position.get("quantity") or 0),"capital_committed":float(position.get("capital_committed") or 0),
                "initial_dollar_risk":float(position.get("initial_dollar_risk") or 0),
                "unrealized_pnl":float(position.get("unrealized_pnl") or 0),"realized_pnl":_number(position.get("realistic_pnl")),
                "entry_timestamp":opened,"time_in_trade_seconds":max(0,int((endpoint-opened).total_seconds())) if opened else None,
                "stop":_number(position.get("stop_price")),"targets":targets,"status":position.get("status")})
        return {"lane":lane,"data_status":"persisted","starting_capital":starting,
                "current_equity":current,"cash_available":_number(row.get("cash_available")),
                "capital_committed":_number(row.get("capital_committed")),"net_pnl":net,
                "return_pct":net/starting*100 if net is not None and starting else None,
                "realized_pnl":_number(row.get("realized_pnl")),"unrealized_pnl":_number(row.get("unrealized_pnl")),
                "fees":_number(row.get("fees")),"slippage":_number(row.get("slippage")),
                "peak_equity":_number(row.get("peak_equity")),"current_drawdown_pct":_number(row.get("current_drawdown_pct")),
                "maximum_drawdown_pct":_number(row.get("maximum_drawdown_pct")),"daily_pnl":_number(row.get("daily_pnl")),
                "open_risk":_number(row.get("open_risk")),"open_positions":int(row.get("open_positions") or 0),
                "risk_state":row.get("risk_state") or "UNAVAILABLE","readiness_status":row.get("readiness_status") or "NOT_READY",
                "metrics":metrics,"positions":position_payload,"updated_at":parse_utc(row.get("updated_at"))}

    def capital_overview(self):
        rows={str(row.get("lane") or "").upper():row for row in self._capital_state_rows()}
        positions=self._capital_position_rows()
        return {"as_of":self._now(),"mode":"SIMULATION",
                "lanes":[self._capital_lane_payload(lane,rows.get(lane),
                    [position for position in positions if str(position.get("lane") or "").upper()==lane]) for lane in ("OB","BROAD")],
                "mirror_role":"RESEARCH_CONTROL_ONLY"}

    def capital_lane(self, lane):
        return next(item for item in self.capital_overview()["lanes"] if item["lane"]==lane)

    def capital_compare(self):
        overview=self.capital_overview(); lanes=overview["lanes"]
        enough=all((item.get("metrics") or {}).get("trades",0)>=100 for item in lanes)
        winner="INSUFFICIENT_EVIDENCE"
        if enough and all(item["readiness_status"] in {"PAPER_VALIDATED","LIVE_CANDIDATE"} for item in lanes):
            ranked=sorted(lanes,key=lambda item:((item.get("metrics") or {}).get("capital_efficiency_pct") or float("-inf")),reverse=True)
            winner=ranked[0]["lane"]
        return {"as_of":overview["as_of"],"lanes":lanes,"winner":winner,
                "evidence":"SUFFICIENT" if enough else "INSUFFICIENT",
                "normalization":"independent starting capital; realistic simulated P&L primary"}

    def capital_decisions(self, limit=50):
        result=[]
        for row in self._capital_decision_rows(limit):
            result.append({"decision_id":str(row.get("decision_id")),"lane":row.get("lane"),
                "opportunity_id":str(row.get("opportunity_id")),"symbol":row.get("symbol"),
                "direction":row.get("direction"),"state":row.get("decision_state"),
                "reason_code":row.get("reason_code"),"explanation":row.get("explanation"),
                "proposed_contract":row.get("proposed_contract"),"proposed_quantity":int(row.get("proposed_quantity") or 0),
                "proposed_capital_required":float(row.get("proposed_capital_required") or 0),
                "proposed_dollar_risk":float(row.get("proposed_dollar_risk") or 0),
                "proposed_account_risk_pct":float(row.get("proposed_account_risk_pct") or 0),
                "decided_at":parse_utc(row.get("decided_at"))})
        return result

    def risk_status(self):
        lanes=[]
        for item in self.capital_overview()["lanes"]:
            config=LaneCapitalConfig.for_lane(item["lane"])
            equity=item.get("current_equity") or item["starting_capital"]
            risk_state=item["risk_state"]
            lanes.append({"lane":item["lane"],"risk_state":risk_state,"daily_pnl":item.get("daily_pnl"),
                "daily_loss_limit":item["starting_capital"]*config.max_daily_loss_pct/100,
                "open_risk":item.get("open_risk"),"maximum_open_risk":equity*config.max_total_open_risk_pct/100,
                "current_drawdown_pct":item.get("current_drawdown_pct"),
                "entries_allowed":risk_state not in {"HALTED","UNAVAILABLE"}})
        return {"as_of":self._now(),"lanes":lanes}

    def _scalp_rows(self, symbol, limit=5000):
        repository = self.repository()
        reader = getattr(repository, "list_scalp_observations", None)
        if reader is None:
            return []
        return [row for row in reader(symbol=symbol, limit=limit)
                if str(row.get("symbol") or "").upper() == symbol and row.get("strategy", "SCALP_RESEARCH") == "SCALP_RESEARCH"]

    def scalp_state(self, symbol):
        rows = self._scalp_rows(symbol, 1)
        return {"symbol": symbol, "strategy": "SCALP_RESEARCH", "mode": "SHADOW",
                "market_status": "open" if market_is_open(self._now()) else "closed",
                "data_status": "persisted" if rows else "unavailable", "current": rows[0] if rows else None}

    def scalp_performance(self, symbol):
        from scalp.analytics import performance
        return {"symbol": symbol, "strategy": "SCALP_RESEARCH", "metrics": performance(self._scalp_rows(symbol))}

    def scalp_compare(self):
        from scalp.analytics import compare
        result = compare(self._scalp_rows("SPY"), self._scalp_rows("QQQ"))
        normalization = result.pop("normalization")
        return {"strategy": "SCALP_RESEARCH", "symbols": result, "normalization": normalization}

    def system_status(self):
        now = self._now(); database = "connected" if self.database_available() else "unavailable"
        health = None
        if database == "connected":
            try: health = self.repository().get_latest_scan_health()
            except Exception: health = None
        success = parse_utc((health or {}).get("last_success_at")); age = (now - success).total_seconds() if success else None
        freshness = "fresh" if age is not None and age <= 900 else "stale" if success else "unavailable"
        worker = "healthy" if health and not health.get("last_error_message") and freshness == "fresh" else "degraded" if health else "unavailable"
        return {"status": "ok" if database == "connected" else "degraded", "market_status": "open" if market_is_open(now) else "closed",
            "database": database, "data_freshness": freshness, "worker_status": worker, "worker_last_success": success,
            "provider_status": "not_queried", "timestamp": now}
