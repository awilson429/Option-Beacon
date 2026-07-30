from copy import deepcopy
import json

import numpy as np
import pandas as pd

import optionbeacon_live
from regime_selection_experiment import (
    ACTIVE,
    DEFAULT_MINIMUM_SAMPLE,
    TREE_MAX_DEPTH,
    TREE_MIN_LEAF_SIZE,
    append_shadow_record,
    context_for_setup,
    evidence_label,
    gap_regime,
    grouped,
    model_decision,
    record_live_shadow,
    selection_metrics,
    shadow_record,
    time_window,
)


def _frame():
    index = pd.date_range(
        "2026-07-27 09:30", periods=50, freq="5min", tz="America/New_York"
    )
    values = np.linspace(100, 102, len(index))
    return pd.DataFrame(
        {
            "Open": values,
            "High": values + 0.2,
            "Low": values - 0.2,
            "Close": values,
            "Volume": np.linspace(1000, 2000, len(index)),
            "ATR": 0.5,
            "VWAP": values - 0.05,
            "AVG_VOLUME_20": 1200,
            "EMA20": values - 0.1,
            "EMA50": values - 0.2,
            "EMA200": values - 0.3,
        },
        index=index,
    )


def _setup(**changes):
    setup = {
        "symbol": "QQQ",
        "base_index": 12,
        "signal_time": "2026-07-27T10:30:00-04:00",
        "direction": "Bullish",
        "setup": "BULLISH SETUP",
        "entry": 100.5,
        "trigger": 100.5,
        "stop": 99.5,
        "target_1": 101.5,
        "target_2": 102.5,
        "target_3": 103.5,
        "atr": 0.5,
        "bar_minutes": 5,
        "regime": "high-volatility expansion",
        "gap_atr": 0.1,
        "higher_timeframe_alignment": "aligned",
        "base_outcome": {
            "realized_return": 0.5,
            "exit_reason": "TARGET_1",
            "target_1_hit": True,
            "target_2_hit": False,
            "target_3_hit": False,
            "stop_first": False,
            "invalidated_quickly": False,
            "mfe": 0.7,
            "mae": -0.1,
            "hold_minutes": 20,
        },
    }
    setup.update(changes)
    return setup


def _rows():
    return pd.DataFrame(
        [
            {
                "status": ACTIVE,
                "symbol": "QQQ",
                "direction": "bullish",
                "signal_time": "2026-07-27T10:30:00-04:00",
                "base_return": 0.5,
                "realized_return": 0.5,
                "exit_reason": "TARGET_1",
                "target_1_hit": True,
                "target_2_hit": False,
                "stop_first": False,
                "invalidated_quickly": False,
                "mfe": 0.7,
                "mae": -0.1,
                "hold_minutes": 20,
            },
            {
                "status": ACTIVE,
                "symbol": "SPY",
                "direction": "bearish",
                "signal_time": "2026-07-28T13:30:00-04:00",
                "base_return": -0.25,
                "realized_return": -0.25,
                "exit_reason": "STOP",
                "target_1_hit": False,
                "target_2_hit": False,
                "stop_first": True,
                "invalidated_quickly": True,
                "mfe": 0.1,
                "mae": -0.3,
                "hold_minutes": 10,
            },
        ]
    )


def test_context_labels_use_setup_time_only_and_future_mutation_is_safe():
    frame = _frame()
    setup = _setup()
    before = context_for_setup(setup)
    frame.iloc[20:, frame.columns.get_loc("Close")] = 10000
    assert context_for_setup(setup) == before


def test_symbol_and_direction_segmentation():
    result = grouped(_rows(), ("symbol", "direction"), minimum_sample=1)
    assert {(row["symbol"], row["direction"]) for row in result} == {
        ("QQQ", "bullish"),
        ("SPY", "bearish"),
    }


def test_time_window_boundaries():
    assert time_window("2026-07-27T09:30:00-04:00") == "09:30-10:00"
    assert time_window("2026-07-27T10:00:00-04:00") == "10:00-11:00"
    assert time_window("2026-07-27T11:00:00-04:00") == "11:00-13:00"
    assert time_window("2026-07-27T13:00:00-04:00") == "13:00-14:00"
    assert time_window("2026-07-27T14:00:00-04:00") == "14:00-15:00"
    assert time_window("2026-07-27T15:00:00-04:00") == "15:00-16:00"


def test_gap_regime_classification():
    assert gap_regime(0.1, "normal") == "no meaningful gap"
    assert gap_regime(0.3, "normal") == "small gap"
    assert gap_regime(0.7, "normal") == "medium gap"
    assert gap_regime(1.2, "normal") == "large gap"
    assert gap_regime(0.7, "opening gap reversal") == "gap reversal"
    assert gap_regime(0.7, "opening gap continuation") == "gap continuation"


