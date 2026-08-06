import json
import logging
from datetime import datetime, timedelta, timezone

import optionbeacon.worker.scan_once as scan_module
from authoritative_entry_funnel import (
    AuthoritativeEntryFunnelRepository,
    classify_symbol,
)
from mirror_execution import MirrorExecutionRepository, run_mirror_execution
from paper_execution import run_paper_execution
from paper_execution_repository import PaperExecutionRepository
from signal_history import TradeOutcome
from trade_repository import TradeRepository
from trade_state_service import process_scanner_result, sync_trade_outcome


NOW = datetime(2026, 8, 6, 15, 0, tzinfo=timezone.utc)


def result(confidence=80, *, price=100.1, signal="WATCHLIST"):
    return {
        "symbol": "SPY", "signal": signal, "bias": "Bullish",
        "confidence": confidence, "score": confidence, "price": price,
        "timestamp": NOW.isoformat(), "setup_stage": "Triggered",
        "entry_timing": "Trigger confirmed",
        "trade_plan": {
            "direction": "Bullish", "setup_type": "Breakout",
            "trigger_price": 100, "technical_stop": 99, "target_1": 101,
        },
    }


def candidate(identity="auth", confidence=80):
    return TradeOutcome(
        trade_id=identity, timestamp=NOW - timedelta(minutes=5), symbol="SPY",
        direction="Bullish", setup="Breakout", confidence=confidence, entry=100,
        stop=99, target_1=101, target_2=None, target_3=None, entry_time=None,
        exit_time=None, exit_reason=None, max_favorable_excursion=None,
        max_adverse_excursion=None, realized_return=None, hold_minutes=None,
    )


def structured(caplog, event):
    return [
        json.loads(record.getMessage()) for record in caplog.records
        if record.getMessage().startswith("{")
        and json.loads(record.getMessage()).get("event") == event
    ]


def test_confidence_boundary_uses_authoritative_rule_not_visible_setup_label():
    below = classify_symbol("SPY", result(64))
    boundary = classify_symbol("SPY", result(65))
    above = classify_symbol("SPY", result(80))
    assert not below["confidence_qualified"]
    assert below["primary_blocker"] == "ENTRY_CONFIDENCE_BELOW_MINIMUM"
    assert boundary["confidence_qualified"]
    assert above["confidence_qualified"]
    assert above["visible_setup_qualified"] is False
    visible = classify_symbol("SPY", result(95, signal="BULLISH SETUP"))
    assert visible["confidence_qualified"] and visible["visible_setup_qualified"]


def test_one_entry_cycle_reconciles_not_entered_and_persisted_candidate_fields(tmp_path):
    repository = TradeRepository(tmp_path / "state.db", database_url="")
    record = candidate(confidence=65)
    sync_trade_outcome(repository, record)
    process_scanner_result(repository, result(70), current_timestamp=NOW)
    event = next(e for e in repository.list_trade_events() if e["event_type"] == "TRADE_ENTERED")
    diagnostics = AuthoritativeEntryFunnelRepository(repository)
    saved = diagnostics.save_cycle(
        scanner_id="production", run_number=4,
        started_at=NOW - timedelta(minutes=1), completed_at=NOW,
        symbols=[("SPY", result(70)), ("QQQ", {**result(64), "symbol": "QQQ"})],
        entered_events=[event], candidate_records=[
            r for r in [record] if r.trade_id == event["opportunity_id"]
        ],
    )
    assert saved["confidence_qualified"] == 1
    assert saved["visible_setup_qualified"] == 0
    assert saved["trade_entered"] == 1
    assert saved["not_entered"] == 1
    assert sum(saved["blockers"].values()) == 1
    row = diagnostics.symbol_rows(saved["cycle_id"])[0]
    assert row["opportunity_id"] == event["opportunity_id"]
    assert row["authoritative_disposition"] == "TRADE_ENTERED_THIS_CYCLE"


