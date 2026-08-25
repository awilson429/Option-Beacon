"""Read-only adapters over existing OptionBeacon persistence services."""
from __future__ import annotations

import os
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas_market_calendars as market_calendars

from trade_repository import RepositoryUnavailable, TradeRepository, parse_utc
from capital_readiness import LaneCapitalConfig
from trade_state_service import scanner_health_state

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

    def list_paper_execution_trades(self):
        return self._optional_capital_rows(
            "SELECT * FROM paper_execution_trades ORDER BY opened_at DESC,trade_id", ()
        )

    def list_paper_execution_positions(self):
        return self._optional_capital_rows(
            "SELECT * FROM paper_execution_positions ORDER BY opened_at DESC,trade_id", ()
        )

    def list_active_trade_positions(self):
        """Read the lane projection with exact paper marks when that table exists."""
        try:
            rows = self._optional_capital_rows(
                """SELECT cp.*,pp.option_type AS paper_option_type,
                    pp.entry_underlying_price AS paper_underlying_entry,
                    pp.current_option_price AS paper_option_mark,
                    pp.unrealized_return_pct AS paper_unrealized_return_pct,
                    pp.last_updated_at AS paper_last_updated_at,
                    pp.metadata_json AS paper_metadata_json
                    FROM capital_positions cp
                    LEFT JOIN paper_execution_positions pp
                      ON pp.position_id=cp.source_trade_id
                    WHERE cp.status='OPEN' AND cp.lane IN ('OB','BROAD')
                    ORDER BY cp.opened_at DESC,cp.position_id""", ()
            )
            if rows:
                return rows
        except RepositoryUnavailable as exc:
            if not any(name in str(exc) for name in ("UndefinedTable", "UndefinedColumn")):
                raise
        return [row for row in self.list_capital_positions()
                if row.get("status") == "OPEN" and row.get("lane") in {"OB", "BROAD"}]

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


