import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.services import OptionBeaconReadService


NOW = datetime(2026, 8, 25, 16, 0, tzinfo=timezone.utc)


class JournalRepository:
    def __init__(self, *, positions=None, executions=None, paper_positions=None,
                 opportunities=None, authoritative=None, snapshots=None):
        self.positions = positions or []
        self.executions = executions or []
        self.paper_positions = paper_positions or []
        self.opportunities = opportunities or []
        self.authoritative = authoritative or []
        self.snapshots = snapshots or []

    def list_capital_positions(self): return self.positions
    def list_paper_execution_trades(self): return self.executions
    def list_paper_execution_positions(self): return self.paper_positions
    def list_opportunities(self, limit=500): return self.opportunities[:limit]
    def list_recent_trades(self, limit=100): return self.authoritative[:limit]

    def trade_management_snapshot_summaries(self, identities):
        result = {}
        for identity in identities:
            rows = [row for row in self.snapshots
                    if (row["trade_id"], row["lane"]) == identity]
            if rows:
                result[identity] = {"count": len(rows), "latest": rows[-1]}
        return result

    def list_trade_management_snapshots(self, trade_id, *, lane=None, limit=5000):
        return [row for row in self.snapshots if row["trade_id"] == trade_id and
                (lane is None or row["lane"] == lane.upper())][:limit]


def position(lane="OB", source="paper-1", opportunity_id="opp-1", **changes):
    row = {
        "position_id": f"{lane}:{source}", "lane": lane, "source_trade_id": source,
        "opportunity_id": opportunity_id, "symbol": "QQQ", "direction": "CALL",
        "strategy": lane, "option_symbol": "QQQ260825C00713000", "strike": 713,
        "expiration": "2026-08-25", "dte": 0, "quantity": 2,
        "theoretical_entry": 1.38, "realistic_entry": 1.42, "current_premium": 1.65,
        "realistic_exit": 1.62, "stop_price": 712.5,
        "targets_json": json.dumps([714.0, 714.8, 715.5]), "capital_committed": 284,
        "initial_dollar_risk": 56, "unrealized_pnl": 0, "realistic_pnl": 35,
        "fees": 3, "slippage": 4, "opened_at": NOW - timedelta(minutes=12),
        "last_mark_at": NOW - timedelta(minutes=1), "closed_at": NOW,
        "status": "CLOSED", "metadata_json": json.dumps({"exit_reason": "TARGET"}),
    }
    row.update(changes)
    return row


def execution(source="paper-1", **changes):
    row = {
        "trade_id": source, "source_signal_id": "opp-1", "opportunity_id": "opp-1",
        "symbol": "QQQ", "option_symbol": "QQQ260825C00713000", "option_type": "CALL",
        "strike": 713, "expiration": "2026-08-25", "quantity": 2,
        "entry_option_price": 1.40, "total_debit": 280,
        "opened_at": NOW - timedelta(minutes=12), "exit_option_price": 1.62,
        "exit_value": 324, "realized_pnl_dollars": 44, "realized_return_pct": 15.71,
        "exit_reason": "TARGET", "duration_minutes": 12, "mfe_dollars": 52,
        "mae_dollars": -18, "mfe_pct": 18.57, "mae_pct": -6.43,
        "closed_at": NOW, "status": "CLOSED", "execution_mode": "PAPER",
        "contract_metadata_json": "{}", "created_at": NOW,
    }
    row.update(changes)
    return row


def paper_position(source="paper-1", **changes):
    row = {"trade_id": source, "entry_underlying_price": 713.1,
           "option_type": "CALL", "entry_option_price": 1.40}
    row.update(changes)
    return row


def opportunity(identifier="opp-1", symbol="QQQ"):
    return {"id": identifier, "symbol": symbol, "direction": "CALL",
            "playbook": "VWAP continuation", "source_version": "scanner-v7", "metadata": {}}


