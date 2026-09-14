from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
import math
import time

from fastapi.testclient import TestClient

from api.main import create_app
from api.serialization import normalize_json_value
from api.services import OptionBeaconReadService

NOW = datetime(2026, 9, 13, 14, 30, tzinfo=timezone.utc)


def health(*, stale=False):
    return {"state": "STALE" if stale else "CURRENT", "message": "Persisted scanner state.",
        "market_data_state": "AVAILABLE", "worker_status": "degraded" if stale else "healthy",
        "provider_status": "not_queried", "data_freshness": "stale" if stale else "fresh",
        "last_started_at": NOW, "last_completed_at": NOW, "last_success_at": NOW,
        "last_error_at": None, "last_error_message": None, "scan_duration_seconds": 2.5,
        "symbols_processed": 2, "symbols_attempted": 2, "symbol_count": 2,
        "results": 2, "failures": 0, "expected_interval_seconds": 300,
        "next_expected_at": NOW}


def instrument(symbol, *, available=True, nonfinite=False):
    score = float("nan") if nonfinite else 81.0
    observation = None if not available else {"observation_id": f"obs-{symbol}",
        "scan_cycle_id": "cycle-1", "symbol": symbol, "observed_at": NOW,
        "data_timestamp": NOW, "underlying_price": float("inf") if nonfinite else 500.25,
        "session_state": "open", "direction": "CALL", "data_quality": "complete",
        "stale": False, "signal": "CALL", "setup_state": "OPEN",
        "qualification_state": "TAKE", "reason_code": "QUALIFIED",
        "explanation": "Persisted decision.", "total_score": score, "confidence": 0.8,
        "bullish_score": 81, "bearish_score": 12, "component_scores": {},
        "indicators": {"rsi": score}, "reasons": [], "opportunity_id": "opp-1",
        "source_version": "v1"}
    return {"symbol": symbol, "data_status": "persisted" if available else "unavailable",
        "underlying_price": None if not available else 500.25, "direction": "CALL" if available else None,
        "setup": "ORB" if available else None, "score": None if not available else score,
        "confidence": None if not available else .8, "signal_state": "OPEN" if available else "UNAVAILABLE",
        "observed_at": NOW if available else None, "signal_age_seconds": 0 if available else None,
        "freshness": "fresh" if available else "unavailable", "actionable": available,
        "context": {}, "canonical_observation": observation}


class ProjectionService(OptionBeaconReadService):
    def __init__(self, *, empty=False, stale=False, nonfinite=False):
        super().__init__(now=lambda: NOW)
        self.empty, self.stale, self.nonfinite = empty, stale, nonfinite
        self.calls = []

    def scanner(self):
        self.calls.append("scanner")
        instruments = [instrument(symbol, available=not self.empty, nonfinite=self.nonfinite)
                       for symbol in ("SPY", "QQQ")]
        opportunities = [] if self.empty else [{"opportunity_id": "opp-1", "symbol": "SPY",
            "direction": "CALL", "strategy": "ORB", "observed_at": NOW, "score": 81,
            "confidence": .8, "contract": None, "entry": None, "stop": None, "targets": [],
            "status": "OPEN", "actionable": True, "data_status": "persisted", "freshness": "fresh",
            "context": {}, "lane_decisions": [{"lane": "OB", "data_status": "persisted",
                "decision_id": "decision-1",
                "state": "TAKE", "reason_code": "QUALIFIED", "explanation": "Persisted decision.",
                "proposed_contract": None, "proposed_quantity": None,
                "proposed_capital_required": None, "proposed_dollar_risk": None,
                "proposed_account_risk_pct": None, "decided_at": NOW}]}]
        return {"as_of": NOW, "market_status": "open", "data_status": "unavailable" if self.empty else "persisted",
            "research_control_role": "RESEARCH_CONTROL_ONLY", "provenance_health": {
                "data_status": "unavailable" if self.empty else "persisted",
                "provenance_status": "UNAVAILABLE" if self.empty else "COMPLETE",
                "scan_cycle_id": None if self.empty else "cycle-1", "cycle_status": None if self.empty else "COMPLETED",
                "started_at": None if self.empty else NOW, "completed_at": None if self.empty else NOW, "error": None},
            "health": health(stale=self.stale or self.empty), "instruments": instruments,
            "opportunities": opportunities, "recent_activity": [], "sections": []}

    def active_trades(self): self.calls.append("active_trades"); return []
    def recent_trades(self, limit): self.calls.append(("recent_trades", limit)); return []
    def system_status(self):
        self.calls.append("system_status")
        return {"status": "ok", "market_status": "open", "database": "connected",
            "data_freshness": "stale" if self.stale else "fresh", "worker_status": "healthy",
            "worker_last_success": NOW, "provider_status": "not_queried", "timestamp": NOW}


