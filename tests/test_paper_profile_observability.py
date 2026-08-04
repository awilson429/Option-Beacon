import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from execution_config import (
    ExecutionConfig,
    execution_config_log_record,
    resolved_execution_config,
)
from paper_execution_repository import PaperExecutionRepository
from paper_trading_page import paper_execution_funnel
from optionbeacon.worker.scan_once import run_scan_once
from trade_repository import TradeRepository


NOW = datetime(2026, 8, 4, 18, tzinfo=timezone.utc)


def broad_environment(**overrides):
    values = {
        "PAPER_SIMULATION_PROFILE": "  broad  ",
        "OPTIONBEACON_EXECUTION_MODE": "PAPER",
        "OPTIONBEACON_TRADING_ENABLED": "true",
    }
    values.update(overrides)
    return values


def test_railway_broad_parsing_defaults_and_override_precedence():
    config = ExecutionConfig.from_environment(broad_environment())
    assert config.simulation_profile == "BROAD"
    assert config.min_beacon_score == 40
    assert config.max_open_positions == 5
    assert config.max_trades_per_day == 20
    assert config.max_dollars_per_trade == 250
    assert config.max_total_deployed_capital == 1250
    assert config.max_daily_loss_dollars == 100
    assert config.max_consecutive_losses == 0
    assert config.loss_cooldown_minutes == 0
    assert config.earliest_entry_time.isoformat() == "09:45:00"
    assert config.latest_entry_time.isoformat() == "15:00:00"

    overridden = ExecutionConfig.from_environment(broad_environment(
        OPTIONBEACON_MIN_BEACON_SCORE="41",
        OPTIONBEACON_MAX_OPEN_POSITIONS="4",
    ))
    assert overridden.simulation_profile == "BROAD"
    assert overridden.min_beacon_score == 41
    assert overridden.max_open_positions == 4


def test_resolved_config_log_is_complete_and_non_secret():
    config = ExecutionConfig.from_environment(broad_environment())
    record = execution_config_log_record(config)
    assert record == {
        "event": "paper_execution_config_resolved",
        "simulation_profile": "BROAD",
        "min_score": 40,
        "max_open_positions": 5,
        "max_trades_per_day": 20,
        "max_dollars_per_trade": 250,
        "max_total_deployed_capital": 1250,
        "max_daily_loss": 100,
        "max_consecutive_losses": 0,
        "loss_cooldown_minutes": 0,
        "entry_window": "09:45:00-15:00:00 America/New_York",
    }
    assert "database" not in json.dumps(record).lower()


def test_worker_state_persists_and_streamlit_local_safe_cannot_override_it(tmp_path):
    trade_repository = TradeRepository(tmp_path / "state.db", database_url="")
    paper = PaperExecutionRepository(trade_repository)
    railway_config = ExecutionConfig.from_environment(broad_environment())
    saved = paper.save_runtime_config("railway-primary", railway_config)

    restarted = PaperExecutionRepository(
        TradeRepository(tmp_path / "state.db", database_url="")
    )
    authoritative = restarted.get_runtime_config()
    local_safe = ExecutionConfig.from_environment({})
    displayed = ExecutionConfig.from_resolved_state(
        authoritative["resolved_config"], fallback=local_safe
    )
    assert saved["simulation_profile"] == "BROAD"
    assert displayed.simulation_profile == "BROAD"
    assert displayed.min_beacon_score == 40
    assert displayed.max_open_positions == 5


def test_worker_cycle_logs_and_persists_resolved_broad_config(
    tmp_path, monkeypatch, caplog
):
    repository = TradeRepository(tmp_path / "state.db", database_url="")
    for key, value in broad_environment().items():
        monkeypatch.setenv(key, value)
    with caplog.at_level(logging.INFO):
        run_scan_once(
            repository=repository, scanner_id="railway-primary", run_number=1,
            symbol_groups_loader=lambda: ({"Core": []}, "test", ""),
            snapshot_writer=lambda results: None,
        )
    output = "\n".join(record.getMessage() for record in caplog.records)
    assert '"event": "paper_execution_config_resolved"' in output
    assert '"simulation_profile": "BROAD"' in output
    assert '"min_score": 40.0' in output
    state = PaperExecutionRepository(repository).get_runtime_config("railway-primary")
    assert state["simulation_profile"] == "BROAD"
    assert state["effective_min_score"] == 40


def test_future_journal_decision_is_stamped_with_worker_profile(tmp_path):
    repository = PaperExecutionRepository(
        TradeRepository(tmp_path / "state.db", database_url="")
    )
    config = ExecutionConfig.from_environment(broad_environment())
    repository.append(
        checked_at=NOW,
        result={"symbol": "SPY"},
        trade=SimpleNamespace(trade_id="paper-1", option_symbol="SPY-C"),
        decision=SimpleNamespace(
            eligible=False, reason="SCORE_TOO_LOW", position_size=0,
            maximum_cost=0, paper_fill_price=None,
        ),
        execution_config=config,
    )
    metadata = json.loads(repository.journal_rows()[0]["metadata_json"])
    assert metadata["simulation_profile"] == "BROAD"
    assert metadata["effective_min_score"] == 40
    assert metadata["journal_type"] == "ENTRY_DECISION"


def test_historical_safe_and_future_broad_decisions_remain_distinct():
    events = [
        {"event_type": "TRADE_ENTERED", "opportunity_id": source,
         "event_timestamp": NOW.isoformat()}
        for source in ("safe-source", "broad-source")
    ]
    captures = [
        SimpleNamespace(trade_id="safe-trade", source_signal_id="safe-source"),
        SimpleNamespace(trade_id="broad-trade", source_signal_id="broad-source"),
    ]
    journal = [
        {"trade_id": "safe-trade", "created_at": NOW.isoformat(), "accepted": 0,
         "reason_code": "SCORE_TOO_LOW", "metadata_json": json.dumps({
             "journal_type": "ENTRY_DECISION", "simulation_profile": "SAFE",
             "effective_min_score": 92,
         })},
        {"trade_id": "broad-trade", "created_at": NOW.isoformat(), "accepted": 1,
         "reason_code": "ELIGIBLE", "metadata_json": json.dumps({
             "journal_type": "ENTRY_DECISION", "simulation_profile": "BROAD",
             "effective_min_score": 40,
         })},
    ]
    funnel = paper_execution_funnel(events, journal, captures, NOW)
    assert funnel["decisions_by_profile"] == {"BROAD": 1, "SAFE": 1}
    assert funnel["opened"] == 1 and funnel["rejected"] == 1


def test_streamlit_reads_worker_state_and_remains_read_only():
    source = Path("app.py").read_text(encoding="utf-8")
    page = source[source.index("def render_paper_trading_page("):source.index("def render_developer_tools(")]
    assert "get_runtime_config" in page
    assert "from_resolved_state" in page
    assert "CURRENT WORKER PROFILE" in page
    assert "config.simulation_profile" not in page
    assert "ExecutionConfig.from_environment" not in page
    assert "initialize=False" in page
    for forbidden in ("save_runtime_config", ".save(", ".append(", "update_position("):
        assert forbidden not in page