def authoritative(identifier="auth-1", opportunity_id="opp-1", **changes):
    row = {"id": identifier, "opportunity_id": opportunity_id,
           "opened_at": NOW - timedelta(minutes=12), "closed_at": NOW,
           "status": "CLOSED", "entry_price": 713.1, "exit_price": 714.2,
           "stop_price": 712.5, "target_1": 714.0, "target_2": 714.8,
           "target_3": 715.5, "exit_reason": "TARGET", "realized_result": 1.1,
           "metadata": {}}
    row.update(changes)
    return row


def snapshot(trade_id="OB:paper-1", lane="OB", **changes):
    row = {"snapshot_id": "snap-1", "trade_id": trade_id, "opportunity_id": "opp-1",
           "lane": lane, "lane_role": "AUTHORITATIVE", "symbol": "QQQ",
           "contract_symbol": "QQQ260825C00713000", "captured_at": NOW,
           "source_timestamp": NOW, "trade_status": "CLOSED", "quantity": 2,
           "entry_timestamp": NOW - timedelta(minutes=12), "entry_premium": 1.42,
           "latest_option_mark": 1.62, "latest_underlying": 714.2, "mark_timestamp": NOW,
           "time_in_trade_seconds": 720, "current_stop": 713.3, "target_1": 714,
           "target_2": 714.8, "target_3": 715.5, "exit_score": 64,
           "exit_label": "PROTECT", "management_source": "test", "stale": False,
           "missing_data": [], "state_fingerprint": "fingerprint"}
    row.update(changes)
    return row


def service(repository):
    return OptionBeaconReadService(repository=repository, now=lambda: NOW)


def complete_repository(**changes):
    values = dict(positions=[position()], executions=[execution()],
                  paper_positions=[paper_position()], opportunities=[opportunity()],
                  authoritative=[authoritative()], snapshots=[snapshot()])
    values.update(changes)
    return JournalRepository(**values)


def test_no_historical_trades_has_explicit_empty_metrics():
    result = service(JournalRepository()).trade_history(status="CLOSED")
    assert result["trades"] == [] and result["total_count"] == 0
    assert result["summary"]["realized_pnl"] is None
    assert [lane["lane"] for lane in result["lanes"]] == ["OB", "BROAD"]


def test_one_closed_trade_exposes_authoritative_contract_entry_exit_plan_and_management():
    row = service(complete_repository()).trade_history(status="CLOSED")["trades"][0]
    assert (row["trade_id"], row["opportunity_id"], row["lane"]) == (
        "OB:paper-1", "opp-1", "OB")
    assert (row["contract_symbol"], row["option_type"], row["quantity"]) == (
        "QQQ260825C00713000", "CALL", 2)
    assert row["underlying_entry"] == 713.1 and row["underlying_exit"] == 714.2
    assert row["option_entry_premium"] == 1.42 and row["option_exit_premium"] == 1.62
    assert row["realized_pnl"] == 35 and row["realized_return_pct"] == pytest.approx(12.32394)
    assert row["r_multiple"] == 0.625 and row["result"] == "WIN"
    assert row["mfe_pct"] == 18.57 and row["mae_pct"] == -6.43
    assert (row["initial_stop"], row["target_1"], row["target_3"]) == (712.5, 714, 715.5)
    assert row["management_history_available"] is True
    assert row["management_snapshot_count"] == 1
    assert row["final_exit_score"] == 64 and row["final_management_label"] == "PROTECT"


def test_multiple_lanes_same_symbol_stay_separate_and_mirror_is_excluded():
    positions = [position("OB"), position("BROAD", realistic_pnl=-20),
                 position("MIRROR", realistic_pnl=999)]
    rows = service(complete_repository(positions=positions)).trade_history(status="CLOSED")
    assert [(row["lane"], row["realized_pnl"]) for row in rows["trades"]] == [
        ("OB", 35), ("BROAD", -20)]
    assert rows["summary"]["realized_pnl"] == 15
    lane_metrics = {lane["lane"]: lane for lane in rows["lanes"]}
    assert lane_metrics["OB"]["wins"] == 1 and lane_metrics["BROAD"]["losses"] == 1
    assert rows["control_research"] is None


