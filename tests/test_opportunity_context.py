from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from opportunity_context import (
    OpportunityContextAnalyticsRepository, attribution, build_opportunity_context,
    context_coverage, dte_bucket, experiment_scope, pullback_structure,
    relative_volume_bucket, return_percent, signal_age_bucket, spread_bucket, trend_state,
)
from trade_repository import TradeRepository


NOW = datetime(2026, 8, 18, 14, 35, tzinfo=timezone.utc)


def record(identifier="opp-1"):
    return SimpleNamespace(trade_id=identifier, symbol="AAPL", direction="Bullish", timestamp=NOW, entry_time=NOW)


def result():
    return {
        "timestamp": NOW, "relative_volume": 2.4, "symbol_session_return": 2.0,
        "sector_session_return": 1.0, "spy_session_return": .25,
        "market_context": {"spy_direction": "UP", "qqq_direction": "UP", "spy_vs_vwap": "ABOVE"},
        "timeframe_trends": {"1m": "UP", "5m": {"fast_ema": 11, "slow_ema": 10, "slope": .1}, "15m": "NEUTRAL"},
        "first_candidate_detected_at": "2026-08-18T14:33:00+00:00",
        "setup_detected_at": "2026-08-18T14:34:00+00:00",
        "setup_confirmed_at": "2026-08-18T14:34:30+00:00",
        "price_structure": {"initial_impulse_magnitude": 1.2, "pullback_depth": .3, "reclaim_confirmed": True},
    }


def test_context_identity_et_timestamp_and_no_future_leakage():
    context = build_opportunity_context(result(), record())
    assert context["opportunity_id"] == "opp-1"
    assert context["eastern_session"] == "2026-08-18"
    assert context["lifecycle"]["setup_to_authoritative_seconds"] == 60
    assert context["structure"]["classification"] == "BULLISH_PULLBACK_RECLAIM"
    leaked = result(); leaked["price_structure"] = {"observed_after_decision": True, "initial_impulse_magnitude": 2}
    assert build_opportunity_context(leaked, record())["structure"]["classification"] == "INSUFFICIENT_DATA"


def test_deterministic_trends_relative_strength_and_alignment():
    context = build_opportunity_context(result(), record())
    assert trend_state({"fast_ema": 12, "slow_ema": 10, "slope": .1}) == "BULLISH"
    assert return_percent(100, 102) == pytest.approx(2)
    assert context["sector"]["sector"] == "Technology"
    assert context["sector"]["stock_vs_sector_relative_strength"] == 1
    assert context["sector"]["stock_vs_spy_relative_strength"] == 1.75
    assert context["multi_timeframe"]["number_of_timeframes_aligned_with_trade"] == 2
    assert context["multi_timeframe"]["total_timeframes_available"] == 3


@pytest.mark.parametrize("value,expected", [(None,"UNKNOWN"),(.4,"LT_0_5"),(.5,"0_5_TO_1"),(1,"1_TO_1_5"),(1.5,"1_5_TO_2"),(2,"2_TO_3"),(3,"3_TO_5"),(5,"GE_5")])
def test_relative_volume_buckets(value, expected): assert relative_volume_bucket(value) == expected


@pytest.mark.parametrize("value,expected", [(None,"UNKNOWN"),(30,"LE_30"),(31,"31_60"),(61,"61_120"),(121,"121_180"),(181,"181_300"),(301,"GT_300")])
def test_signal_age_buckets(value, expected): assert signal_age_bucket(value) == expected


@pytest.mark.parametrize("value,expected", [(None,"UNKNOWN"),(5,"LE_5"),(10,"5_10"),(15,"10_15"),(20,"15_20"),(21,"GT_20")])
def test_spread_buckets(value, expected): assert spread_bucket(value) == expected


@pytest.mark.parametrize("value,expected", [(None,"UNKNOWN"),(0,"0"),(1,"1"),(3,"2_3"),(7,"4_7"),(8,"GT_7")])
def test_dte_buckets(value, expected): assert dte_bucket(value) == expected


def test_pullback_classifier_and_missing_data():
    assert pullback_structure({}, "Bullish") == "INSUFFICIENT_DATA"
    assert pullback_structure({"initial_impulse_magnitude": 1}, "Bearish") == "DIRECT_BREAKDOWN"
    assert pullback_structure({"initial_impulse_magnitude": 1, "pullback_depth": .2, "reclaim_confirmed": True}, "Bearish") == "BEARISH_BOUNCE_REJECTION"


def test_idempotent_additive_storage_and_enrichment(tmp_path):
    repo = TradeRepository(tmp_path / "context.db"); repo.initialize()
    repo.create_opportunity(opportunity_id="opp-1", idempotency_key="opp-1", symbol="AAPL", direction="Bullish", playbook="Breakout", signal_timestamp=NOW, source_version="test")
    original = build_opportunity_context(result(), record())
    repo.create_opportunity_context("opp-1", original)
    repo.create_opportunity_context("opp-1", {**original, "captured_at": "changed"})
    repo.enrich_opportunity_context("opp-1", {"option_execution": {"spread_percent": 12}})
    assert len(repo.list_opportunity_contexts()) == 1
    stored = repo.get_opportunity_context("opp-1")["context"]
    assert stored["captured_at"] == NOW.isoformat()
    assert stored["option_execution"]["spread_percent"] == 12


def test_coverage_scope_and_chronological_governance():
    dev = build_opportunity_context(result(), record("dev"), captured_at="2026-08-12T14:00:00Z")
    fwd = build_opportunity_context(result(), record("fwd"), captured_at="2026-08-18T14:00:00Z")
    assert experiment_scope("2026-08-12T14:00:00Z") == "DEVELOPMENT"
    assert experiment_scope("2026-08-18T14:00:00Z") == "FORWARD_TEST"
    coverage = context_coverage([dev, fwd])
    assert next(row for row in coverage if row["factor"] == "catalyst_category")["coverage_pct"] == 0
    report = attribution([dev, fwd], [{"opportunity_id":"dev","realized_return":2},{"opportunity_id":"fwd","realized_return":1}], {}, scope="ALL")
    assert all(row["governance"] == "INSUFFICIENT DATA" for row in report["factors"])


def test_analytics_reads_are_bounded_projected_and_read_only():
    source = Path("opportunity_context.py").read_text(encoding="utf-8")
    section = source[source.index("class OpportunityContextAnalyticsRepository"):]
    assert "SELECT *" not in section
    assert " LIMIT ?" in section and " IN (" in section
    for forbidden in ("INSERT ", "UPDATE ", "DELETE ", "provider", "option_quote", "select_contract"):
        assert forbidden not in section


def test_dashboard_has_no_writes_or_provider_calls():
    source = Path("opportunity_context_dashboard.py").read_text(encoding="utf-8")
    assert "Load Opportunity Context Attribution" in source
    for forbidden in ("INSERT", "UPDATE", "DELETE", "create_", "record_", "provider", "option_quote"):
        assert forbidden not in source


def test_capture_failure_is_explicitly_isolated_from_trading_path():
    source = Path("trade_state_service.py").read_text(encoding="utf-8")
    body = source[source.index("def _persist_opportunity_context"):source.index("def _persist_outcome_label")]
    assert "try:" in body and "except Exception:" in body
    assert "build_opportunity_context" in body
