from datetime import datetime, timezone
import inspect

from fastapi.testclient import TestClient

import api.dependencies
import api.main
import api.services
from api.main import cors_origins, create_app
from api.services import ReadOnlyTradeRepository

NOW = datetime(2026, 8, 21, 15, 0, tzinfo=timezone.utc)


class FakeService:
    def __init__(self, available=True):
        self.available = available
        self.requested_limit = None

    def database_available(self): return self.available
    def active_trades(self): return [self._trade("open", "OPEN")]
    def recent_trades(self, limit): self.requested_limit = limit; return [self._trade("recent", "CLOSED")]
    def market(self, symbol):
        return {"symbol": symbol, "market_status": "open", "data_status": "persisted", "price": 500.25,
            "bias": "CALL", "regime": "range_chop", "last_updated": NOW, "metadata": {}}
    def trade_desk(self, symbol):
        return {"symbol": symbol, "price": None, "market_status": "closed", "data_status": "unavailable", "last_updated": None,
            "bias": {"direction": None, "label": None}, "trade_coverage": {"direction": None, "entry_trigger": None, "state": "unavailable"},
            "setup": {"state": "unavailable", "strike": None, "expiration": None, "dte": None, "spread": None, "contract": None},
            "context": {"level": "unavailable", "known_factors": [], "details": None},
            "confirmations": {"state": "unavailable", "items": []}, "market_condition": {"regime": None},
            "session": {"pnl": None, "trades": 0, "wins": 0, "losses": 0, "win_rate": None}}
    def trade_desk_home(self):
        return {"as_of": NOW, "data_status": "persisted",
            "session": {"realized_pnl": 0.2, "unrealized_pnl": 0.1, "total_pnl": 0.3,
                "trades": 1, "wins": 1, "losses": 0, "win_rate": 100.0, "active_trades": 1},
            "active": [],
            "lanes": [{"key": "CONTROL_RESEARCH", "label": "MIRROR / CONTROL RESEARCH",
                "role": "RESEARCH_CONTROL", "active_trades": 0, "trades_today": 0,
                "realized_pnl": None, "description": "Research/control comparison only; not a primary live lane"}],
            "recent_activity": []}
    def system_status(self):
        return {"status": "ok" if self.available else "degraded", "market_status": "closed",
            "database": "connected" if self.available else "unavailable", "data_freshness": "unavailable",
            "worker_status": "unavailable", "worker_last_success": None, "provider_status": "not_queried", "timestamp": NOW}
    def capital_overview(self):
        return {"as_of":NOW,"mode":"SIMULATION","mirror_role":"RESEARCH_CONTROL_ONLY",
            "lanes":[self.capital_lane("OB"),self.capital_lane("BROAD")]}
    def capital_lane(self, lane):
        return {"lane":lane,"data_status":"persisted","starting_capital":25000,
            "current_equity":25100,"cash_available":25000,"capital_committed":100,
            "net_pnl":100,"return_pct":0.4,"realized_pnl":90,"unrealized_pnl":10,
            "fees":2,"slippage":3,"peak_equity":25200,"current_drawdown_pct":0.4,
            "maximum_drawdown_pct":1.2,"daily_pnl":25,"open_risk":50,"open_positions":1,
            "risk_state":"NORMAL","readiness_status":"EARLY_RESEARCH","metrics":{"trades":5},"updated_at":NOW}
    def capital_compare(self):
        overview=self.capital_overview()
        return {"as_of":NOW,"lanes":overview["lanes"],"winner":"INSUFFICIENT_EVIDENCE",
            "evidence":"INSUFFICIENT","normalization":"independent starting capital; realistic simulated P&L primary"}
    def capital_decisions(self, limit=50):
        return [{"decision_id":"d1","lane":"OB","opportunity_id":"opp","symbol":"QQQ",
            "direction":"CALL","state":"TAKE","reason_code":"ALL_RISK_CONTROLS_PASSED",
            "explanation":"All controls passed.","proposed_contract":"QQQ-C","proposed_quantity":2,
            "proposed_capital_required":200,"proposed_dollar_risk":50,
            "proposed_account_risk_pct":0.2,"decided_at":NOW}]
    def risk_status(self):
        return {"as_of":NOW,"lanes":[{"lane":"OB","risk_state":"NORMAL","daily_pnl":25,
            "daily_loss_limit":500,"open_risk":50,"maximum_open_risk":375,
            "current_drawdown_pct":0.4,"entries_allowed":True}]}
    @staticmethod
    def _trade(identifier, status):
        return {"id": identifier, "opportunity_id": "opp", "symbol": "QQQ", "direction": "CALL", "setup": "ORB",
            "status": status, "opened_at": NOW, "closed_at": NOW if status == "CLOSED" else None, "entry_price": 1.2,
            "last_price": 1.3, "exit_price": 1.4 if status == "CLOSED" else None, "realized_result": 0.2 if status == "CLOSED" else None,
            "exit_reason": "TARGET" if status == "CLOSED" else None, "metadata": {}}


