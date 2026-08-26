from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.services import OptionBeaconReadService
from capital_readiness import lane_configs
from capital_repository import CapitalRepository
from decision_provenance import build_observation, scan_cycle_identity
from trade_repository import TradeRepository
from trade_state_service import process_scanner_result


NOW = datetime(2026, 8, 25, 15, 0, tzinfo=timezone.utc)


def repository(tmp_path):
    repo = TradeRepository(tmp_path / "provenance.db")
    CapitalRepository(repo, configs=lane_configs())
    return repo


def qualified_result(symbol="SPY", **changes):
    payload = {
        "symbol": symbol, "signal": "BULLISH SETUP", "bias": "Bullish",
        "price": 642.5, "confidence": 94, "bullish_score": 94,
        "bearish_score": 28, "trend_score": 25, "momentum_score": 20,
        "volume_score": 12, "volatility_score": 15, "price_action_score": 22,
        "relative_volume": 1.6, "atr": 1.2, "rsi": 61, "vwap": 641.8,
        "ema20": 641.0, "ema50": 639.0, "ema200": 625.0,
        "macd": 1.1, "macd_signal": .8, "macd_hist": .3,
        "volume": 2000000, "avg_volume": 1200000,
        "setup_stage": "Forming", "entry_timing": "Watch closely",
        "last_candle_at": NOW.isoformat(), "timestamp": NOW.isoformat(),
        "reasons": ["Price above 20 EMA", "Volume expansion"],
        "trade_plan": {"direction": "Bullish", "setup_type": "Bullish breakout",
                       "trigger_price": 643.0, "technical_stop": 640.0,
                       "target_1": 645.0, "target_2": 647.0, "target_3": 649.0},
    }
    payload.update(changes)
    return payload


def start_cycle(repo, *, run_number=7, started_at=NOW):
    cycle_id = scan_cycle_identity(
        scanner_id="worker", run_number=run_number, started_at=started_at
    )
    repo.start_provenance_cycle(
        scan_cycle_id=cycle_id, scanner_id="worker", run_number=run_number,
        started_at=started_at, session_state="WORKER_ACTIVE",
        worker_source="test", source_version="test-version",
    )
    return cycle_id


def persist_observation(repo, cycle_id, result, *, at=NOW, failure=None):
    observation = build_observation(
        scan_cycle_id=cycle_id, symbol=result.get("symbol", "SPY") if result else "SPY",
        observed_at=at, result=result, failure=failure, source_version="test-version",
    )
    return repo.record_provenance_observation(observation)


def decision(lane, opportunity_id, *, state="TAKE", reason="ALL_RISK_CONTROLS_PASSED"):
    return {
        "lane": lane, "opportunity_id": opportunity_id, "symbol": "SPY",
        "direction": "Bullish", "state": state, "reason_code": reason,
        "explanation": reason.replace("_", " ").title(),
        "proposed_contract": "SPY260828C00643000", "proposed_quantity": 1,
        "proposed_capital_required": 150.0, "proposed_dollar_risk": 50.0,
        "proposed_account_risk_pct": .2, "theoretical_entry": 1.45,
        "realistic_entry": 1.5, "stop_fill": 1.0, "risk_per_contract": 50.0,
        "drawdown_state": "NORMAL", "timestamp": NOW + timedelta(seconds=1),
    }


def paper_position(*, closed=False):
    return SimpleNamespace(
        trade_id="paper-1", status="CLOSED" if closed else "OPEN",
        exit_time=NOW + timedelta(minutes=30) if closed else None,
        exit_bid=2.0 if closed else None, exit_ask=2.1 if closed else None,
        exit_mid=2.05 if closed else None, current_bid=1.7, current_ask=1.8,
        current_mid=1.75, ticker="SPY", direction="Bullish",
        option_symbol="SPY260828C00643000", strike=643.0, expiration="2026-08-28",
        entry_time=NOW + timedelta(seconds=2), last_update=NOW + timedelta(minutes=30),
        exit_reason="TARGET" if closed else None, last_underlying_price=646.0,
        last_option_quote_time=NOW + timedelta(minutes=30), current_return_percent=36.6,
    )


