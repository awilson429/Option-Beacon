from datetime import datetime, timedelta, timezone

from mirror_execution import MirrorExecutionRepository
from optionbeacon.worker.scan_once import run_scan_once
from paper_execution_repository import PaperExecutionRepository
from trade_repository import TradeRepository
from trade_state_service import list_trade_outcomes, process_scanner_result


NOW = datetime(2026, 8, 6, 14, 30, tzinfo=timezone.utc)


def result(symbol, direction, price, *, confidence=80, trigger=100, at=NOW):
    return {
        "symbol": symbol,
        "signal": "WATCHLIST",
        "bias": direction,
        "confidence": confidence,
        "score": confidence,
        "price": price,
        "timestamp": at.isoformat(),
        "setup_stage": "Developing",
        "entry_timing": "Too early",
        "trade_plan": {
            "direction": direction,
            "setup_type": "Breakout" if direction == "Bullish" else "Breakdown",
            "trigger_price": trigger,
            "technical_stop": 98 if direction == "Bullish" else 102,
            "target_1": 104 if direction == "Bullish" else 96,
        },
    }


def entered_events(repository):
    return [
        event for event in repository.list_trade_events(limit=5000)
        if event["event_type"] == "TRADE_ENTERED"
    ]


def test_two_cycle_worker_entry_precedes_broad_and_mirror_consumers(
    tmp_path, monkeypatch,
):
    repository = TradeRepository(tmp_path / "worker.db", database_url="")
    paper_handoffs = []
    mirror_handoffs = []
    current = {"result": result("SPY", "Bullish", 99)}

    monkeypatch.setenv("OPTIONBEACON_MIRROR_ENABLED", "true")
    monkeypatch.setattr(
        "optionbeacon.worker.scan_once.run_mirror_execution",
        lambda _repository, _mirror, candidates, **kwargs:
            mirror_handoffs.append(list(candidates)),
    )

    def paper_executor(candidates, **kwargs):
        paper_handoffs.append(list(candidates))
        return {"opened": [], "decisions": []}

    common = {
        "repository": repository,
        "scanner_id": "production",
        "symbol_groups_loader": lambda: ({"Core": ["SPY"]}, "test", ""),
        "signal_generator": lambda _symbol: dict(current["result"]),
        "snapshot_writer": lambda _results: None,
        "paper_executor": paper_executor,
    }
    assert run_scan_once(**common, run_number=1, clock=lambda: NOW) == 0
    assert entered_events(repository) == []

    # A changed current plan must not replace the first cycle's persisted trigger.
    current["result"] = result(
        "SPY", "Bullish", 100.1, trigger=999, at=NOW + timedelta(minutes=5)
    )
    cycle_two = NOW + timedelta(minutes=5)
    assert run_scan_once(**common, run_number=2, clock=lambda: cycle_two) == 0

    entries = entered_events(repository)
    assert len(entries) == 1
    authoritative_id = entries[0]["opportunity_id"]
    assert entries[0]["underlying_price"] == 100.1
    assert [row["_authoritative_entry_id"] for row in paper_handoffs[-1]] == [
        authoritative_id
    ]
    assert [row["_authoritative_entry_id"] for row in mirror_handoffs[-1]] == [
        authoritative_id
    ]
    assert PaperExecutionRepository(repository).counts() == {
        "positions": 0, "trades": 0, "journal": 0,
    }
    assert MirrorExecutionRepository(repository).rows() == []


def test_multi_symbol_lifecycle_uses_direction_confidence_age_and_persisted_trigger(
    tmp_path,
):
    repository = TradeRepository(tmp_path / "multi.db", database_url="")
    first_cycle = {
        "BULL": result("BULL", "Bullish", 99),
        "BEAR": result("BEAR", "Bearish", 101),
        "LOW": result("LOW", "Bullish", 99, confidence=64),
        "WAIT": result("WAIT", "Bullish", 99),
        "OLD": result("OLD", "Bullish", 99, at=NOW - timedelta(minutes=61)),
    }
    for scanner_result in first_cycle.values():
        process_scanner_result(repository, scanner_result, current_timestamp=NOW)

    originals = {
        record.symbol: record for record in list_trade_outcomes(repository)
    }
    assert len(originals) == 5

    second_cycle = NOW + timedelta(minutes=1)
    updates = {
        "BULL": result("BULL", "Bullish", 100.1, trigger=999, at=second_cycle),
        "BEAR": result("BEAR", "Bearish", 99.9, trigger=1, at=second_cycle),
        "LOW": result("LOW", "Bullish", 100.1, confidence=64, at=second_cycle),
        "WAIT": result("WAIT", "Bullish", 99.9, at=second_cycle),
        "OLD": result("OLD", "Bullish", 100.1, at=second_cycle),
    }
    for scanner_result in updates.values():
        process_scanner_result(
            repository, scanner_result, current_timestamp=second_cycle
        )

    events = entered_events(repository)
    assert {event["symbol"] for event in events} == {"BULL", "BEAR"}
    persisted = {
        record.trade_id: record for record in list_trade_outcomes(repository)
    }
    assert persisted[originals["BULL"].trade_id].entry_time == second_cycle
    assert persisted[originals["BEAR"].trade_id].entry_time == second_cycle
    assert persisted[originals["LOW"].trade_id].entry_time is None
    assert persisted[originals["WAIT"].trade_id].entry_time is None
    assert persisted[originals["OLD"].trade_id].exit_reason == "NEVER_TRIGGERED"


def test_candidate_identity_reuses_same_bucket_and_old_candidate_survives_new_bucket(
    tmp_path,
):
    repository = TradeRepository(tmp_path / "identity.db", database_url="")
    process_scanner_result(repository, result("SPY", "Bullish", 99), current_timestamp=NOW)
    process_scanner_result(
        repository,
        result("SPY", "Bullish", 99.5, at=NOW + timedelta(minutes=4)),
        current_timestamp=NOW + timedelta(minutes=4),
    )
    assert len(list_trade_outcomes(repository)) == 1

    process_scanner_result(
        repository,
        result("SPY", "Bullish", 100.1, at=NOW + timedelta(minutes=5)),
        current_timestamp=NOW + timedelta(minutes=5),
    )
    records = list_trade_outcomes(repository)
    assert len(records) == 2
    assert sum(record.entry_time is not None for record in records) == 1
    assert len(entered_events(repository)) == 1
