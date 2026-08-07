from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from intraday_strategy import Candidate, OpportunityState, aggregate_bars, detect_candidate, opportunity_id, transition, trigger_crossed

ET = ZoneInfo("America/New_York")

def bars(reclaim=False):
    start = datetime(2026, 8, 7, 9, 30, tzinfo=ET)
    rows = [{"timestamp": start + timedelta(minutes=i), "open": 600+i*.1-.03,
             "high": 600+i*.1+.08, "low": 600+i*.1-.08, "close": 600+i*.1,
             "volume": 1000+i*20} for i in range(30)]
    if reclaim:
        rows[-2]["close"] = 599
        rows[-1].update(open=599, low=598.9, high=603.2, close=603.1, volume=5000)
    return rows

def test_universe_is_hard_and_spy_qqq_candidates_are_supported():
    assert detect_candidate("AAPL", bars(), bars()) is None
    assert detect_candidate("SPY", bars(True), bars()) is not None
    assert detect_candidate("QQQ", bars(True), bars()) is not None

def test_vwap_reclaim_is_explainable_and_identity_is_durable():
    candidate = detect_candidate("SPY", bars(True), bars())
    assert candidate.setup == "VWAP RECLAIM" and candidate.direction == "CALL"
    assert "1m VWAP reclaimed" in candidate.reasons
    assert candidate.opportunity_id == opportunity_id("SPY", candidate.setup, "CALL", candidate.detected_at)

def test_aggregation_transition_and_trigger_are_strict():
    assert len(aggregate_bars(bars(), 3)) == 10
    assert transition("OBSERVING", "SETUP_DETECTED") is OpportunityState.SETUP_DETECTED
    with pytest.raises(ValueError): transition("OBSERVING", "TRIGGERED")
    candidate = Candidate("id", "SPY", "CALL", "VWAP RECLAIM", 75, 10, 10.1, datetime.now(ET), "MORNING", "TRENDING UP")
    assert trigger_crossed(candidate, 10, 10.2)