def test_identity_is_unique_by_cycle_symbol_and_observation(tmp_path):
    repo = repository(tmp_path)
    first_cycle = start_cycle(repo, run_number=1)
    second_cycle = start_cycle(repo, run_number=2, started_at=NOW + timedelta(minutes=5))
    spy_one = persist_observation(repo, first_cycle, qualified_result("SPY"))
    qqq_one = persist_observation(repo, first_cycle, qualified_result("QQQ"))
    spy_two = persist_observation(
        repo, second_cycle, qualified_result("SPY", last_candle_at=(NOW + timedelta(minutes=5)).isoformat()),
        at=NOW + timedelta(minutes=5),
    )
    assert len({first_cycle, second_cycle}) == 2
    assert len({spy_one["observation_id"], qqq_one["observation_id"], spy_two["observation_id"]}) == 3
    assert repo.latest_provenance_observations()["SPY"]["scan_cycle_id"] == second_cycle


def test_provenance_idempotency_rejects_conflicting_immutable_identity(tmp_path):
    repo = repository(tmp_path)
    cycle = start_cycle(repo)
    with pytest.raises(ValueError, match="scan-cycle identity collides"):
        repo.start_provenance_cycle(
            scan_cycle_id=cycle, scanner_id="different-worker", run_number=7,
            started_at=NOW, session_state="WORKER_ACTIVE", worker_source="test",
        )
    stored = persist_observation(repo, cycle, qualified_result("SPY"))
    conflicting = build_observation(
        scan_cycle_id=cycle, symbol="QQQ", observed_at=NOW,
        result=qualified_result("QQQ"), source_version="test-version",
    )
    conflicting["observation_id"] = stored["observation_id"]
    with pytest.raises(ValueError, match="observation identity collides"):
        repo.record_provenance_observation(conflicting)
    repo.record_provenance_decision_link(
        decision_id="decision-1", observation_id=stored["observation_id"],
        opportunity_id="opportunity-1", lane="OB", decision_state="PASS",
        decided_at=NOW, link_status="NO_TRADE", source="test",
    )
    with pytest.raises(ValueError, match="decision identity collides"):
        repo.record_provenance_decision_link(
            decision_id="decision-1", observation_id=stored["observation_id"],
            opportunity_id="opportunity-2", lane="OB", decision_state="PASS",
            decided_at=NOW, link_status="NO_TRADE", source="test",
        )


def test_observation_preserves_inputs_nulls_freshness_and_dispositions(tmp_path):
    repo = repository(tmp_path)
    cycle = start_cycle(repo)
    qualified = persist_observation(repo, cycle, qualified_result())
    assert qualified["qualification_state"] == "QUALIFIED"
    assert qualified["component_scores"]["trend_score"] == 25
    assert qualified["indicators"]["rsi"] == 61
    assert qualified["opportunity_id"] is None
    stale_result = qualified_result("QQQ", last_candle_at=(NOW - timedelta(minutes=20)).isoformat())
    stale = persist_observation(repo, cycle, stale_result, at=NOW + timedelta(seconds=1))
    assert stale["qualification_state"] == "QUALIFIED"
    assert stale["data_quality"] == "stale"
    assert stale["stale"] is True

    rejected_cycle = start_cycle(repo, run_number=9, started_at=NOW + timedelta(minutes=10))
    rejected = persist_observation(
        repo, rejected_cycle,
        qualified_result("QQQ", setup_stage="Extended",
                         last_candle_at=(NOW + timedelta(minutes=10)).isoformat()),
        at=NOW + timedelta(minutes=10),
    )
    assert rejected["qualification_state"] == "REJECTED"
    assert rejected["reason_code"] == "SETUP_STAGE_EXTENDED"


def test_no_result_and_session_block_are_explicit_with_nullable_values(tmp_path):
    repo = repository(tmp_path)
    no_result_cycle = start_cycle(repo, run_number=10)
    no_result = persist_observation(repo, no_result_cycle, None)
    assert no_result["qualification_state"] == "DATA_UNSAFE"
    assert no_result["reason_code"] == "NO_RESULT"
    assert no_result["underlying_price"] is None
    assert no_result["confidence"] is None
    blocked_cycle = start_cycle(repo, run_number=11, started_at=NOW + timedelta(minutes=5))
    blocked = persist_observation(
        repo, blocked_cycle,
        {"symbol": "SPY", "signal": "MARKET CLOSED / WAIT", "price": 642.0,
         "timestamp": (NOW + timedelta(minutes=5)).isoformat()},
        at=NOW + timedelta(minutes=5),
    )
    assert blocked["qualification_state"] == "SESSION_BLOCKED"
    assert blocked["reason_code"] == "MARKET_CLOSED_WAIT"