def test_win_loss_breakeven_and_aggregate_metrics_use_realistic_capital_pnl():
    positions = [position(source="win", realistic_pnl=60),
                 position(source="loss", opportunity_id="opp-2", realistic_pnl=-30),
                 position(source="flat", opportunity_id="opp-3", realistic_pnl=0)]
    result = service(complete_repository(positions=positions)).trade_history(status="CLOSED")
    metrics = result["summary"]
    assert (metrics["wins"], metrics["losses"], metrics["breakeven"]) == (1, 1, 1)
    assert metrics["win_rate"] == pytest.approx(100 / 3)
    assert metrics["realized_pnl"] == 30 and metrics["profit_factor"] == 2
    assert metrics["average_winner"] == 60 and metrics["average_loser"] == -30
    assert {row["result"] for row in result["trades"]} == {"WIN", "LOSS", "BREAKEVEN"}


def test_filters_dates_and_pagination_apply_before_aggregate_metrics():
    older = position("BROAD", "older", "opp-2", symbol="SPY", realistic_pnl=-20,
                     opened_at=NOW - timedelta(days=10), closed_at=NOW - timedelta(days=9))
    rows = [position(), older]
    svc = service(complete_repository(positions=rows))
    assert svc.trade_history(lane="BROAD")["trades"][0]["trade_id"] == "BROAD:older"
    assert svc.trade_history(symbol="SPY")["total_count"] == 1
    assert svc.trade_history(result="LOSS")["total_count"] == 1
    assert svc.trade_history(date_from=(NOW - timedelta(days=1)).date())["total_count"] == 1
    paged = svc.trade_history(limit=1, offset=1)
    assert paged["total_count"] == 2 and len(paged["trades"]) == 1
    assert paged["summary"]["total_trades"] == 2


def test_missing_legacy_fields_remain_unavailable_and_are_not_zero_filled():
    sparse = position(option_symbol=None, strike=None, realistic_exit=None,
                      realistic_pnl=None, stop_price=None, targets_json="[]",
                      metadata_json="{}")
    row = service(JournalRepository(positions=[sparse], opportunities=[opportunity()],
                                    authoritative=[], executions=[], paper_positions=[])
                  ).trade_history()["trades"][0]
    assert row["contract_symbol"] is None and row["underlying_exit"] is None
    assert row["option_exit_premium"] is None and row["realized_pnl"] is None
    assert row["result"] == "UNAVAILABLE"
    assert row["management_history_available"] is False
    assert "canonical_management_history" in row["missing_data"]


def test_management_summary_and_timeline_require_exact_trade_and_lane_not_symbol():
    misleading = [snapshot("BROAD:paper-1", "BROAD", exit_score=99),
                  snapshot("OB:different", "OB", exit_score=100)]
    repo = complete_repository(snapshots=misleading)
    row = service(repo).trade_history()["trades"][0]
    assert row["management_history_available"] is False and row["final_exit_score"] is None
    client = TestClient(create_app(service=service(repo)))
    assert client.get("/api/trades/OB:paper-1/management?lane=OB").status_code == 404


def test_history_api_serializes_contract_and_validates_filters():
    client = TestClient(create_app(service=service(complete_repository())))
    response = client.get("/api/trades/history?status=CLOSED&lane=OB&symbol=QQQ&limit=1")
    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 1 and body["trades"][0]["result"] == "WIN"
    assert body["trades"][0]["entry_timestamp"].endswith(("Z", "+00:00"))
    assert client.get("/api/trades/history?lane=MIRROR").status_code == 422


def test_one_malformed_record_does_not_break_valid_journal_history():
    malformed = position(source="broken", opened_at=object())
    result = service(complete_repository(positions=[malformed, position()])).trade_history()
    assert result["total_count"] == 1 and result["trades"][0]["trade_id"] == "OB:paper-1"
