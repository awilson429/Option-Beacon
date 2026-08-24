"""Read-only adapters over existing OptionBeacon persistence services."""
from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas_market_calendars as market_calendars

from trade_repository import RepositoryUnavailable, TradeRepository, parse_utc

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