def test_snapshot_endpoint_schema_symbols_read_only_and_bounded():
    service = ProjectionService()
    started = time.perf_counter()
    response = TestClient(create_app(service=service)).get("/api/live/snapshot")
    assert response.status_code == 200
    body = response.json()
    assert time.perf_counter() - started < 1
    assert set(body) == {"schema_version", "snapshot_id", "generated_at", "data_status", "market", "symbols",
                         "scanner", "decisions", "active_trades", "recent_trades", "system", "provenance"}
    assert body["schema_version"] == "1" and set(body["symbols"]) == {"SPY", "QQQ"}
    assert len(body["snapshot_id"]) == 20
    assert service.calls == ["scanner", "active_trades", ("recent_trades", 20), "system_status"]


def test_snapshot_strict_json_normalization_and_missing_is_not_zero():
    body = TestClient(create_app(service=ProjectionService(nonfinite=True))).get("/api/live/snapshot").json()
    assert body["symbols"]["SPY"]["observation"]["underlying_price"] is None
    assert body["symbols"]["SPY"]["observation"]["total_score"] is None
    assert body["symbols"]["SPY"]["scanner"]["score"] is None
    assert "NaN" not in str(body) and "Infinity" not in str(body)


def test_empty_and_stale_snapshot_are_explicit():
    body = TestClient(create_app(service=ProjectionService(empty=True))).get("/api/live/snapshot").json()
    assert body["data_status"] == "unavailable"
    assert body["symbols"]["SPY"]["scanner"]["underlying_price"] is None
    assert body["symbols"]["SPY"]["scanner"]["score"] is None
    assert "scanner_stale_or_unavailable" in body["system"]["stale_or_missing"]
    stale = TestClient(create_app(service=ProjectionService(stale=True))).get("/api/live/snapshot").json()
    assert stale["market"]["freshness"] == "stale"


def test_snapshot_identity_is_deterministic_for_unchanged_persisted_state():
    current = {"now": NOW}
    service = ProjectionService()
    service._now = lambda: current["now"]
    first = service.live_snapshot()
    current["now"] = datetime(2026, 9, 13, 14, 45, tzinfo=timezone.utc)
    second = service.live_snapshot()
    assert first["snapshot_id"] == second["snapshot_id"]
    assert len(first["snapshot_id"]) == 20
    assert first["generated_at"] != second["generated_at"]
    assert first["snapshot_id"] != str(first["generated_at"])


def test_snapshot_cursor_skips_system_status_and_matches_snapshot_identity():
    service = ProjectionService()
    cursor = service.live_snapshot_cursor()
    snapshot = service.live_snapshot()
    assert cursor["snapshot_id"] == snapshot["snapshot_id"]
    assert cursor["cycle_id"] == snapshot["scanner"]["cycle_id"]
    assert cursor["occurred_at"] == snapshot["generated_at"]
    assert service.calls.count("system_status") == 1
    assert service.calls.count("scanner") >= 2


def test_snapshot_identity_changes_when_persisted_cycle_changes():
    service = ProjectionService()
    original_scanner = service.scanner
    first = service.live_snapshot()["snapshot_id"]

    def scanner():
        payload = original_scanner()
        payload["provenance_health"] = {**payload["provenance_health"], "scan_cycle_id": "cycle-2"}
        return payload

    service.scanner = scanner
    assert service.live_snapshot()["snapshot_id"] != first


def test_normalizer_supports_decimal_enum_and_library_scalar_protocols():
    import numpy as np
    import pandas as pd

    class State(Enum): OK = "ok"
    class Scalar:
        def item(self): return float("-inf")
    result = normalize_json_value({"decimal": Decimal("1.25"), "enum": State.OK,
        "scalar": Scalar(), "date": NOW, "timestamp": pd.Timestamp(NOW),
        "missing_timestamp": pd.NaT, "numpy_float": np.float64(float("nan")),
        "numpy_integer": np.int64(7)})
    assert result == {"decimal": 1.25, "enum": "ok", "scalar": None,
        "date": NOW.isoformat(), "timestamp": NOW.isoformat(),
        "missing_timestamp": None, "numpy_float": None, "numpy_integer": 7}