def client(service=None): return TestClient(create_app(service=service or FakeService()))


def test_health_and_database_unavailable_behavior():
    assert client().get("/api/health").json()["database"] == "connected"
    response = client(FakeService(False)).get("/api/health")
    assert response.status_code == 200 and response.json()["status"] == "degraded"


def test_trade_desk_schema_preserves_unavailable_values():
    response = client().get("/api/trade-desk/qqq")
    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "QQQ" and body["price"] is None
    assert body["confirmations"] == {"state": "unavailable", "items": []}


def test_trade_desk_home_contract_keeps_control_research_demoted():
    response = client().get("/api/trade-desk")
    assert response.status_code == 200
    body = response.json()
    assert body["session"]["total_pnl"] == 0.3
    assert body["lanes"][0]["role"] == "RESEARCH_CONTROL"
    assert "primary live lane" in body["lanes"][0]["description"]


def test_invalid_symbol_is_rejected():
    response = client().get("/api/trade-desk/AAPL")
    assert response.status_code == 404 and "Unsupported symbol" in response.json()["detail"]


def test_active_and_recent_trades_use_service_and_bounded_limit():
    service = FakeService(); api = client(service)
    assert api.get("/api/trades/active").json()[0]["status"] == "OPEN"
    assert api.get("/api/trades/recent?limit=7").json()[0]["status"] == "CLOSED"
    assert service.requested_limit == 7
    assert api.get("/api/trades/recent?limit=0").status_code == 422


def test_market_and_system_status_contracts():
    api = client()
    assert api.get("/api/market/SPY").json()["source"] == "persisted_state"
    status = api.get("/api/system/status").json()
    assert status["provider_status"] == "not_queried" and "timestamp" in status


def test_capital_readiness_api_contracts_are_read_only_and_mirror_is_not_a_lane():
    api=client()
    overview=api.get("/api/capital").json()
    assert [lane["lane"] for lane in overview["lanes"]] == ["OB","BROAD"]
    assert overview["mirror_role"] == "RESEARCH_CONTROL_ONLY"
    assert api.get("/api/capital/OB").json()["starting_capital"] == 25000
    assert api.get("/api/capital/compare").json()["winner"] == "INSUFFICIENT_EVIDENCE"
    assert api.get("/api/capital/decisions/recent").json()[0]["state"] == "TAKE"
    assert api.get("/api/risk/status").json()["lanes"][0]["entries_allowed"] is True
    assert api.get("/api/capital/MIRROR").status_code == 404


def test_openapi_and_safe_cors_configuration():
    schema = client().get("/openapi.json").json()
    assert "/api/trade-desk" in schema["paths"]
    assert "/api/trade-desk/{symbol}" in schema["paths"]
    assert cors_origins({}) == ["http://localhost:3000"]
    assert cors_origins({"OPTIONBEACON_CORS_ORIGINS": "*, https://example.com"}) == ["https://example.com"]


def test_api_import_has_no_streamlit_dependency_and_repository_is_read_only():
    for module in (api.main, api.dependencies, api.services):
        assert "streamlit" not in inspect.getsource(module)
    assert ReadOnlyTradeRepository.initialize(object()) is None
    source = inspect.getsource(ReadOnlyTradeRepository.connection)
    assert "SET TRANSACTION READ ONLY" in source and "rollback" in source and ".commit" not in source


def test_trade_desk_home_aggregates_known_pnl_and_lane_roles():
    active = {**FakeService._trade("active", "OPEN"), "setup": "ORB",
        "metadata": {"execution_lane": "BROAD", "unrealized_pnl": 0.35}}
    ob_closed = {**FakeService._trade("ob-win", "CLOSED"), "realized_result": 0.8}
    mirror_closed = {**FakeService._trade("mirror-loss", "CLOSED"), "setup": "MIRROR_CONTROL",
        "realized_result": -0.3}

    class HomeService(api.services.OptionBeaconReadService):
        def active_trades(self): return [active]
        def recent_trades(self, limit): return [ob_closed, mirror_closed]
        def _capital_state_rows(self): return []
        def _capital_decision_rows(self, limit): return []
        def _capital_position_rows(self): return []

    body = HomeService(now=lambda: NOW).trade_desk_home()
    assert body["session"] == {"realized_pnl": 0.5, "unrealized_pnl": 0.35,
        "total_pnl": 0.85, "trades": 2, "wins": 1, "losses": 1,
        "win_rate": 50.0, "active_trades": 1}
    lanes = {lane["key"]: lane for lane in body["lanes"]}
    assert lanes["OB"]["role"] == "AUTHORITATIVE"
    assert lanes["BROAD"]["active_trades"] == 1
    assert lanes["CONTROL_RESEARCH"]["role"] == "RESEARCH_CONTROL"
    assert body["recent_activity"][1]["strategy"] == "MIRROR / CONTROL RESEARCH"
