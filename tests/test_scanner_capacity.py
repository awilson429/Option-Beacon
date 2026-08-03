import json
import inspect
from datetime import datetime, timedelta, timezone

import pytest

from developer_tools import scanner_capacity_summary
from optionbeacon.worker.capacity import (
    aggregate_symbol_timings,
    capacity_health,
    deterministic_symbol_subset,
    opportunity_density,
    percentile,
    schedule_delay_seconds,
    summarize_capacity,
    utilization_percent,
    verbose_capacity_diagnostics_enabled,
)
from optionbeacon.worker.scan_once import run_scan_once
from trade_repository import TradeRepository
from app import render_developer_tools


NOW = datetime(2026, 8, 3, 14, 0, tzinfo=timezone.utc)


def metric(**overrides):
    values = {
        "scanner_id": "scanner", "scan_started_at": NOW,
        "scan_completed_at": NOW + timedelta(seconds=20),
        "scanner_interval_seconds": 60, "configured_symbols": 25,
        "attempted_symbols": 25, "successful_symbols": 24, "failed_symbols": 1,
        "skipped_symbols": 0, "rate_limit_count": 0, "provider_warning_count": 0,
        "retry_count": 0, "request_count": 25, "cache_hit_count": 0,
        "scan_duration_seconds": 20, "avg_symbol_seconds": .8,
        "p50_symbol_seconds": .7, "p95_symbol_seconds": 1.2,
        "max_symbol_seconds": 1.5, "repository_write_seconds": .2,
        "opportunities_generated": 3, "actionable_opportunities": 1,
        "watch_count": 1, "wait_count": 1, "open_count": 0,
        "top_ranked_count": 0, "opportunity_density": .125,
        "partial_scan": 1, "scan_status": "PARTIAL", "utilization_percent": 33.333,
        "capacity_health": "CAUTION", "overlap_detected": 0, "overlap_count": 0,
        "schedule_delay_seconds": 0, "intended_scan_start": NOW,
        "metadata_json": {"included_symbols": ["SPY"]},
    }
    values.update(overrides)
    return values


def test_utilization_health_bands_and_overlap():
    assert utilization_percent(30, 60) == 50
    assert capacity_health(49) == "HEALTHY"
    assert capacity_health(50) == "CAUTION"
    assert capacity_health(75) == "SATURATED"
    assert capacity_health(100) == "OVERLOADED"
    assert capacity_health(10, overlap=True) == "OVERLOADED"


def test_timing_percentiles_and_repository_aggregation():
    timings = [
        {"duration_seconds": value, "repository_seconds": .1}
        for value in [1, 2, 3, 4, 5]
    ]
    result = aggregate_symbol_timings(timings)
    assert result["avg_symbol_seconds"] == 3
    assert result["p50_symbol_seconds"] == 3
    assert result["p95_symbol_seconds"] == pytest.approx(4.8)
    assert result["max_symbol_seconds"] == 5
    assert result["repository_write_seconds"] == pytest.approx(.5)
    assert percentile([], 95) == 0


def test_schedule_delay_density_subset_and_diagnostics(monkeypatch):
    assert schedule_delay_seconds(NOW, NOW + timedelta(seconds=7)) == 7
    assert schedule_delay_seconds(NOW, NOW - timedelta(seconds=1)) == 0
    assert opportunity_density(3, 12) == .25
    symbols, limit = deterministic_symbol_subset(["SPY", "QQQ", "IWM"], "2")
    assert symbols == ["SPY", "QQQ"] and limit == 2
    monkeypatch.delenv("OPTIONBEACON_BENCHMARK_SYMBOL_LIMIT", raising=False)
    assert deterministic_symbol_subset(["SPY"])[0] == ["SPY"]
    assert verbose_capacity_diagnostics_enabled() is False


def test_repository_persistence_summary_and_minimum_threshold(tmp_path):
    repo = TradeRepository(tmp_path / "state.db", database_url="")
    for index in range(10):
        repo.record_capacity_metrics(metric(id=f"m{index}"))
    rows = repo.list_capacity_metrics()
    assert len(rows) == 10
    assert rows[0]["metadata_json"]["included_symbols"] == ["SPY"]
    summary = scanner_capacity_summary(repo)
    assert summary["recommended_max_symbols"] == 25
    assert summary["recent"]["success_rate_percent"] == 96
    insufficient = summarize_capacity(rows[:9])
    assert insufficient["recommended_max_symbols"] is None
    assert insufficient["insufficient_data"] is True


def test_scan_metrics_count_partial_429_retry_cache_and_default_universe(tmp_path, monkeypatch):
    repo = TradeRepository(tmp_path / "state.db", database_url="")
    monkeypatch.delenv("OPTIONBEACON_BENCHMARK_SYMBOL_LIMIT", raising=False)
    result = run_scan_once(
        repository=repo,
        symbol_groups_loader=lambda: ({"Core": ["SPY", "QQQ"]}, "test", ""),
        signal_generator=lambda symbol: {"symbol": symbol, "signal": "WATCH" if symbol == "SPY" else "WAIT", "price": 500},
        snapshot_writer=lambda results: None,
        scanner_interval_seconds=60,
    )
    assert result == 0
    row = repo.list_capacity_metrics(limit=1)[0]
    assert row["configured_symbols"] == 2
    assert row["successful_symbols"] == 2
    assert row["watch_count"] == 1 and row["wait_count"] == 1
    assert row["metadata_json"]["included_symbols"] == ["SPY", "QQQ"]


def test_overlap_is_persisted(tmp_path):
    repo = TradeRepository(tmp_path / "state.db", database_url="")
    owner = repo.acquire_scan_lock()
    assert run_scan_once(repository=repo, scanner_interval_seconds=60, intended_start=NOW) == 2
    repo.release_scan_lock("optionbeacon-scanner", owner)
    row = repo.list_capacity_metrics(limit=1)[0]
    assert row["overlap_detected"] == 1
    assert row["scan_status"] == "SKIPPED_OVERLAP"


def test_verbose_symbol_details_are_opt_in(tmp_path, monkeypatch):
    repo = TradeRepository(tmp_path / "state.db", database_url="")
    monkeypatch.setenv("OPTIONBEACON_VERBOSE_CAPACITY_DIAGNOSTICS", "true")
    run_scan_once(
        repository=repo,
        symbol_groups_loader=lambda: ({"Core": ["SPY"]}, "test", ""),
        signal_generator=lambda symbol: {"symbol": symbol, "signal": "WAIT", "price": 500},
        snapshot_writer=lambda results: None,
    )
    assert repo.list_capacity_metrics(limit=1)[0]["metadata_json"]["symbol_timings"][0]["symbol"] == "SPY"


def test_developer_tools_renders_compact_capacity_section():
    source = inspect.getsource(render_developer_tools)
    assert 'st.markdown("### Scanner Capacity")' in source
    assert '"Utilization (%)"' in source
    assert '"Health"' in source
    assert "universe_comparison" in source
