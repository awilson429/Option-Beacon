import logging
from pathlib import Path

import optionbeacon.worker.scan_once as scan_module
from paper_execution import AuthoritativeEntryProjectionError, pending_authoritative_entries
from paper_execution_repository import PaperExecutionRepository
from optionbeacon.worker.scan_once import run_scan_once
from trade_repository import TradeRepository


def messages(caplog):
    return "\n".join(record.getMessage() for record in caplog.records)


def test_partial_rate_limits_still_complete_zero_candidate_paper_cycle(
    tmp_path, monkeypatch, caplog
):
    repository = TradeRepository(tmp_path / "state.db", database_url="")
    monkeypatch.setenv("OPTIONBEACON_EXECUTION_MODE", "PAPER")
    monkeypatch.setenv("OPTIONBEACON_TRADING_ENABLED", "true")

    def signal(symbol):
        if symbol != "SPY":
            raise RuntimeError("HTTP 429 Too Many Requests")
        return {"symbol": symbol, "signal": "WAIT", "price": 500}

    with caplog.at_level(logging.INFO):
        result = run_scan_once(
            repository=repository,
            scanner_id="railway-primary",
            run_number=14,
            symbol_groups_loader=lambda: (
                {"Production": ["SPY", "IWM", "JD", "JETS"]}, "test", ""
            ),
            signal_generator=signal,
            snapshot_writer=lambda results: None,
        )

    output = messages(caplog)
    assert result == 0
    assert '"event": "paper_state_restored"' in output
    assert '"event": "paper_positions_refreshed"' in output
    assert '"event": "paper_authoritative_handoff"' in output
    assert '"paper_candidates_received": 0' in output
    assert '"event": "paper_cycle_started"' in output
    assert '"event": "paper_cycle_completed"' in output
    assert '"candidates_received": 0' in output
    assert '"candidates_evaluated": 0' in output
    assert '"candidates_rejected": 0' in output
    assert '"candidates_opened": 0' in output


def test_universe_failure_is_structured_and_paper_cycle_still_runs(
    tmp_path, monkeypatch, caplog
):
    repository = TradeRepository(tmp_path / "state.db", database_url="")
    monkeypatch.setenv("OPTIONBEACON_EXECUTION_MODE", "PAPER")
    monkeypatch.setenv("OPTIONBEACON_TRADING_ENABLED", "true")

    with caplog.at_level(logging.INFO):
        result = run_scan_once(
            repository=repository,
            scanner_id="railway-primary",
            symbol_groups_loader=lambda: (_ for _ in ()).throw(
                RuntimeError("provider unavailable")
            ),
            snapshot_writer=lambda results: None,
        )

    output = messages(caplog)
    assert result == 1
    assert '"event": "scanner_phase_failed"' in output
    assert '"stage": "universe_loading"' in output
    assert '"paper_handoff_will_run": true' in output
    assert '"event": "paper_authoritative_handoff"' in output
    assert '"event": "paper_cycle_completed"' in output


def test_pending_entry_database_failure_is_explicit_and_releases_lock(
    tmp_path, monkeypatch, caplog
):
    repository = TradeRepository(tmp_path / "state.db", database_url="")
    monkeypatch.setattr(
        scan_module,
        "pending_authoritative_entries",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("database read failed")),
    )

    with caplog.at_level(logging.INFO):
        result = run_scan_once(
            repository=repository,
            scanner_id="railway-primary",
            symbol_groups_loader=lambda: ({"Core": []}, "test", ""),
            snapshot_writer=lambda results: None,
        )

    output = messages(caplog)
    assert result == 1
    assert '"event": "paper_cycle_failed"' in output
    assert '"stage": "authoritative_entry_query"' in output
    assert '"event": "scanner_lock_released"' in output


def test_railway_runs_the_only_persistent_worker_entrypoint():
    railway = Path("railway.toml").read_text(encoding="utf-8")
    worker = Path("optionbeacon/worker/run.py").read_text(encoding="utf-8")
    assert "python -m optionbeacon.worker.run" in railway
    assert "from optionbeacon.worker.scan_once import run_scan_once" in worker


def test_malformed_authoritative_entry_cannot_silently_disappear(tmp_path):
    repository = TradeRepository(tmp_path / "state.db", database_url="")
    repository.create_opportunity(
        opportunity_id="broken-entry", idempotency_key="broken-entry",
        symbol="ABNB", direction="Bearish", playbook="Breakdown",
        signal_timestamp="2026-08-04T14:30:00+00:00", source_version="test",
        state="OPEN", metadata={},
    )
    repository.record_trade_event(
        dedup_key="broken-event", trade_id="broken-entry",
        opportunity_id="broken-entry", symbol="ABNB", direction="Bearish",
        setup="Breakdown", event_type="TRADE_ENTERED",
        event_timestamp="2026-08-04T14:35:00+00:00",
        description="Synthetic malformed entry",
    )
    paper = PaperExecutionRepository(repository)

    try:
        pending_authoritative_entries(repository, {}, paper)
    except AuthoritativeEntryProjectionError as exc:
        assert "broken-entry" in str(exc)
    else:
        raise AssertionError("Malformed authoritative entry was silently skipped")
