import copy
import inspect
from datetime import datetime, timedelta, timezone

import app

from authoritative_entry_funnel import (
    AuthoritativeEntryFunnelRepository,
    classify_symbol,
    configured_thresholds,
    funnel_counts,
    near_entry_rows,
)
from trade_repository import TradeRepository


NOW = datetime(2026, 8, 6, 14, 35, tzinfo=timezone.utc)


def result(symbol="SPY", **changes):
    value = {
        "symbol": symbol, "signal": "WATCHLIST", "bias": "Bullish",
        "confidence": 80, "price": 99.9, "setup_stage": "Armed",
        "entry_timing": "Watch closely", "timestamp": NOW.isoformat(),
        "trade_plan": {
            "direction": "Bullish", "setup_type": "Bullish breakout",
            "trigger_price": 100, "technical_stop": 99,
            "target_1": 101, "target_2": 102, "target_3": 103,
        },
    }
    value.update(changes)
    return value


def test_classification_uses_real_states_and_does_not_mutate_results():
    source = result()
    before = copy.deepcopy(source)
    row = classify_symbol("SPY", source)
    assert source == before
    assert row["direction"] == "CALL"
    assert row["state"] == "Armed"
    assert row["primary_blocker"] == "TRIGGER_NOT_REACHED"
    assert row["distance_to_trigger_pct"] > 0


def test_actual_blockers_cover_data_direction_score_trigger_and_lifecycle():
    insufficient = classify_symbol("BAD", None)
    neutral = classify_symbol("FLAT", result("FLAT", bias="Neutral", trade_plan={}))
    score = classify_symbol("LOW", result("LOW"))
    triggered = classify_symbol("GO", result(
        "GO", signal="BULLISH SETUP", confidence=95, price=100.1,
        setup_stage="Triggered", entry_timing="Trigger confirmed",
    ))
    assert insufficient["primary_blocker"] == "INSUFFICIENT_DATA"
    assert neutral["primary_blocker"] == "DIRECTION_UNCLEAR"
    assert score["primary_blocker"] == "TRIGGER_NOT_REACHED"
    assert triggered["primary_blocker"] == "AWAITING_AUTHORITATIVE_LIFECYCLE"
    counts = funnel_counts([insufficient, neutral, score, triggered], entered_count=1)
    assert counts == {
        "scanned": 4, "valid_results": 3, "directional_candidates": 2,
        "qualified_setups": 1, "armed": 1, "trigger_reached": 1,
        "trade_entered": 1,
    }


def test_funnel_persistence_reconciles_entered_events_and_session_history(tmp_path):
    repository = TradeRepository(tmp_path / "state.db", database_url="")
    diagnostics = AuthoritativeEntryFunnelRepository(repository)
    first = diagnostics.save_cycle(
        scanner_id="scanner", run_number=1, started_at=NOW - timedelta(minutes=2),
        completed_at=NOW, symbols=[("SPY", result("SPY", signal="BULLISH SETUP",
            confidence=95, price=100.1, setup_stage="Triggered", entry_timing="Trigger confirmed"))],
        entered_events=[{"symbol": "SPY", "event_type": "TRADE_ENTERED"}],
    )
    assert first["trade_entered"] == 1
    cycle = diagnostics.latest_cycle("2026-08-06")
    rows = diagnostics.symbol_rows(cycle["cycle_id"])
    assert rows[0]["trade_entered"] == 1 and rows[0]["primary_blocker"] is None
    diagnostics.save_cycle(
        scanner_id="scanner", run_number=0, started_at=NOW - timedelta(days=1, minutes=2),
        completed_at=NOW - timedelta(days=1), symbols=[("QQQ", result("QQQ"))],
        entered_events=[],
    )
    assert diagnostics.previous_session_cycle("2026-08-06")["session_date"] == "2026-08-05"


def test_near_entry_is_deterministic_and_prioritizes_armed():
    rows = [
        classify_symbol("FAR", result("FAR", price=98, setup_stage="Developing")),
        classify_symbol("NEAR", result("NEAR", price=99.95)),
    ]
    assert [row["symbol"] for row in near_entry_rows(rows)] == ["NEAR", "FAR"]


def test_current_thresholds_match_production_constants():
    thresholds = configured_thresholds()
    assert thresholds["call_score_threshold"] == 90
    assert thresholds["put_score_threshold"] == 90
    assert thresholds["authoritative_entry_confidence"] == 65
    assert thresholds["volume_multiplier"] == 1.4
    assert thresholds["breakout_buffer_up"] == 1.0003


def test_developer_tools_is_read_only_for_funnel_state():
    source = inspect.getsource(app.render_authoritative_entry_funnel)
    assert "initialize=False" in source
    for forbidden in ("save_cycle", "initialize()", "_execute", "INSERT", "UPDATE", "DELETE"):
        assert forbidden not in source
