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
    def system_status(self):
        return {"status": "ok" if self.available else "degraded", "market_status": "closed",
            "database": "connected" if self.available else "unavailable", "data_freshness": "unavailable",
            "worker_status": "unavailable", "worker_last_success": None, "provider_status": "not_queried", "timestamp": NOW}
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


def test_openapi_and_safe_cors_configuration():
    schema = client().get("/openapi.json").json()
    assert "/api/trade-desk/{symbol}" in schema["paths"]
    assert cors_origins({}) == ["http://localhost:3000"]
    assert cors_origins({"OPTIONBEACON_CORS_ORIGINS": "*, https://example.com"}) == ["https://example.com"]


def test_api_import_has_no_streamlit_dependency_and_repository_is_read_only():
    for module in (api.main, api.dependencies, api.services):
        assert "streamlit" not in inspect.getsource(module)
    assert ReadOnlyTradeRepository.initialize(object()) is None
    source = inspect.getsource(ReadOnlyTradeRepository.connection)
    assert "SET TRANSACTION READ ONLY" in source and "rollback" in source and ".commit" not in source