def test_rejected_no_trade_is_durable_without_opportunity(tmp_path):
    repo = repository(tmp_path)
    cycle = start_cycle(repo)
    result = qualified_result(signal="WATCHLIST", bias="Neutral", confidence=55,
                              bullish_score=55, bearish_score=40, trade_plan={})
    observation = persist_observation(repo, cycle, result)
    changed = process_scanner_result(
        repo, result, current_timestamp=NOW,
        provenance_observation_id=observation["observation_id"],
        provenance_scan_cycle_id=cycle,
    )
    stored = repo.get_provenance_observation(observation["observation_id"])
    assert changed == 0
    assert stored["qualification_state"] == "NO_SETUP"
    assert stored["reason_code"] == "NO_TRADE_PLAN"
    assert stored["opportunity_id"] is None
    assert repo.list_opportunities() == []
    assert repo.provenance_decision_links() == []


def test_complete_exact_chain_reconstructs_observation_to_closed_outcome(tmp_path):
    repo = repository(tmp_path)
    cycle = start_cycle(repo)
    result = qualified_result()
    observation = persist_observation(repo, cycle, result)
    process_scanner_result(
        repo, result, source_version="test-version", current_timestamp=NOW,
        provenance_observation_id=observation["observation_id"],
        provenance_scan_cycle_id=cycle,
    )
    stored_observation = repo.get_provenance_observation(observation["observation_id"])
    opportunity_id = stored_observation["opportunity_id"]
    assert opportunity_id

    capital = CapitalRepository(repo, configs=lane_configs(), initialize=False)
    ob_id = capital.record_decision(decision("OB", opportunity_id))
    broad_id = capital.record_decision(decision("BROAD", opportunity_id))
    rows = {row["lane"]: row for row in capital.recent_decisions(limit=10)}
    open_position = paper_position()
    capital._upsert_from_paper(open_position, opportunity_id, rows["OB"], now=NOW)
    capital._upsert_from_paper(open_position, opportunity_id, rows["BROAD"], now=NOW)
    closed_position = paper_position(closed=True)
    capital._upsert_from_paper(closed_position, opportunity_id, rows["OB"], now=NOW + timedelta(minutes=30))
    capital._upsert_from_paper(closed_position, opportunity_id, rows["BROAD"], now=NOW + timedelta(minutes=30))

    service = OptionBeaconReadService(repository=repo, now=lambda: NOW + timedelta(minutes=31))
    chain = service.trade_provenance("OB:paper-1", lane="OB")
    assert chain["observation"]["observation_id"] == observation["observation_id"]
    assert chain["opportunity"]["id"] == opportunity_id
    assert chain["capital_decision"]["decision_id"] == ob_id
    assert chain["decision_trade_link"]["trade_id"] == "OB:paper-1"
    assert chain["trade"]["position_id"] == "OB:paper-1"
    assert chain["management"][-1]["trade_id"] == "OB:paper-1"
    assert chain["outcome"]["status"] == "CLOSED"
    assert repo.provenance_decision_link(broad_id)["trade_id"] == "BROAD:paper-1"