def _integer(value):
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _json_object(value):
    if isinstance(value, dict):
        return value
    try:
        decoded = json.loads(value or "{}")
        return decoded if isinstance(decoded, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _first(source_rows, *keys):
    for source in source_rows:
        for key in keys:
            value = source.get(key)
            if value is not None and value != "":
                return value
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

    def _active_capital_rows(self):
        repository = self.repository()
        reader = getattr(repository, "list_active_trade_positions", None)
        if callable(reader):
            return reader()
        return [row for row in self._capital_position_rows()
                if str(row.get("status") or "").upper() == "OPEN"
                and str(row.get("lane") or "").upper() in {"OB", "BROAD"}]

    def _active_management(self, snapshot=None):
        snapshot = snapshot or {}
        payload = {
            "breakeven_state": snapshot.get("breakeven_state"),
            "maximum_hold_minutes": snapshot.get("maximum_hold_minutes"),
            "exit_score": snapshot.get("exit_score"),
            "exit_label": snapshot.get("exit_label"),
            "exit_state": snapshot.get("exit_label"),
            "trade_coach_state": snapshot.get("trade_coach_state"),
            "trade_coach_status": snapshot.get("trade_coach_state"),
            "thesis_state": snapshot.get("thesis_state"),
            "thesis_status": snapshot.get("thesis_state"),
            "momentum_state": snapshot.get("momentum_state"),
            "structure_state": snapshot.get("structure_state"),
            "target_progress": snapshot.get("target_progress"),
            "stop_management_state": snapshot.get("stop_management_state"),
            "management_reason": snapshot.get("management_reason"),
            "management_updated_at": parse_utc(snapshot.get("captured_at")),
            "last_management_update": parse_utc(snapshot.get("captured_at")),
        }
        payload["exit_score"] = _integer(payload["exit_score"])
        payload["maximum_hold_minutes"] = _integer(payload["maximum_hold_minutes"])
        payload["management_data_status"] = (
            "stale" if snapshot.get("stale") else "persisted" if snapshot else "unavailable"
        )
        return payload

    def _apply_management_snapshots(self, rows):
        reader = getattr(self.repository(), "latest_trade_management_snapshots", None)
        snapshots = reader([(row.get("id"), row.get("lane")) for row in rows]) \
            if callable(reader) else {}
        for row in rows:
            snapshot = snapshots.get((str(row.get("id")), str(row.get("lane") or "").upper()))
            row.update(self._active_management(snapshot))
            if not snapshot:
                continue
            for target, source in (
                ("stop", "current_stop"), ("target_1", "target_1"),
                ("target_2", "target_2"), ("target_3", "target_3"),
                ("current_dollar_risk", "current_managed_risk"),
            ):
                if snapshot.get(source) is not None:
                    row[target] = _number(snapshot[source])
        return rows

    def _active_capital_trade(self, position, authoritative, opportunity, decision):
        lane = str(position.get("lane") or "").upper()
        capital_metadata = _json_object(position.get("metadata_json"))
        paper_metadata = _json_object(position.get("paper_metadata_json"))
        paper_position = _json_object(paper_metadata.get("position"))
        trade_metadata = (authoritative or {}).get("metadata") or {}
        opportunity_metadata = (opportunity or {}).get("metadata") or {}
        sources = [capital_metadata, paper_position, trade_metadata, opportunity_metadata]
        opened = parse_utc(position.get("opened_at")) or parse_utc((authoritative or {}).get("opened_at"))
        mark_timestamp = parse_utc(position.get("last_mark_at") or position.get("paper_last_updated_at"))
        freshness, _ = self._scanner_freshness(mark_timestamp, self._now())
        targets = position.get("targets")
        if not isinstance(targets, list):
            try: targets = json.loads(position.get("targets_json") or "[]")
            except (TypeError, ValueError, json.JSONDecodeError): targets = []
        targets = [_number(value) for value in targets if _number(value) is not None]
        target_values = targets[:3] + [None] * (3 - len(targets[:3]))
        if not targets:
            target_values = [_number((authoritative or {}).get(f"target_{index}"))
                             for index in (1, 2, 3)]
        latest_option = _number(position.get("current_premium"))
        if latest_option is None: latest_option = _number(position.get("paper_option_mark"))
        underlying_entry = _number(position.get("paper_underlying_entry"))
        if underlying_entry is None: underlying_entry = _number((authoritative or {}).get("entry_price"))
        latest_underlying = _number(_first(sources, "last_underlying_price", "latest_underlying"))
        if latest_underlying is None: latest_underlying = _number((authoritative or {}).get("last_price"))
        option_type = _first(sources, "option_type") or position.get("paper_option_type")
        direction = (authoritative or {}).get("direction") or (opportunity or {}).get("direction") or position.get("direction")
        if option_type is None and str(direction or "").upper() in {"CALL", "PUT"}:
            option_type = str(direction).upper()
        risk_pct = _number((decision or {}).get("proposed_account_risk_pct"))
        metadata = {**trade_metadata, "capital_position_id": position.get("position_id"),
                    "source_trade_id": position.get("source_trade_id")}
        elapsed = max(0, int((self._now() - opened).total_seconds())) if opened else None
        return {
            "id": str(position.get("position_id")),
            "opportunity_id": str(position.get("opportunity_id")),
            "symbol": position.get("symbol") or (opportunity or {}).get("symbol"),
            "direction": direction, "setup": (opportunity or {}).get("playbook"),
            "status": "OPEN", "opened_at": opened, "closed_at": None,
            "entry_price": underlying_entry, "last_price": latest_underlying,
            "exit_price": None, "realized_result": None, "exit_reason": None,
            "metadata": metadata, "lane": lane,
            "lane_role": "AUTHORITATIVE" if lane == "OB" else "PAPER",
            "strategy": position.get("strategy") or lane, "data_status": "persisted",
            "contract_symbol": position.get("option_symbol"), "strike": _number(position.get("strike")),
            "option_type": str(option_type).upper() if option_type else None,
            "expiration": position.get("expiration"), "dte": _integer(
                position.get("dte") if position.get("dte") is not None else _first(sources, "dte")
            ),
            "quantity": _integer(position.get("quantity")),
            "entry_timestamp": opened, "underlying_entry": underlying_entry,
            "option_entry_premium": _number(position.get("realistic_entry")),
            "capital_committed": _number(position.get("capital_committed")),
            "initial_dollar_risk": _number(position.get("initial_dollar_risk")),
            "account_risk_pct": risk_pct, "current_dollar_risk": None,
            "latest_underlying": latest_underlying, "latest_option_mark": latest_option,
            "unrealized_pnl": _number(position.get("unrealized_pnl")),
            "unrealized_return_pct": _number(position.get("paper_unrealized_return_pct")),
            "time_in_trade_seconds": elapsed, "data_freshness": freshness,
            "mark_timestamp": mark_timestamp, "stop": _number(position.get("stop_price"))
                if position.get("stop_price") is not None else _number((authoritative or {}).get("stop_price")),
            "target_1": target_values[0], "target_2": target_values[1], "target_3": target_values[2],
            **self._active_management(),
        }

    def _active_authoritative_trade(self, trade, opportunity, lane):
        metadata = trade.get("metadata") or {}
        opened = parse_utc(trade.get("opened_at"))
        elapsed = max(0, int((self._now() - opened).total_seconds())) if opened else None
        return {**trade, "symbol": (opportunity or {}).get("symbol"),
            "direction": (opportunity or {}).get("direction"), "setup": (opportunity or {}).get("playbook"),
            "lane": lane, "lane_role": "AUTHORITATIVE" if lane == "OB" else "PAPER",
            "strategy": metadata.get("source_strategy") or (opportunity or {}).get("playbook"),
            "data_status": "persisted", "contract_symbol": metadata.get("option_symbol") or metadata.get("contract"),
            "strike": _number(metadata.get("strike")), "option_type": metadata.get("option_type"),
            "expiration": metadata.get("expiration"), "dte": metadata.get("dte"),
            "quantity": metadata.get("quantity"), "entry_timestamp": opened,
            "underlying_entry": _number(trade.get("entry_price")),
            "option_entry_premium": _number(metadata.get("option_entry_premium")),
            "capital_committed": _number(metadata.get("capital_committed")),
            "initial_dollar_risk": _number(metadata.get("initial_dollar_risk")),
            "account_risk_pct": _number(metadata.get("account_risk_pct")), "current_dollar_risk": None,
            "latest_underlying": _number(trade.get("last_price")),
            "latest_option_mark": _number(metadata.get("latest_option_mark")),
            "unrealized_pnl": _number(metadata.get("unrealized_pnl")),
            "unrealized_return_pct": _number(metadata.get("unrealized_return_pct")),
            "time_in_trade_seconds": elapsed, "data_freshness": "unavailable",
            "mark_timestamp": None, "stop": _number(trade.get("stop_price")),
            "target_1": _number(trade.get("target_1")), "target_2": _number(trade.get("target_2")),
            "target_3": _number(trade.get("target_3")), **self._active_management()}

    def active_trades(self):
        authoritative = self.repository().list_open_trades()
        opportunities = {row.get("id"): row for row in self.repository().list_opportunities(limit=500)}
        authoritative_by_opportunity = {row.get("opportunity_id"): row for row in authoritative}
        decisions = {}
        for row in self._capital_decision_rows(10_000):
            lane = str(row.get("lane") or "").upper()
            state = str(row.get("decision_state") or row.get("state") or "").upper()
            key = (lane, row.get("opportunity_id"))
            if lane in {"OB", "BROAD"} and state == "TAKE" and key not in decisions:
                decisions[key] = row
        result = []
        represented = set()
        for position in self._active_capital_rows():
            lane = str(position.get("lane") or "").upper()
            opportunity_id = position.get("opportunity_id")
            if lane not in {"OB", "BROAD"}: continue
            represented.add((lane, opportunity_id))
            result.append(self._active_capital_trade(position,
                authoritative_by_opportunity.get(opportunity_id), opportunities.get(opportunity_id),
                decisions.get((lane, opportunity_id))))
        for trade in authoritative:
            lane_key = _trade_lane({**trade, "setup": (opportunities.get(trade.get("opportunity_id")) or {}).get("playbook")})[0]
            if lane_key == "CONTROL_RESEARCH": continue
            lane = "BROAD" if lane_key == "BROAD" else "OB"
            key = (lane, trade.get("opportunity_id"))
            if key not in represented:
                result.append(self._active_authoritative_trade(
                    trade, opportunities.get(trade.get("opportunity_id")), lane))
        return self._apply_management_snapshots(result)

    def trade_management_history(self, trade_id, *, lane=None, limit=5000):
        reader = getattr(self.repository(), "list_trade_management_snapshots", None)
        if not callable(reader):
            return []
        return reader(trade_id, lane=lane, limit=limit)

    def _provenance_health(self):
        reader = getattr(self.repository(), "latest_provenance_cycle", None)
        cycle = reader() if callable(reader) else None
        if not cycle:
            return {"data_status": "unavailable", "provenance_status": "UNAVAILABLE",
                    "scan_cycle_id": None, "cycle_status": None, "started_at": None,
                    "completed_at": None, "error": None}
        return {
            "data_status": "persisted",
            "provenance_status": cycle.get("provenance_status") or "UNKNOWN",
            "scan_cycle_id": cycle.get("scan_cycle_id"),
            "cycle_status": cycle.get("cycle_status"),
            "started_at": parse_utc(cycle.get("started_at")),
            "completed_at": parse_utc(cycle.get("completed_at")),
            "error": cycle.get("provenance_error"),
        }

    def recent_provenance(self, *, symbol=None, limit=100):
        reader = getattr(self.repository(), "list_recent_provenance_observations", None)
        rows = reader(limit=limit, symbol=symbol) if callable(reader) else []
        return {"as_of": self._now(),
                "data_status": "persisted" if rows else "unavailable",
                "health": self._provenance_health(), "observations": rows}

    @staticmethod
    def _provenance_outcome(position):
        if not position or str(position.get("status") or "").upper() != "CLOSED":
            return None
        metadata = _json_object(position.get("metadata_json"))
        return {
            "status": "CLOSED", "closed_at": parse_utc(position.get("closed_at")),
            "realistic_exit": _number(position.get("realistic_exit")),
            "realistic_pnl": _number(position.get("realistic_pnl")),
            "theoretical_pnl": _number(position.get("theoretical_pnl")),
            "fees": _number(position.get("fees")), "slippage": _number(position.get("slippage")),
            "exit_reason": metadata.get("exit_reason"),
        }

    def opportunity_provenance(self, opportunity_id):
        repository = self.repository()
        observation_reader = getattr(repository, "provenance_observation_for_opportunity", None)
        observation = observation_reader(opportunity_id) if callable(observation_reader) else None
        try:
            opportunity = repository.get_opportunity(opportunity_id=str(opportunity_id))
        except Exception:
            opportunity = None
        decisions = [row for row in self._capital_decision_rows(10_000)
                     if str(row.get("opportunity_id")) == str(opportunity_id)
                     and str(row.get("lane") or "").upper() in {"OB", "BROAD"}]
        link_reader = getattr(repository, "provenance_decision_links", None)
        links = link_reader(opportunity_id=opportunity_id) if callable(link_reader) else []
        positions = [row for row in self._capital_position_rows()
                     if str(row.get("opportunity_id")) == str(opportunity_id)
                     and str(row.get("lane") or "").upper() in {"OB", "BROAD"}]
        lane_payloads = []
        for lane in ("OB", "BROAD"):
            lane_decisions = [row for row in decisions if str(row.get("lane")).upper() == lane]
            lane_links = [row for row in links if str(row.get("lane")).upper() == lane]
            linked_ids = {str(row.get("trade_id")) for row in lane_links if row.get("trade_id")}
            trade = next((row for row in positions
                          if str(row.get("lane")).upper() == lane
                          and str(row.get("position_id")) in linked_ids), None)
            management = self.trade_management_history(trade.get("position_id"), lane=lane) \
                if trade else []
            lane_payloads.append({
                "lane": lane, "decisions": lane_decisions,
                "decision_trade_links": lane_links, "trade": trade,
                "management": management, "outcome": self._provenance_outcome(trade),
            })
        status = "persisted" if observation else "legacy_unavailable" if opportunity else "unavailable"
        return {"as_of": self._now(), "data_status": status,
                "opportunity_id": str(opportunity_id), "observation": observation,
                "opportunity": opportunity, "lanes": lane_payloads}

    def trade_provenance(self, trade_id, *, lane):
        lane = str(lane).upper()
        position = next((row for row in self._capital_position_rows()
                         if str(row.get("position_id")) == str(trade_id)
                         and str(row.get("lane") or "").upper() == lane), None)
        if not position:
            return {"as_of": self._now(), "data_status": "unavailable",
                    "trade_id": str(trade_id), "lane": lane, "observation": None,
                    "qualification": None, "opportunity": None,
                    "capital_decision": None, "decision_trade_link": None,
                    "trade": None, "management": [], "outcome": None}
        opportunity_id = str(position.get("opportunity_id"))
        chain = self.opportunity_provenance(opportunity_id)
        repository = self.repository()
        link_reader = getattr(repository, "provenance_decision_links", None)
        links = link_reader(trade_id=trade_id, lane=lane) if callable(link_reader) else []
        link = links[-1] if links else None
        decision = next((row for row in self._capital_decision_rows(10_000)
                         if link and str(row.get("decision_id")) == str(link.get("decision_id"))), None)
        observation = chain.get("observation")
        qualification = ({key: observation.get(key) for key in
            ("qualification_state", "reason_code", "explanation")}
            if observation else None)
        management = self.trade_management_history(trade_id, lane=lane)
        return {"as_of": self._now(),
                "data_status": "persisted" if observation and link else "partial",
                "trade_id": str(trade_id), "lane": lane, "observation": observation,
                "qualification": qualification, "opportunity": chain.get("opportunity"),
                "capital_decision": decision, "decision_trade_link": link,
                "trade": position, "management": management,
                "outcome": self._provenance_outcome(position)}

    def _journal_source_rows(self, name):
        repository = self.repository()
        reader = getattr(repository, name, None)
        if callable(reader):
            return reader()
        return []

    def _journal_trade(self, position, *, opportunity=None, authoritative=None,
                       execution=None, paper_position=None, management=None):
        opportunity = opportunity or {}
        authoritative = authoritative or {}
        execution = execution or {}
        paper_position = paper_position or {}
        management = management or {}
        capital_metadata = _json_object(position.get("metadata_json"))
        execution_metadata = _json_object(execution.get("contract_metadata_json"))
        opportunity_metadata = opportunity.get("metadata") or _json_object(
            opportunity.get("metadata_json"))
        sources = [capital_metadata, execution_metadata, opportunity_metadata]
        lane = str(position.get("lane") or "").upper()
        trade_id = str(position.get("position_id") or "")
        opened_at = parse_utc(position.get("opened_at"))
        closed_at = parse_utc(position.get("closed_at") or execution.get("closed_at"))
        duration_seconds = None
        if opened_at and closed_at:
            duration_seconds = max(0, int((closed_at - opened_at).total_seconds()))
        elif _integer(execution.get("duration_minutes")) is not None:
            duration_seconds = max(0, _integer(execution.get("duration_minutes")) * 60)
        targets = position.get("targets")
        if not isinstance(targets, list):
            try:
                targets = json.loads(position.get("targets_json") or "[]")
            except (TypeError, ValueError, json.JSONDecodeError):
                targets = []
        targets = [_number(value) for value in targets if _number(value) is not None]
        if not targets:
            targets = [_number(authoritative.get(f"target_{index}")) for index in (1, 2, 3)]
        targets = targets[:3] + [None] * (3 - len(targets[:3]))
        realized_pnl = _number(position.get("realistic_pnl"))
        realistic_entry = _number(position.get("realistic_entry"))
        quantity = _integer(position.get("quantity") if position.get("quantity") is not None
                            else execution.get("quantity"))
        initial_notional = realistic_entry * quantity * 100 if realistic_entry and quantity else None
        realized_return = realized_pnl / initial_notional * 100 \
            if realized_pnl is not None and initial_notional else None
        initial_risk = _number(position.get("initial_dollar_risk"))
        r_multiple = realized_pnl / initial_risk if realized_pnl is not None and initial_risk and initial_risk > 0 else None
        result = ("WIN" if realized_pnl is not None and realized_pnl > 0 else
                  "LOSS" if realized_pnl is not None and realized_pnl < 0 else
                  "BREAKEVEN" if realized_pnl == 0 else "UNAVAILABLE")
        latest = management.get("latest") or {}
        option_type = execution.get("option_type") or paper_position.get("option_type") \
            or _first(sources, "option_type")
        missing = []
        candidates = {
            "contract_symbol": position.get("option_symbol") or execution.get("option_symbol"),
            "option_type": option_type,
            "underlying_entry": paper_position.get("entry_underlying_price") or authoritative.get("entry_price"),
            "underlying_exit": authoritative.get("exit_price"),
            "option_exit_premium": position.get("realistic_exit") or execution.get("exit_option_price"),
            "realized_pnl": realized_pnl,
            "realized_return_pct": realized_return,
            "exit_reason": _first([capital_metadata, execution], "exit_reason"),
        }
        missing.extend(key for key, value in candidates.items() if value is None or value == "")
        if not management.get("count"):
            missing.append("canonical_management_history")
        return {
            "trade_id": trade_id, "opportunity_id": str(position.get("opportunity_id") or ""),
            "lane": lane, "lane_role": "AUTHORITATIVE" if lane == "OB" else "PAPER",
            "symbol": position.get("symbol") or opportunity.get("symbol"),
            "direction": position.get("direction") or opportunity.get("direction"),
            "status": str(position.get("status") or "UNKNOWN").upper(),
            "strategy": position.get("strategy") or opportunity.get("playbook"),
            "contract_symbol": candidates["contract_symbol"], "strike": _number(
                position.get("strike") if position.get("strike") is not None else execution.get("strike")),
            "option_type": str(option_type).upper() if option_type else None,
            "expiration": position.get("expiration") or execution.get("expiration"),
            "dte": _integer(position.get("dte")), "quantity": quantity,
            "entry_timestamp": opened_at, "underlying_entry": _number(candidates["underlying_entry"]),
            "option_entry_premium": realistic_entry,
            "capital_committed": initial_notional if initial_notional is not None
                else _number(position.get("capital_committed")),
            "initial_dollar_risk": initial_risk, "exit_timestamp": closed_at,
            "underlying_exit": _number(candidates["underlying_exit"]),
            "option_exit_premium": _number(candidates["option_exit_premium"]),
            "exit_reason": candidates["exit_reason"], "hold_duration_seconds": duration_seconds,
            "realized_pnl": realized_pnl, "realized_return_pct": realized_return,
            "r_multiple": r_multiple, "mfe_dollars": _number(execution.get("mfe_dollars")),
            "mae_dollars": _number(execution.get("mae_dollars")),
            "mfe_pct": _number(execution.get("mfe_pct")), "mae_pct": _number(execution.get("mae_pct")),
            "result": result, "initial_stop": _number(position.get("stop_price")
                if position.get("stop_price") is not None else authoritative.get("stop_price")),
            "target_1": targets[0], "target_2": targets[1], "target_3": targets[2],
            "management_history_available": bool(management.get("count")),
            "management_snapshot_count": int(management.get("count") or 0),
            "final_exit_score": _integer(latest.get("exit_score")),
            "final_management_label": latest.get("exit_label"),
            "final_management_at": parse_utc(latest.get("captured_at")),
            "data_quality": "CANONICAL", "missing_data": sorted(set(missing)),
            "source_version": opportunity.get("source_version") or "capital-position-v1",
        }

    @staticmethod
    def _journal_metrics(rows):
        closed = [row for row in rows if row.get("status") == "CLOSED"]
        known = [row for row in closed if row.get("realized_pnl") is not None]
        wins = [row for row in known if row["realized_pnl"] > 0]
        losses = [row for row in known if row["realized_pnl"] < 0]
        breakeven = [row for row in known if row["realized_pnl"] == 0]
        returns = [row["realized_return_pct"] for row in closed
                   if row.get("realized_return_pct") is not None]
        holds = [row["hold_duration_seconds"] for row in closed
                 if row.get("hold_duration_seconds") is not None]
        net = sum(row["realized_pnl"] for row in known) if known else None
        return {
            "total_trades": len(closed), "wins": len(wins), "losses": len(losses),
            "breakeven": len(breakeven),
            "win_rate": len(wins) / len(known) * 100 if known else None,
            "realized_pnl": net,
            "average_winner": sum(row["realized_pnl"] for row in wins) / len(wins) if wins else None,
            "average_loser": sum(row["realized_pnl"] for row in losses) / len(losses) if losses else None,
            "profit_factor": (sum(row["realized_pnl"] for row in wins) /
                              abs(sum(row["realized_pnl"] for row in losses))) if losses else None,
            "average_return_pct": sum(returns) / len(returns) if returns else None,
            "average_hold_seconds": sum(holds) / len(holds) if holds else None,
        }

    def trade_history(self, *, lane=None, symbol=None, status=None, result=None,
                      date_from=None, date_to=None, limit=100, offset=0):
        positions = self._capital_position_rows()
        opportunities = {str(row.get("id")): row for row in
                         self.repository().list_opportunities(limit=10_000)}
        authoritative = {str(row.get("opportunity_id")): row for row in
                         self.repository().list_recent_trades(limit=10_000)}
        execution = {str(row.get("trade_id")): row for row in
                     self._journal_source_rows("list_paper_execution_trades")}
        paper_positions = {str(row.get("trade_id")): row for row in
                           self._journal_source_rows("list_paper_execution_positions")}
        allowed = [row for row in positions if str(row.get("lane") or "").upper() in {"OB", "BROAD"}]
        identities = [(row.get("position_id"), row.get("lane")) for row in allowed]
        summary_reader = getattr(self.repository(), "trade_management_snapshot_summaries", None)
        management = summary_reader(identities) if callable(summary_reader) else {}
        rows = []
        for position in allowed:
            try:
                opportunity_id = str(position.get("opportunity_id") or "")
                source_trade_id = str(position.get("source_trade_id") or "")
                key = (str(position.get("position_id")), str(position.get("lane") or "").upper())
                row = self._journal_trade(position, opportunity=opportunities.get(opportunity_id),
                    authoritative=authoritative.get(opportunity_id), execution=execution.get(source_trade_id),
                    paper_position=paper_positions.get(source_trade_id), management=management.get(key))
            except Exception:
                continue
            event_at = row.get("exit_timestamp") or row.get("entry_timestamp")
            if lane and row["lane"] != str(lane).upper(): continue
            if symbol and str(row.get("symbol") or "").upper() != str(symbol).upper(): continue
            if status and row["status"] != str(status).upper(): continue
            if result and row["result"] != str(result).upper(): continue
            if date_from and (not event_at or event_at.date() < date_from): continue
            if date_to and (not event_at or event_at.date() > date_to): continue
            rows.append(row)
        rows.sort(key=lambda row: (row.get("exit_timestamp") or row.get("entry_timestamp") or
                                   datetime.min.replace(tzinfo=UTC), row["trade_id"]), reverse=True)
        overall_rows = [row for row in rows if row["lane"] in {"OB", "BROAD"}]
        lane_metrics = [{"lane": lane_key, **self._journal_metrics(
            [row for row in overall_rows if row["lane"] == lane_key])} for lane_key in ("OB", "BROAD")]
        total = len(rows)
        return {"as_of": self._now(), "data_status": "persisted" if rows else "unavailable",
                "total_count": total, "limit": int(limit), "offset": int(offset),
                "summary": self._journal_metrics(overall_rows), "lanes": lane_metrics,
                "control_research": None, "trades": rows[int(offset):int(offset) + int(limit)]}

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

    @staticmethod
    def _scanner_freshness(observed_at, now):
        timestamp = parse_utc(observed_at)
        if timestamp is None:
            return "unavailable", None
        age = max(0, int((now - timestamp).total_seconds()))
        return ("fresh" if age <= 900 else "stale"), age

    @staticmethod
    def _scanner_lane_decision(lane, decision=None):
        if not decision:
            return {"lane": lane, "data_status": "unavailable", "state": None,
                    "reason_code": None, "explanation": None, "proposed_contract": None,
                    "proposed_quantity": None, "proposed_capital_required": None,
                    "proposed_dollar_risk": None, "proposed_account_risk_pct": None,
                    "decided_at": None}
        return {"lane": lane, "data_status": "persisted", "state": decision.get("state"),
                "reason_code": decision.get("reason_code"), "explanation": decision.get("explanation"),
                "proposed_contract": decision.get("proposed_contract"),
                "proposed_quantity": decision.get("proposed_quantity"),
                "proposed_capital_required": decision.get("proposed_capital_required"),
                "proposed_dollar_risk": decision.get("proposed_dollar_risk"),
                "proposed_account_risk_pct": decision.get("proposed_account_risk_pct"),
                "decided_at": decision.get("decided_at")}

    def _scanner_health(self, now):
        raw = self.repository().get_latest_scan_health()
        lock = None
        if raw:
            lock = self.repository().get_scan_lock(raw.get("scanner_id"))
        state = scanner_health_state(raw, scan_lock=lock, now=now)
        try:
            from optionbeacon.worker.run import configured_scan_seconds
            interval = configured_scan_seconds()
        except Exception:
            interval = None
        completed = parse_utc((raw or {}).get("last_completed_at"))
        next_expected = None
        if interval is not None and completed is not None and state.get("state") != "SCANNING":
            next_expected = completed + timedelta(seconds=interval)
        state_name = str(state.get("state") or "WAITING").upper()
        worker = {"SCANNING": "running", "CURRENT": "healthy",
                  "STALE": "degraded", "ERROR": "degraded"}.get(state_name, "unavailable")
        freshness = "fresh" if state_name in {"SCANNING", "CURRENT"} else (
            "stale" if state_name in {"STALE", "ERROR"} and state.get("last_success_at") else "unavailable"
        )
        return {"state": state_name, "message": state.get("message") or "Scanner state is unavailable.",
                "market_data_state": str(state.get("market_data_state") or "UNKNOWN"),
                "worker_status": worker, "provider_status": "not_queried",
                "data_freshness": freshness,
                "last_started_at": parse_utc((raw or {}).get("last_started_at")),
                "last_completed_at": completed,
                "last_success_at": parse_utc((raw or {}).get("last_success_at")),
                "last_error_at": parse_utc((raw or {}).get("last_error_at")),
                "last_error_message": (raw or {}).get("last_error_message"),
                "scan_duration_seconds": _number((raw or {}).get("scan_duration")),
                "symbols_processed": (raw or {}).get("last_symbols_processed"),
                "symbols_attempted": state.get("current_symbols_attempted"),
                "symbol_count": state.get("current_symbol_count"),
                "results": state.get("current_results"), "failures": state.get("current_failures"),
                "expected_interval_seconds": interval, "next_expected_at": next_expected}

    def scanner(self):
        """Aggregate persisted Scanner state without providers, writes, or strategy execution."""
        now = self._now()
        sections = []
        failed_sections = set()

        try:
            provenance_reader = getattr(
                self.repository(), "latest_provenance_observations", None
            )
            provenance_observations = provenance_reader(("SPY", "QQQ")) \
                if callable(provenance_reader) else {}
            provenance_health = self._provenance_health()
            provenance_status = "persisted" if provenance_observations else "unavailable"
            if provenance_health.get("provenance_status") == "DEGRADED":
                provenance_status = "partial"
            sections.append({
                "section": "decision_provenance", "data_status": provenance_status,
                "message": provenance_health.get("error") if provenance_status == "partial"
                    else None if provenance_status == "persisted"
                    else "No canonical SPY/QQQ decision observations are deployed yet.",
            })
        except Exception:
            failed_sections.add("decision_provenance")
            provenance_observations = {}
            provenance_health = {"data_status": "error", "provenance_status": "DEGRADED",
                "scan_cycle_id": None, "cycle_status": None, "started_at": None,
                "completed_at": None, "error": "Decision provenance could not be read."}
            sections.append({"section": "decision_provenance", "data_status": "error",
                             "message": "Canonical decision observations could not be read."})

        try:
            health = self._scanner_health(now)
            health_status = "persisted" if health["last_started_at"] else "unavailable"
            sections.append({"section": "scanner_health", "data_status": health_status,
                             "message": None if health_status == "persisted" else "No completed scanner run is persisted yet."})
        except Exception:
            failed_sections.add("scanner_health")
            health = {"state": "UNAVAILABLE", "message": "Scanner health is unavailable.",
                      "market_data_state": "UNKNOWN", "worker_status": "unavailable",
                      "provider_status": "not_queried", "data_freshness": "unavailable",
                      "last_started_at": None, "last_completed_at": None, "last_success_at": None,
                      "last_error_at": None, "last_error_message": None,
                      "scan_duration_seconds": None, "symbols_processed": None,
                      "symbols_attempted": None, "symbol_count": None, "results": None,
                      "failures": None, "expected_interval_seconds": None, "next_expected_at": None}
            sections.append({"section": "scanner_health", "data_status": "error",
                             "message": "Persisted scanner health could not be read."})

        try:
            opportunity_rows = [row for row in self.repository().list_opportunities(limit=200)
                                if str(row.get("symbol") or "").upper() in SUPPORTED_SYMBOLS]
            sections.append({"section": "opportunities",
                             "data_status": "persisted" if opportunity_rows else "unavailable",
                             "message": None if opportunity_rows else "No persisted SPY or QQQ opportunities are available."})
        except Exception:
            failed_sections.add("opportunities")
            opportunity_rows = []
            sections.append({"section": "opportunities", "data_status": "error",
                             "message": "Persisted opportunities could not be read."})

        try:
            decision_rows = [row for row in self.capital_decisions(200)
                             if str(row.get("lane") or "").upper() in {"OB", "BROAD"}]
            sections.append({"section": "lane_decisions",
                             "data_status": "persisted" if decision_rows else "unavailable",
                             "message": None if decision_rows else "No persisted OB/BROAD decisions are available."})
        except Exception:
            failed_sections.add("lane_decisions")
            decision_rows = []
            sections.append({"section": "lane_decisions", "data_status": "error",
                             "message": "Persisted OB/BROAD decisions could not be read."})

        try:
            event_rows = self.repository().list_trade_event_summaries(limit=100)
            activity_state = "persisted" if event_rows or opportunity_rows or decision_rows else "unavailable"
            sections.append({"section": "recent_activity", "data_status": activity_state,
                             "message": None if activity_state == "persisted" else "No recent scanner activity is persisted."})
        except Exception:
            failed_sections.add("recent_activity")
            event_rows = []
            sections.append({"section": "recent_activity", "data_status": "partial"
                             if opportunity_rows or decision_rows else "error",
                             "message": "Trade events are unavailable; other persisted activity remains visible."})

        decision_map = {}
        for decision in decision_rows:
            key = (str(decision.get("opportunity_id")), str(decision.get("lane") or "").upper())
            decision_map.setdefault(key, decision)
        event_by_opportunity = {}
        event_by_symbol = {}
        for event in event_rows:
            opportunity_id = str(event.get("opportunity_id") or "")
            symbol = str(event.get("symbol") or "").upper()
            if opportunity_id:
                event_by_opportunity.setdefault(opportunity_id, event)
            if symbol in SUPPORTED_SYMBOLS:
                event_by_symbol.setdefault(symbol, event)

        opportunities = []
        for row in opportunity_rows[:20]:
            opportunity_id = str(row.get("id"))
            observed_at = parse_utc(row.get("signal_timestamp"))
            if observed_at is None:
                continue
            freshness, _ = self._scanner_freshness(observed_at, now)
            state = str(row.get("state") or "UNAVAILABLE").upper()
            event = event_by_opportunity.get(opportunity_id) or {}
            lane_decisions = [self._scanner_lane_decision(
                lane, decision_map.get((opportunity_id, lane))) for lane in ("OB", "BROAD")]
            contract = next((item.get("proposed_contract") for item in lane_decisions
                             if item.get("proposed_contract")), None)
            metadata = row.get("metadata") or {}
            contract = contract or metadata.get("option_symbol") or metadata.get("contract")
            targets = [_number(row.get(key)) for key in ("target_1", "target_2", "target_3")]
            opportunities.append({"opportunity_id": opportunity_id, "symbol": str(row.get("symbol")).upper(),
                "direction": row.get("direction"), "strategy": row.get("playbook"),
                "observed_at": observed_at, "score": _number(event.get("rule_score")),
                "confidence": _number(row.get("confidence")), "contract": contract,
                "entry": _number(row.get("entry_reference")), "stop": _number(row.get("stop_reference")),
                "targets": [value for value in targets if value is not None], "status": state,
                "actionable": state in {"CANDIDATE", "OPEN"}, "data_status": "persisted",
                "freshness": freshness, "context": row.get("evidence") or {},
                "lane_decisions": lane_decisions})

        instruments = []
        for symbol in ("SPY", "QQQ"):
            rows = [row for row in opportunity_rows if str(row.get("symbol") or "").upper() == symbol]
            current = next((row for row in rows if str(row.get("state") or "").upper()
                            in {"CANDIDATE", "OPEN"}), rows[0] if rows else None)
            if current is None:
                instruments.append({"symbol": symbol, "data_status": "error" if "opportunities" in failed_sections else "unavailable",
                    "underlying_price": None, "direction": None, "setup": None, "score": None,
                    "confidence": None, "signal_state": "UNAVAILABLE", "observed_at": None,
                    "signal_age_seconds": None, "freshness": "unavailable", "actionable": False,
                    "context": {}, "canonical_observation": provenance_observations.get(symbol)})
                continue
            observed_at = parse_utc(current.get("signal_timestamp"))
            freshness, age = self._scanner_freshness(observed_at, now)
            state = str(current.get("state") or "UNAVAILABLE").upper()
            event = event_by_opportunity.get(str(current.get("id"))) or event_by_symbol.get(symbol) or {}
            instruments.append({"symbol": symbol, "data_status": "persisted",
                "underlying_price": _number(event.get("underlying_price")),
                "direction": current.get("direction"), "setup": current.get("playbook"),
                "score": _number(event.get("rule_score")), "confidence": _number(current.get("confidence")),
                "signal_state": state, "observed_at": observed_at, "signal_age_seconds": age,
                "freshness": freshness, "actionable": state in {"CANDIDATE", "OPEN"},
                "context": current.get("evidence") or {},
                "canonical_observation": provenance_observations.get(symbol)})

        activity = []
        for decision in decision_rows:
            occurred_at = parse_utc(decision.get("decided_at"))
            if occurred_at is None:
                continue
            activity.append({"activity_id": f'decision:{decision.get("decision_id")}',
                "event_type": "LANE_DECISION", "occurred_at": occurred_at,
                "symbol": decision.get("symbol"), "direction": decision.get("direction"),
                "opportunity_id": str(decision.get("opportunity_id")), "lane": decision.get("lane"),
                "status": decision.get("state") or "UNAVAILABLE", "reason_code": decision.get("reason_code"),
                "description": decision.get("explanation") or "Persisted capital-lane decision."})
        for event in event_rows:
            occurred_at = parse_utc(event.get("event_timestamp"))
            if occurred_at is None:
                continue
            activity.append({"activity_id": f'event:{event.get("id")}',
                "event_type": event.get("event_type") or "TRADE_EVENT", "occurred_at": occurred_at,
                "symbol": event.get("symbol"), "direction": event.get("direction"),
                "opportunity_id": str(event.get("opportunity_id")) if event.get("opportunity_id") else None,
                "lane": None, "status": event.get("event_type") or "RECORDED",
                "reason_code": event.get("exit_reason"),
                "description": event.get("description") or "Persisted authoritative trade event."})
        for row in opportunity_rows:
            occurred_at = parse_utc(row.get("signal_timestamp"))
            if occurred_at is None:
                continue
            state = str(row.get("state") or "UNAVAILABLE").upper()
            activity.append({"activity_id": f'opportunity:{row.get("id")}',
                "event_type": "OPPORTUNITY", "occurred_at": occurred_at,
                "symbol": row.get("symbol"), "direction": row.get("direction"),
                "opportunity_id": str(row.get("id")), "lane": None, "status": state,
                "reason_code": None,
                "description": f'{row.get("playbook") or "Scanner"} opportunity persisted as {state.lower()}.'})
        activity.sort(key=lambda item: item["occurred_at"], reverse=True)

        available = bool(opportunity_rows or decision_rows or health.get("last_started_at"))
        overall = "partial" if failed_sections else "persisted" if available else "unavailable"
        return {"as_of": now, "market_status": "open" if market_is_open(now) else "closed",
                "data_status": overall, "research_control_role": "RESEARCH_CONTROL_ONLY",
                "provenance_health": provenance_health,
                "health": health, "instruments": instruments, "opportunities": opportunities,
                "recent_activity": activity[:16], "sections": sections}
