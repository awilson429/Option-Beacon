from dataclasses import replace
from datetime import datetime, timedelta, timezone

from execution_config import ExecutionConfig
from paper_execution import pending_authoritative_entries, run_paper_execution
from paper_execution_repository import PaperExecutionRepository
from paper_trading_page import execution_status_model
from signal_history import TradeOutcome
from trade_repository import TradeRepository
from trade_state_service import process_scanner_result, sync_trade_outcome


NOW = datetime(2026, 8, 4, 14, 35, tzinfo=timezone.utc)


def authoritative_record(trade_id="entry-1", entry=100.0):
    return TradeOutcome(
        trade_id=trade_id,
        timestamp=NOW - timedelta(minutes=10),
        symbol="ABNB",
        direction="Bearish",
        setup="Breakdown",
        confidence=80,
        entry=entry,
        stop=102,
        target_1=98,
        target_2=96,
        target_3=None,
        entry_time=None,
        exit_time=None,
        exit_reason=None,
        max_favorable_excursion=None,
        max_adverse_excursion=None,
        realized_return=None,
        hold_minutes=None,
    )


def scan_result(score=95):
    return {
        "symbol": "ABNB",
        "price": 99.9,
        "score": score,
        "confidence": 10,
        "signal": "WAIT",
        "entry_timing": "WAIT",
        "timestamp": NOW.isoformat(),
    }


class Contracts:
    def expirations(self, ticker):
        return ["2026-08-14"], None

    def chain(self, ticker, expiration):
        return [{
            "option_type": "put",
            "expiration_date": expiration,
            "strike": 100,
            "symbol": "ABNB260814P00100000",
            "bid": 0.95,
            "ask": 1.05,
            "last": 1.0,
            "delta": -0.5,
            "open_interest": 500,
            "volume": 100,
            "implied_volatility": 0.3,
        }], None


def enabled_config(**changes):
    return replace(
        ExecutionConfig(),
        trading_enabled=True,
        max_open_positions=10,
        max_trades_per_day=10,
        min_open_interest=0,
        **changes,
    )


def entered_repository(tmp_path, records=None, score=95):
    repository = TradeRepository(tmp_path / "state.db", database_url="")
    for record in records or [authoritative_record()]:
        sync_trade_outcome(repository, record)
    process_scanner_result(repository, scan_result(score=score), current_timestamp=NOW)
    return repository


def test_authoritative_enter_reaches_paper_and_opens_once(tmp_path):
    repository = entered_repository(tmp_path)
    paper = PaperExecutionRepository(repository)
    candidates = pending_authoritative_entries(repository, {"ABNB": scan_result()}, paper)

    assert [row["_authoritative_entry_id"] for row in candidates] == ["entry-1"]
    assert candidates[0]["confidence"] == 80
    assert candidates[0]["entry_timing"] == "WAIT"  # no second qualification pass

    result = run_paper_execution(
        candidates,
        config=enabled_config(min_beacon_score=90),
        now=NOW,
        chain_provider=Contracts(),
        trade_ledger=paper,
        position_store=paper,
        journal=paper,
        refreshed_positions=[],
    )
    assert len(result["opened"]) == 1
    assert len(paper.load()) == 1
    assert paper.journal_rows()[0]["accepted"] == 1
    assert pending_authoritative_entries(repository, {"ABNB": scan_result()}, paper) == []

    with repository.connection() as connection:
        persisted = repository._fetchone(
            connection,
            "SELECT source_signal_id,opportunity_id FROM paper_execution_trades",
        )
    assert persisted == {"source_signal_id": "entry-1", "opportunity_id": "entry-1"}


def test_ineligible_authoritative_enter_has_explicit_rejection(tmp_path):
    repository = entered_repository(tmp_path, score=44)
    paper = PaperExecutionRepository(repository)
    candidates = pending_authoritative_entries(repository, {"ABNB": scan_result(score=44)}, paper)

    result = run_paper_execution(
        candidates,
        config=enabled_config(min_beacon_score=92),
        now=NOW,
        chain_provider=Contracts(),
        trade_ledger=paper,
        position_store=paper,
        journal=paper,
        refreshed_positions=[],
    )
    assert not result["opened"]
    assert result["decisions"][0].reason == "SCORE_TOO_LOW"
    assert paper.journal_rows()[0]["reason_code"] == "SCORE_TOO_LOW"
    assert pending_authoritative_entries(repository, {"ABNB": scan_result(score=44)}, paper) == []


def test_historical_undispositioned_entry_is_rejected_not_opened(tmp_path):
    repository = entered_repository(tmp_path)
    paper = PaperExecutionRepository(repository)
    candidates = pending_authoritative_entries(repository, {"ABNB": scan_result()}, paper)
    result = run_paper_execution(
        candidates,
        config=enabled_config(min_beacon_score=90),
        now=NOW + timedelta(hours=2),
        chain_provider=Contracts(),
        trade_ledger=paper,
        position_store=paper,
        journal=paper,
        refreshed_positions=[],
    )
    assert not result["opened"]
    assert result["decisions"][0].reason == "STALE_AUTHORITATIVE_ENTRY"
    assert paper.journal_rows()[0]["reason_code"] == "STALE_AUTHORITATIVE_ENTRY"


def test_rapid_entries_are_not_lost_and_restart_preserves_dispositions(tmp_path):
    records = [authoritative_record("rapid-1"), authoritative_record("rapid-2", 99.95)]
    repository = entered_repository(tmp_path, records=records)
    paper = PaperExecutionRepository(repository)
    candidates = pending_authoritative_entries(repository, {"ABNB": scan_result()}, paper)
    assert {row["_authoritative_entry_id"] for row in candidates} == {"rapid-1", "rapid-2"}

    result = run_paper_execution(
        candidates,
        config=enabled_config(min_beacon_score=90),
        now=NOW,
        chain_provider=Contracts(),
        trade_ledger=paper,
        position_store=paper,
        journal=paper,
        refreshed_positions=[],
    )
    assert len(result["opened"]) == 2

    restarted_repository = TradeRepository(tmp_path / "state.db", database_url="")
    restarted_paper = PaperExecutionRepository(restarted_repository)
    assert len(restarted_paper.load()) == 2
    assert pending_authoritative_entries(
        restarted_repository, {"ABNB": scan_result()}, restarted_paper
    ) == []


def test_worker_heartbeat_satisfies_read_only_status_without_decisions():
    health = {"last_success_at": NOW.isoformat()}
    status = execution_status_model([], [], health)
    assert status["trading"] == "ENABLED — WORKER ACTIVE"
    assert status["treatment"] == "active"