def test_provenance_failures_do_not_change_candidate_or_capital_decision(tmp_path, monkeypatch):
    repo = repository(tmp_path)
    cycle = start_cycle(repo)
    result = qualified_result()
    observation = persist_observation(repo, cycle, result)
    monkeypatch.setattr(repo, "link_provenance_opportunity",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    changed = process_scanner_result(
        repo, result, current_timestamp=NOW,
        provenance_observation_id=observation["observation_id"],
        provenance_scan_cycle_id=cycle,
    )
    assert changed == 1
    assert len(repo.list_opportunities()) == 1
    assert repo.get_provenance_cycle(cycle)["provenance_status"] == "DEGRADED"

    monkeypatch.setattr(repo, "record_provenance_decision_link",
                        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    capital = CapitalRepository(repo, configs=lane_configs(), initialize=False)
    decision_id = capital.record_decision(decision("OB", repo.list_opportunities()[0]["id"]))
    assert any(row["decision_id"] == decision_id for row in capital.recent_decisions())


def test_trade_link_failure_does_not_block_position_or_management(tmp_path, monkeypatch):
    repo = repository(tmp_path)
    cycle = start_cycle(repo)
    result = qualified_result()
    observation = persist_observation(repo, cycle, result)
    process_scanner_result(
        repo, result, current_timestamp=NOW,
        provenance_observation_id=observation["observation_id"],
        provenance_scan_cycle_id=cycle,
    )
    opportunity_id = repo.get_provenance_observation(observation["observation_id"])["opportunity_id"]
    capital = CapitalRepository(repo, configs=lane_configs(), initialize=False)
    capital.record_decision(decision("OB", opportunity_id))
    row = next(item for item in capital.recent_decisions() if item["lane"] == "OB")
    monkeypatch.setattr(repo, "link_provenance_decision_trade",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    capital._upsert_from_paper(paper_position(), opportunity_id, row, now=NOW)
    with repo.connection() as connection:
        position = repo._fetchone(
            connection, "SELECT * FROM capital_positions WHERE position_id=?",
            ("OB:paper-1",),
        )
    assert position["status"] == "OPEN"
    assert repo.latest_trade_management_snapshot("OB:paper-1", lane="OB") is not None


def test_mirror_isolation_and_no_symbol_only_lookup(tmp_path):
    repo = repository(tmp_path)
    with pytest.raises(ValueError, match="OB or BROAD"):
        repo.record_provenance_decision_link(
            decision_id="mirror", observation_id=None, opportunity_id="opportunity",
            lane="CONTROL_RESEARCH", decision_state="TAKE", decided_at=NOW,
            link_status="DECIDED", source="test",
        )
    cycle = start_cycle(repo)
    first = persist_observation(repo, cycle, qualified_result("SPY"))
    second_cycle = start_cycle(repo, run_number=8, started_at=NOW + timedelta(minutes=5))
    second = persist_observation(
        repo, second_cycle, qualified_result("SPY", last_candle_at=(NOW + timedelta(minutes=5)).isoformat()),
        at=NOW + timedelta(minutes=5),
    )
    repo.link_provenance_opportunity(first["observation_id"], "opp-1")
    repo.link_provenance_opportunity(second["observation_id"], "opp-2")
    assert repo.provenance_observation_for_opportunity("opp-1")["observation_id"] == first["observation_id"]
    assert repo.provenance_observation_for_opportunity("opp-2")["observation_id"] == second["observation_id"]


def test_provenance_api_recent_opportunity_trade_and_legacy_states(tmp_path):
    repo = repository(tmp_path)
    cycle = start_cycle(repo)
    observation = persist_observation(repo, cycle, qualified_result())
    process_scanner_result(
        repo, qualified_result(), current_timestamp=NOW,
        provenance_observation_id=observation["observation_id"],
        provenance_scan_cycle_id=cycle,
    )
    opportunity_id = repo.get_provenance_observation(observation["observation_id"])["opportunity_id"]
    client = TestClient(create_app(service=OptionBeaconReadService(repository=repo, now=lambda: NOW)))
    recent = client.get("/api/provenance/recent?symbol=SPY").json()
    assert recent["observations"][0]["observation_id"] == observation["observation_id"]
    scanner = client.get("/api/scanner")
    assert scanner.status_code == 200
    scanner_payload = scanner.json()
    spy = next(row for row in scanner_payload["instruments"] if row["symbol"] == "SPY")
    assert spy["canonical_observation"]["observation_id"] == observation["observation_id"]
    assert scanner_payload["provenance_health"]["provenance_status"] == "HEALTHY"
    opportunity = client.get(f"/api/provenance/opportunities/{opportunity_id}").json()
    assert opportunity["data_status"] == "persisted"
    assert opportunity["observation"]["opportunity_id"] == opportunity_id
    missing = client.get("/api/provenance/trades/legacy-position?lane=OB").json()
    assert missing["data_status"] == "unavailable"
    assert missing["observation"] is None
    assert client.get("/api/provenance/trades/legacy-position").status_code == 422
    assert client.get("/api/provenance/trades/legacy-position?lane=CONTROL_RESEARCH").status_code == 422

    repo.create_opportunity(
        opportunity_id="legacy", idempotency_key="legacy", symbol="SPY",
        direction="Bullish", playbook="legacy", signal_timestamp=NOW,
        source_version="legacy",
    )
    legacy = client.get("/api/provenance/opportunities/legacy").json()
    assert legacy["data_status"] == "legacy_unavailable"
    assert legacy["observation"] is None
