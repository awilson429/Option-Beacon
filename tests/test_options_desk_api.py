from datetime import datetime, timezone

from fastapi.testclient import TestClient

from api.main import create_app

NOW=datetime(2026,8,21,15,tzinfo=timezone.utc)


class Service:
    def __init__(self): self.calls=[]
    def trade_desk(self,symbol):
        self.calls.append(("trade_desk",symbol))
        return {"symbol":symbol,"price":500 if symbol=="SPY" else 600,"market_status":"open","data_status":"persisted","last_updated":NOW,
          "bias":{"direction":"CALL" if symbol=="SPY" else "PUT","label":f"{symbol} independent"},
          "trade_coverage":{"direction":None,"entry_trigger":None,"state":"watching"},
          "setup":{"state":"awaiting_contract","strike":None,"expiration":None,"dte":None,"spread":None,"contract":None},
          "context":{"level":"available","known_factors":[],"details":None},"confirmations":{"state":"context_only","items":[]},
          "market_condition":{"regime":"RANGE"},"session":{"pnl":None,"trades":0,"wins":0,"losses":0,"win_rate":None}}
    def options_desk(self): return {"instruments":{s:self.trade_desk(s) for s in ("SPY","QQQ")}}
    def scalp_state(self,symbol):
        self.calls.append(("scalp_state",symbol)); return {"symbol":symbol,"strategy":"SCALP_RESEARCH","mode":"SHADOW","market_status":"open","data_status":"unavailable","current":None}
    def scalp_performance(self,symbol):
        self.calls.append(("scalp_performance",symbol)); return {"symbol":symbol,"strategy":"SCALP_RESEARCH","metrics":{"opportunities":0,"evidence":"INSUFFICIENT"}}
    def scalp_compare(self):
        self.calls.append(("scalp_compare",None)); return {"strategy":"SCALP_RESEARCH","symbols":{"SPY":{"opportunities":0},"QQQ":{"opportunities":0}},"normalization":"per triggered contract; realistic P&L primary"}


def test_options_desk_returns_independent_symbol_state():
    service=Service(); client=TestClient(create_app(service=service)); body=client.get("/api/options-desk").json()
    assert body["instruments"]["SPY"]["price"]==500 and body["instruments"]["QQQ"]["price"]==600
    assert body["instruments"]["SPY"]["bias"]["direction"] != body["instruments"]["QQQ"]["bias"]["direction"]


def test_scalp_endpoints_and_schemas_are_shadow_read_only():
    service=Service(); client=TestClient(create_app(service=service))
    assert client.get("/api/scalp/SPY").json()["mode"]=="SHADOW"
    assert client.get("/api/scalp/QQQ/performance").json()["metrics"]["evidence"]=="INSUFFICIENT"
    assert set(client.get("/api/scalp/compare").json()["symbols"])=={"SPY","QQQ"}
    assert all(call[0] not in {"provider","save","write"} for call in service.calls)
    assert client.get("/api/scalp/AAPL").status_code==404


def test_existing_endpoint_remains_compatible_and_openapi_lists_new_contracts():
    client=TestClient(create_app(service=Service()))
    assert client.get("/api/trade-desk/SPY").status_code==200
    paths=client.get("/openapi.json").json()["paths"]
    assert {"/api/options-desk","/api/options-desk/{symbol}","/api/scalp/{symbol}","/api/scalp/{symbol}/performance","/api/scalp/compare"} <= set(paths)