def test_higher_timeframe_alignment_is_preserved():
    assert context_for_setup(_setup())["higher_timeframe_alignment"] == "aligned"
    assert (
        context_for_setup(_setup(higher_timeframe_alignment="opposed"))[
            "higher_timeframe_alignment"
        ]
        == "opposed"
    )


def test_minimum_sample_warning():
    metrics = selection_metrics(_rows().iloc[:1])
    assert evidence_label(metrics, DEFAULT_MINIMUM_SAMPLE) == "insufficient sample"


def test_shallow_tree_constraints():
    assert TREE_MAX_DEPTH <= 3
    assert TREE_MIN_LEAF_SIZE >= 5
    prior = []
    for index in range(12):
        prior.append(
            {
                **context_for_setup(_setup(symbol="QQQ" if index < 6 else "SPY")),
                "realized_return": 0.2 if index < 6 else -0.2,
            }
        )
    accepted, _, _, details = model_decision(
        "MODEL_H_SHALLOW_TREE", _frame(), _setup(), prior
    )
    assert accepted is True
    assert details["tree"]["depth"] <= TREE_MAX_DEPTH
    assert details["tree"]["minimum_leaf_size"] == TREE_MIN_LEAF_SIZE


def test_shadow_deterministic_duplicate_prevention(tmp_path):
    result = {
        "symbol": "QQQ",
        "signal": "BULLISH SETUP",
        "timestamp": "2026-07-27T10:30:00-04:00",
        "trade_plan": {
            "entry": 100,
            "stop": 99,
            "target_1": 101,
            "target_2": 102,
            "target_3": 103,
        },
    }
    first = shadow_record(result)
    second = shadow_record(deepcopy(result))
    assert first == second
    target = tmp_path / "shadow.jsonl"
    assert append_shadow_record(first, target)
    assert not append_shadow_record(second, target)
    assert len(target.read_text().splitlines()) == 1


def test_shadow_evaluator_isolation_and_no_production_writes(tmp_path):
    result = {
        "symbol": "QQQ",
        "signal": "BULLISH SETUP",
        "timestamp": "2026-07-27T10:30:00-04:00",
        "trade_plan": {"entry": 100, "stop": 99, "target_1": 101},
    }
    original = deepcopy(result)
    target = tmp_path / "experiment.jsonl"
    returned = record_live_shadow(result, None, None, target)
    assert returned is result
    assert result == original
    assert target.exists()
    assert not (tmp_path / "signal_history.jsonl").exists()
    assert not (tmp_path / "paper_option_positions.json").exists()


def test_live_scanner_shadow_failure_does_not_change_production(monkeypatch):
    frame = _frame()
    monkeypatch.setattr(optionbeacon_live, "get_data", lambda symbol: frame.copy())
    monkeypatch.setattr(optionbeacon_live, "add_indicators", lambda value: value)
    result = {
        "symbol": "QQQ",
        "signal": "NEUTRAL",
        "price": 100,
        "trade_plan": None,
    }
    monkeypatch.setattr(optionbeacon_live, "score_candle", lambda *args, **kwargs: dict(result))
    monkeypatch.setattr(optionbeacon_live, "enrich_with_trade_plan", lambda value: value)
    monkeypatch.setattr(optionbeacon_live, "enrich_with_option_liquidity", lambda value: value)
    monkeypatch.setattr(optionbeacon_live, "process_scanner_trade_plan", lambda value: None)
    monkeypatch.setattr(optionbeacon_live, "update_trade_outcomes_from_result", lambda value: None)
    monkeypatch.setattr(optionbeacon_live, "record_scanner_result", lambda value: None)
    import regime_selection_experiment

    monkeypatch.setattr(
        regime_selection_experiment,
        "record_live_shadow",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("read only")),
    )
    output = optionbeacon_live.generate_signal("QQQ")
    assert output["symbol"] == "QQQ"
    assert output["signal"] == "NEUTRAL"


def test_shadow_record_contains_required_context_and_plan():
    record = shadow_record(
        {
            "symbol": "SPY",
            "signal": "BEARISH SETUP",
            "timestamp": "2026-07-27T13:00:00-04:00",
            "trade_plan": {
                "entry": 600,
                "stop": 601,
                "target_1": 599,
                "target_2": 598,
                "target_3": 597,
                "risk_reward": 2,
            },
        }
    )
    assert record["eligible"] is True
    assert record["direction"] == "bearish"
    assert record["time_window"] == "13:00-14:00"
    assert record["selected_model"] == "MODEL_G_SIMPLE_GATES"
    assert record["theoretical_targets"] == [599, 598, 597]
    assert json.dumps(record)