def test_zero_entry_cycle_is_internally_consistent(tmp_path):
    repository = TradeRepository(tmp_path / "state.db", database_url="")
    diagnostics = AuthoritativeEntryFunnelRepository(repository)
    saved = diagnostics.save_cycle(
        scanner_id="production", run_number=3,
        started_at=NOW - timedelta(minutes=1), completed_at=NOW,
        symbols=[("SPY", result(64)), ("QQQ", {**result(80, price=99), "symbol": "QQQ"})],
        entered_events=[], candidate_records=[],
    )
    assert saved["trade_entered"] == 0
    assert saved["not_entered"] == 2
    assert sum(saved["blockers"].values()) == 2


def test_authoritative_log_contains_searchable_opportunity_identity(tmp_path, caplog):
    repository = TradeRepository(tmp_path / "state.db", database_url="")
    sync_trade_outcome(repository, candidate("trace-id"))
    with caplog.at_level(logging.INFO):
        process_scanner_result(
            repository, result(), current_timestamp=NOW,
            scanner_id="production", run_number=4,
        )
    row = structured(caplog, "authoritative_trade_entered")[0]
    assert row == {
        "event": "authoritative_trade_entered", "scanner_id": "production",
        "run_number": 4, "opportunity_id": "trace-id", "symbol": "SPY",
        "direction": "Bullish", "confidence": 80, "trigger": 100,
        "entry_price": 100.1,
    }


def test_broad_candidate_failure_does_not_prevent_mirror_or_mutate_ledgers(
    tmp_path, monkeypatch, caplog,
):
    repository = TradeRepository(tmp_path / "state.db", database_url="")
    paper = PaperExecutionRepository(repository)
    mirror = MirrorExecutionRepository(repository)
    sync_trade_outcome(repository, candidate("same-id"))
    process_scanner_result(repository, result(), current_timestamp=NOW)
    projected = [{
        **result(), "_authoritative_entry_id": "same-id",
        "_authoritative_event_id": "event-id",
    }]
    monkeypatch.setattr("paper_execution.capture_qualified_signal", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("failure")))
    with caplog.at_level(logging.INFO):
        run_paper_execution(
            projected, config=object(), now=NOW, refreshed_positions=[],
            trade_ledger=paper, position_store=paper, journal=paper,
            scanner_id="production", run_number=4,
        )
        class NoContracts:
            def expirations(self, _ticker):
                return [], None

        mirror_result = run_mirror_execution(
            repository, mirror, projected, enabled=True, scanner_id="production",
            run_number=4, now=NOW, chain_provider=NoContracts(),
        )
    assert structured(caplog, "broad_authoritative_handoff")[0]["opportunity_id"] == "same-id"
    assert structured(caplog, "mirror_authoritative_handoff")[-1]["opportunity_id"] == "same-id"
    assert mirror_result["unexecutable"] == 1
    assert mirror.get("same-id")["disposition_code"] == "MIRROR_NO_VALID_CONTRACT"
    assert paper.counts() == {"positions": 0, "trades": 0, "journal": 0}
    assert repository.get_opportunity(opportunity_id="same-id")["state"] == "OPEN"


def test_mirror_unexecutable_is_independent_of_authoritative_and_broad_state(tmp_path):
    repository = TradeRepository(tmp_path / "state.db", database_url="")
    paper = PaperExecutionRepository(repository)
    mirror = MirrorExecutionRepository(repository)
    sync_trade_outcome(repository, candidate("same-id"))
    process_scanner_result(repository, result(), current_timestamp=NOW)
    event = next(e for e in repository.list_trade_events() if e["event_type"] == "TRADE_ENTERED")
    projected = [{**result(), "_authoritative_entry_id": "same-id", "_authoritative_event_id": event["id"]}]

    class NoContracts:
        def expirations(self, _ticker):
            return [], None

    outcome = run_mirror_execution(
        repository, mirror, projected, enabled=True, scanner_id="production",
        run_number=4, now=NOW, chain_provider=NoContracts(),
    )
    assert outcome["unexecutable"] == 1
    assert repository.get_opportunity(opportunity_id="same-id")["state"] == "OPEN"
    assert paper.counts() == {"positions": 0, "trades": 0, "journal": 0}
