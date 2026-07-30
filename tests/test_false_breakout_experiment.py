from pathlib import Path

import pandas as pd
import pytest

from false_breakout_experiment import (
    ACTIVE,
    CONFIRMED,
    MODELS,
    CandidateModel,
    _candidate_decision,
    _confirmation_index,
    append_shadow_record,
    atr_extension,
    classify_gap,
    close_confirmed,
    collect_base_setups,
    evaluate_model,
    record_live_shadow,
    risk_reward_at_entry,
    shadow_record,
    target_one_consumption,
    volume_confirmation_features,
)
from optimization_analysis import higher_timeframe_alignment
from trade_replay import add_replay_indicators


def _frame(closes, *, volumes=None):
    index = pd.date_range("2026-07-20 09:30", periods=len(closes), freq="5min")
    volumes = volumes or [1000] * len(closes)
    frame = pd.DataFrame(
        {
            "Open": closes,
            "High": [value + 0.10 for value in closes],
            "Low": [value - 0.10 for value in closes],
            "Close": closes,
            "Volume": volumes,
            "ATR": [1.0] * len(closes),
            "AVG_VOLUME_20": [1000.0] * len(closes),
            "VWAP": [100.0] * len(closes),
            "EMA20": closes,
            "EMA50": [value - 0.05 for value in closes],
            "EMA200": [value - 0.10 for value in closes],
        },
        index=index,
    )
    return frame


def _setup(direction="Bullish", base_index=0):
    bullish = direction == "Bullish"
    return {
        "symbol": "SPY",
        "base_index": base_index,
        "signal_time": "2026-07-20T09:30:00",
        "direction": direction,
        "setup": "BULLISH SETUP" if bullish else "BEARISH SETUP",
        "confidence": 90,
        "entry": 100,
        "trigger": 100,
        "stop": 99 if bullish else 101,
        "target_1": 102 if bullish else 98,
        "target_2": 104 if bullish else 96,
        "target_3": 106 if bullish else 94,
        "atr": 1,
        "bar_minutes": 5,
        "base_outcome": {"realized_return": -0.25, "exit_reason": "STOP"},
        "regime": "range-bound",
        "gap_classification": "<0.25 ATR",
        "gap_atr": 0,
        "higher_timeframe_alignment": "neutral",
        "hour": "09:30-10:00",
    }


def test_close_confirmation_is_point_in_time():
    assert close_confirmed(100.01, 100, 1, "Bullish") is True
    assert close_confirmed(100.04, 100, 1, "Bullish", 0.05) is False
    assert close_confirmed(100.05, 100, 1, "Bullish", 0.05) is True
    assert close_confirmed(99.95, 100, 1, "Bearish", 0.05) is True


def test_two_close_confirmation_occurs_only_after_second_close():
    frame = _frame([99.9, 100.1, 100.2])
    model = CandidateModel("two", confirmation="two_closes")

    index, _reason = _confirmation_index(frame, 0, _setup(), model)

    assert index == 2


def test_future_mutation_does_not_change_earlier_close_decision():
    frame = _frame([100.1, 100.2, 100.3, 100.4])
    before = _confirmation_index(
        frame, 0, _setup(), MODELS["MODEL_B_CLOSE_ONLY"]
    )
    altered = frame.copy()
    altered.iloc[1:, altered.columns.get_loc("Close")] = 1

    assert _confirmation_index(
        altered, 0, _setup(), MODELS["MODEL_B_CLOSE_ONLY"]
    ) == before


def test_volume_ratios_use_current_and_prior_data_only():
    frame = _frame(
        [100] * 8,
        volumes=[500, 600, 700, 800, 900, 1000, 1100, 1200],
    )
    features = volume_confirmation_features(frame, 7)

    assert features["trailing_20_ratio"] == 1.2
    assert features["prior_five_ratio"] == pytest.approx(1200 / 900)
    assert features["same_time_ratio"] is None


def test_extension_consumption_and_risk_reward_are_directionally_symmetric():
    assert atr_extension(100.35, 100, 1, "Bullish") == pytest.approx(0.35)
    assert atr_extension(99.65, 100, 1, "Bearish") == pytest.approx(0.35)
    assert target_one_consumption(101, 100, 102, "Bullish") == 0.5
    assert target_one_consumption(99, 100, 98, "Bearish") == 0.5
    assert risk_reward_at_entry(100, 99, 102, "Bullish") == 2
    assert risk_reward_at_entry(100, 101, 98, "Bearish") == 2


@pytest.mark.parametrize(
    ("gap", "bucket"),
    [
        (0.1, "<0.25 ATR"),
        (0.25, "0.25-0.50 ATR"),
        (0.5, "0.50-1.00 ATR"),
        (-1.1, ">1.00 ATR"),
    ],
)
def test_gap_classification_boundaries(gap, bucket):
    assert classify_gap(gap) == bucket


def test_retest_and_hold_waits_for_resume():
    frame = _frame([100.1, 100.03, 99.99, 100.2])
    frame.iloc[1, frame.columns.get_loc("Low")] = 99.98
    model = CandidateModel("retest", confirmation="retest_hold")

    index, reason = _confirmation_index(frame, 0, _setup(), model)

    assert index == 3
    assert "retested" in reason


def test_retest_logic_is_bullish_bearish_symmetric():
    bullish = _frame([100.1, 100.02, 100.2])
    bearish = _frame([99.9, 99.98, 99.8])
    bullish.iloc[1, bullish.columns.get_loc("Low")] = 99.99
    bearish.iloc[1, bearish.columns.get_loc("High")] = 100.01
    model = CandidateModel("retest", confirmation="retest_hold")

    assert _confirmation_index(bullish, 0, _setup("Bullish"), model)[0] == 2
    assert _confirmation_index(bearish, 0, _setup("Bearish"), model)[0] == 2


