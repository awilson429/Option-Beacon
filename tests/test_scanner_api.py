from datetime import datetime, timedelta, timezone
import inspect

from fastapi.testclient import TestClient

from api.main import create_app
from api.services import OptionBeaconReadService


NOW = datetime(2026, 8, 24, 15, 0, tzinfo=timezone.utc)


class ScannerRepository:
    def __init__(self, *, empty=False, stale=False):
        self.empty = empty
        success = NOW - (timedelta(hours=2) if stale else timedelta(minutes=1))
        self.health = None if empty else {
            "scanner_id": "railway-production-worker",
            "last_started_at": success - timedelta(seconds=20),
            "last_completed_at": success,
            "last_success_at": success,
            "last_error_at": None,
            "last_error_message": None,
            "last_symbols_processed": 74,
            "scan_duration": 20.5,
            "market_data_state": "AVAILABLE",
            "current_run_number": 12,
            "current_symbols_attempted": 74,
            "current_symbol_count": 74,
            "current_results": 74,
            "current_failures": 0,
            "progress_updated_at": success,
            "current_owner_id": None,
        }

    def get_latest_scan_health(self):
        return self.health

    def get_scan_lock(self, scanner_id):
        return None

    def list_opportunities(self, limit=200):
        if self.empty:
            return []
        return [
            {"id": "spy-open", "symbol": "SPY", "direction": "Bullish",
             "playbook": "VWAP continuation", "signal_timestamp": NOW - timedelta(minutes=2),
             "state": "OPEN", "confidence": 78, "entry_reference": 642.25,
             "stop_reference": 641.82, "target_1": 642.9, "target_2": 643.4,
             "target_3": None, "evidence": {"regime": "range_chop"}, "metadata": {}},
            {"id": "qqq-closed", "symbol": "QQQ", "direction": "Bearish",
             "playbook": "Breakdown", "signal_timestamp": NOW - timedelta(hours=2),
             "state": "CLOSED", "confidence": 69, "entry_reference": 571.2,
             "stop_reference": None, "target_1": None, "target_2": None,
             "target_3": None, "evidence": {}, "metadata": {}},
        ]

    def list_capital_decisions(self, limit=200):
        if self.empty:
            return []
        common = {"opportunity_id": "spy-open", "symbol": "SPY", "direction": "CALL",
                  "proposed_contract": "SPY260824C00643000", "proposed_quantity": 2,
                  "proposed_capital_required": 228, "proposed_dollar_risk": 56,
                  "proposed_account_risk_pct": .22, "decided_at": NOW - timedelta(minutes=1)}
        return [
            {"decision_id": "ob-1", "lane": "OB", "decision_state": "TAKE",
             "reason_code": "ALL_RISK_CONTROLS_PASSED", "explanation": "OB controls passed.", **common},
            {"decision_id": "broad-1", "lane": "BROAD", "decision_state": "PASS",
             "reason_code": "CONTRACT_SPREAD_TOO_WIDE", "explanation": "Spread exceeds the lane limit.", **common},
            {"decision_id": "mirror-1", "lane": "MIRROR", "decision_state": "TAKE",
             "reason_code": "CONTROL", "explanation": "Research only.", **common},
        ]

    def list_trade_event_summaries(self, limit=100):
        if self.empty:
            return []
        return [{"id": "event-1", "opportunity_id": "spy-open", "symbol": "SPY",
                 "direction": "Bullish", "event_type": "TRADE_ENTERED",
                 "event_timestamp": NOW - timedelta(minutes=1), "underlying_price": 642.31,
                 "rule_score": 81, "exit_reason": None,
                 "description": "Authoritative trade entered."}]


def scanner_client(repository):
    service = OptionBeaconReadService(repository=repository, now=lambda: NOW)
    return TestClient(create_app(service=service)), service


def test_scanner_endpoint_contract_represents_spy_qqq_and_exact_lane_decisions(monkeypatch):
    monkeypatch.setenv("OPTIONBEACON_SCAN_SECONDS", "300")
    api, _ = scanner_client(ScannerRepository())
    response = api.get("/api/scanner")
    assert response.status_code == 200
    body = response.json()
    assert body["market_status"] == "open"
    assert body["health"]["state"] == "CURRENT"
    assert body["health"]["expected_interval_seconds"] == 300
    assert [row["symbol"] for row in body["instruments"]] == ["SPY", "QQQ"]
    spy = body["instruments"][0]
    assert spy["underlying_price"] == 642.31 and spy["score"] == 81
    assert spy["actionable"] is True and spy["freshness"] == "fresh"
    qqq = body["instruments"][1]
    assert qqq["underlying_price"] is None and qqq["freshness"] == "stale"

    opportunity = body["opportunities"][0]
    assert opportunity["contract"] == "SPY260824C00643000"
    decisions = {row["lane"]: row for row in opportunity["lane_decisions"]}
    assert set(decisions) == {"OB", "BROAD"}
    assert decisions["OB"]["state"] == "TAKE"
    assert decisions["BROAD"]["state"] == "PASS"
    assert decisions["BROAD"]["reason_code"] == "CONTRACT_SPREAD_TOO_WIDE"
    assert body["research_control_role"] == "RESEARCH_CONTROL_ONLY"
    assert "MIRROR" not in {row["lane"] for item in body["opportunities"] for row in item["lane_decisions"]}


def test_scanner_empty_state_and_unavailable_fields_are_explicit():
    api, _ = scanner_client(ScannerRepository(empty=True))
    body = api.get("/api/scanner").json()
    assert body["data_status"] == "unavailable"
    assert body["opportunities"] == [] and body["recent_activity"] == []
    assert body["health"]["state"] == "WAITING"
    assert all(row["data_status"] == "unavailable" for row in body["instruments"])
    assert all(row["underlying_price"] is None and row["score"] is None for row in body["instruments"])


def test_scanner_stale_health_and_recent_activity_are_truthful():
    api, _ = scanner_client(ScannerRepository(stale=True))
    body = api.get("/api/scanner").json()
    assert body["health"]["state"] == "STALE"
    assert body["health"]["worker_status"] == "degraded"
    assert body["health"]["data_freshness"] == "stale"
    kinds = {row["event_type"] for row in body["recent_activity"]}
    assert {"LANE_DECISION", "TRADE_ENTERED", "OPPORTUNITY"} <= kinds
    broad = next(row for row in body["recent_activity"] if row["lane"] == "BROAD")
    assert broad["status"] == "PASS" and broad["reason_code"] == "CONTRACT_SPREAD_TOO_WIDE"


def test_scanner_read_service_has_no_provider_or_write_calls():
    source = inspect.getsource(OptionBeaconReadService.scanner)
    assert "generate_signal" not in source
    assert "save_" not in source and "record_" not in source
    assert ".commit" not in source
