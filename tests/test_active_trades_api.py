import json
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from api.main import create_app
from api.services import OptionBeaconReadService


NOW = datetime(2026, 8, 24, 15, 0, tzinfo=timezone.utc)


class ActiveRepository:
    def __init__(self, *, trades=None, opportunities=None, positions=None, decisions=None):
        self.trades = trades or []
        self.opportunities = opportunities or []
        self.positions = positions or []
        self.decisions = decisions or []

    def list_open_trades(self):
        return self.trades

    def list_opportunities(self, limit=500):
        return self.opportunities[:limit]

    def list_active_trade_positions(self):
        return self.positions

    def list_capital_decisions(self, limit=50):
        return self.decisions[:limit]


def opportunity(identifier="opp-1", symbol="QQQ", direction="CALL"):
    return {"id": identifier, "symbol": symbol, "direction": direction,
            "playbook": "VWAP continuation", "metadata": {}}


def authoritative(identifier="auth-1", opportunity_id="opp-1", **changes):
    row = {"id": identifier, "opportunity_id": opportunity_id,
           "status": "OPEN", "opened_at": NOW - timedelta(minutes=7),
           "closed_at": None, "entry_price": 713.1, "last_price": 713.8,
           "stop_price": 712.6, "target_1": 714.0, "target_2": 714.8,
           "target_3": 715.5, "exit_price": None, "realized_result": None,
           "exit_reason": None, "metadata": {}}
    row.update(changes)
    return row


def capital(lane="OB", opportunity_id="opp-1", **changes):
    row = {"position_id": f"{lane}:paper-1", "lane": lane,
           "source_trade_id": "paper-1", "opportunity_id": opportunity_id,
           "symbol": "QQQ", "direction": "CALL", "strategy": lane,
           "option_symbol": "QQQ260824C00713000", "strike": 713,
           "expiration": "2026-08-24", "dte": 0, "quantity": 8,
           "realistic_entry": 1.42, "current_premium": 1.61,
           "capital_committed": 1136, "initial_dollar_risk": 112,
           "unrealized_pnl": 152, "stop_price": None, "targets_json": "[]",
           "opened_at": NOW - timedelta(minutes=7), "last_mark_at": NOW - timedelta(seconds=20),
           "status": "OPEN", "metadata_json": json.dumps({}),
           "paper_option_type": "CALL", "paper_underlying_entry": 713.1,
           "paper_option_mark": 1.61, "paper_unrealized_return_pct": 13.4,
           "paper_last_updated_at": NOW - timedelta(seconds=20),
           "paper_metadata_json": json.dumps({"position": {"last_underlying_price": 713.8}})}
    row.update(changes)
    return row


def service(repository):
    return OptionBeaconReadService(repository=repository, now=lambda: NOW)


def test_no_active_trades_returns_an_empty_list():
    assert service(ActiveRepository()).active_trades() == []


def test_one_active_trade_exposes_exact_contract_risk_plan_pnl_and_time():
    repo = ActiveRepository(
        trades=[authoritative()], opportunities=[opportunity()], positions=[capital()],
        decisions=[{"lane": "OB", "opportunity_id": "opp-1", "decision_state": "TAKE",
                    "proposed_account_risk_pct": 0.45}],
    )
    row = service(repo).active_trades()[0]
    assert row["id"] == "OB:paper-1" and row["lane"] == "OB"
    assert row["lane_role"] == "AUTHORITATIVE"
    assert row["contract_symbol"] == "QQQ260824C00713000"
    assert (row["strike"], row["option_type"], row["expiration"], row["dte"], row["quantity"]) == (
        713.0, "CALL", "2026-08-24", 0, 8)
    assert row["option_entry_premium"] == 1.42 and row["latest_option_mark"] == 1.61
    assert row["unrealized_pnl"] == 152 and row["unrealized_return_pct"] == 13.4
    assert row["capital_committed"] == 1136 and row["initial_dollar_risk"] == 112
    assert row["account_risk_pct"] == 0.45 and row["time_in_trade_seconds"] == 420
    assert (row["stop"], row["target_1"], row["target_2"], row["target_3"]) == (
        712.6, 714.0, 714.8, 715.5)
    assert row["data_freshness"] == "fresh"


def test_multiple_lanes_remain_distinct_and_mirror_is_excluded():
    positions = [capital("OB"), capital("BROAD", quantity=3), capital("MIRROR")]
    repo = ActiveRepository(trades=[authoritative()], opportunities=[opportunity()], positions=positions)
    rows = service(repo).active_trades()
    assert [(row["lane"], row["lane_role"]) for row in rows] == [
        ("OB", "AUTHORITATIVE"), ("BROAD", "PAPER")]
    assert all("MIRROR" not in row["id"] for row in rows)


def test_unmatched_authoritative_trade_is_ob_and_control_trade_is_excluded():
    control = authoritative("control", "opp-2", metadata={"execution_lane": "MIRROR"})
    repo = ActiveRepository(
        trades=[authoritative(), control],
        opportunities=[opportunity(), opportunity("opp-2", "SPY", "PUT")],
    )
    rows = service(repo).active_trades()
    assert len(rows) == 1 and rows[0]["id"] == "auth-1" and rows[0]["lane"] == "OB"
    assert rows[0]["latest_option_mark"] is None
    assert rows[0]["data_freshness"] == "unavailable"


def test_missing_and_stale_marks_are_localized_without_losing_positions():
    stale = capital("OB", last_mark_at=NOW - timedelta(minutes=20),
                    paper_last_updated_at=NOW - timedelta(minutes=20))
    missing = capital("BROAD", current_premium=None, paper_option_mark=None,
                      last_mark_at=None, paper_last_updated_at=None)
    repo = ActiveRepository(trades=[authoritative()], opportunities=[opportunity()],
                            positions=[stale, missing])
    rows = {row["lane"]: row for row in service(repo).active_trades()}
    assert rows["OB"]["data_freshness"] == "stale"
    assert rows["BROAD"]["data_freshness"] == "unavailable"
    assert rows["BROAD"]["latest_option_mark"] is None


def test_management_is_passed_through_only_when_persisted():
    managed = authoritative(metadata={"exit_score": 76, "exit_state": "HOLD",
        "trade_coach_status": "THESIS INTACT", "momentum_state": "MODERATING",
        "structure_state": "ABOVE VWAP", "last_management_update": NOW.isoformat()})
    repo = ActiveRepository(trades=[managed], opportunities=[opportunity()], positions=[capital()])
    row = service(repo).active_trades()[0]
    assert row["exit_score"] == 76 and row["exit_state"] == "HOLD"
    assert row["management_data_status"] == "persisted"
    assert row["last_management_update"] == NOW

    unavailable = service(ActiveRepository(trades=[authoritative()], opportunities=[opportunity()])).active_trades()[0]
    assert unavailable["exit_score"] is None
    assert unavailable["trade_coach_status"] is None
    assert unavailable["management_data_status"] == "unavailable"


def test_fastapi_active_contract_is_additive_and_serializable():
    repo = ActiveRepository(trades=[authoritative()], opportunities=[opportunity()], positions=[capital()])
    response = TestClient(create_app(service=service(repo))).get("/api/trades/active")
    assert response.status_code == 200
    body = response.json()[0]
    assert body["opportunity_id"] == "opp-1"
    assert body["lane"] == "OB" and body["contract_symbol"].startswith("QQQ")
    assert body["mark_timestamp"].endswith(("Z", "+00:00"))