def test_risk_reward_gate_marks_consumed_entry_late():
    frame = _frame([101.5, 101.6, 101.7])
    model = CandidateModel(
        "rr",
        min_risk_reward=1.25,
        max_target_consumption=0.50,
    )

    decision = _candidate_decision(frame, 0, _setup(), model)

    assert decision["status"] == "LATE"
    assert "risk/reward" in decision["reason"]


def test_higher_timeframe_alignment_does_not_use_future_bars():
    raw = pd.DataFrame(
        {
            "Open": [100 + i * 0.05 for i in range(100)],
            "High": [100.1 + i * 0.05 for i in range(100)],
            "Low": [99.9 + i * 0.05 for i in range(100)],
            "Close": [100 + i * 0.05 for i in range(100)],
            "Volume": [1000] * 100,
        },
        index=pd.date_range("2026-07-20 09:30", periods=100, freq="5min"),
    )
    frame = add_replay_indicators(raw)
    index = 60
    before = higher_timeframe_alignment(frame, index, "Bullish")
    changed = frame.copy()
    changed.iloc[index + 1 :, changed.columns.get_loc("Close")] = 1

    assert higher_timeframe_alignment(changed, index, "Bullish") == before


def test_model_evaluation_is_deterministic():
    frame = _frame([100.1, 100.6, 100.8, 99.0, 99.0, 99.0])
    setup = _setup()

    first = evaluate_model(
        frame, [setup], MODELS["MODEL_B_CLOSE_ONLY"]
    ).to_dict("records")
    second = evaluate_model(
        frame, [setup], MODELS["MODEL_B_CLOSE_ONLY"]
    ).to_dict("records")

    assert first == second


def test_shadow_evaluator_preserves_production_result_and_isolated_store(tmp_path):
    production = {
        "symbol": "SPY",
        "signal": "BULLISH SETUP",
        "confidence": 90,
        "price": 100.1,
        "entry": 100,
        "stop": 99,
        "target": 102,
        "resistance": 100,
        "atr": 1,
        "last_candle_at": "2026-07-20T09:30:00-04:00",
    }
    original = dict(production)
    shadow_path = tmp_path / "shadow.jsonl"
    returned = record_live_shadow(
        production,
        _frame([100.1]),
        0,
        path=shadow_path,
    )

    assert returned is production
    assert production == original
    assert shadow_path.exists()
    assert not (tmp_path / "signal_history.jsonl").exists()
    assert not (tmp_path / "paper_option_positions.json").exists()


def test_shadow_retry_is_append_only_and_deduplicated(tmp_path):
    record = shadow_record(
        {
            "symbol": "SPY",
            "signal": "WATCHLIST",
            "last_candle_at": "2026-07-20T09:30:00-04:00",
        },
        now="2026-07-20T09:31:00-04:00",
    )
    path = tmp_path / "shadow.jsonl"

    assert append_shadow_record(record, path) is True
    assert append_shadow_record(record, path) is False
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_shadow_module_has_no_production_persistence_or_position_dependency():
    source = Path("false_breakout_experiment.py").read_text(encoding="utf-8")

    for forbidden in (
        "record_scanner_result",
        "signal_history.jsonl",
        "paper_option_positions",
        "create_position",
        "process_scanner_trade_plan",
    ):
        assert forbidden not in source


def test_live_shadow_failure_cannot_interrupt_production_result(monkeypatch):
    import false_breakout_experiment
    import optionbeacon_live

    raw = pd.DataFrame(
        {
            "Open": [100.0] * 35,
            "High": [100.2] * 35,
            "Low": [99.8] * 35,
            "Close": [100.1] * 35,
            "Volume": [1000] * 35,
        },
        index=pd.date_range("2026-07-20 09:30", periods=35, freq="5min"),
    )
    expected = {
        "symbol": "SPY",
        "signal": "BULLISH SETUP",
        "confidence": 90,
        "price": 100.1,
        "entry": 100.1,
        "stop": 99.8,
        "target": 100.6,
        "resistance": 100,
        "support": 99,
        "atr": 1,
    }
    monkeypatch.setattr(optionbeacon_live, "get_data", lambda _symbol: raw)
    monkeypatch.setattr(
        optionbeacon_live,
        "add_indicators",
        lambda frame: _frame([100.1] * len(frame)),
    )
    monkeypatch.setattr(
        optionbeacon_live,
        "score_candle",
        lambda *_args, **_kwargs: dict(expected),
    )
    monkeypatch.setattr(
        optionbeacon_live,
        "enrich_with_trade_plan",
        lambda result: result,
    )
    monkeypatch.setattr(
        optionbeacon_live,
        "enrich_with_option_liquidity",
        lambda result: result,
    )
    monkeypatch.setattr(
        optionbeacon_live,
        "process_scanner_trade_plan",
        lambda _result: None,
    )
    monkeypatch.setattr(
        optionbeacon_live,
        "update_trade_outcomes_from_result",
        lambda _result: None,
    )
    monkeypatch.setattr(
        optionbeacon_live,
        "record_scanner_result",
        lambda _result: None,
    )
    monkeypatch.setattr(
        false_breakout_experiment,
        "record_live_shadow",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    result = optionbeacon_live.generate_signal("SPY")

    for key, value in expected.items():
        assert result[key] == value
