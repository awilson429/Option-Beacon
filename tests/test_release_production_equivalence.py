"""Release-candidate guards for unchanged production defaults."""

from pathlib import Path

from optionbeacon_strategy import (
    DEFAULT_CALL_SCORE_THRESHOLD,
    DEFAULT_PUT_SCORE_THRESHOLD,
)
from ui_modern_style import demo_scorecard_enabled, modern_style_active
from ui_navigation import CARD_NAVIGATION, active_card_workspace


def test_production_score_thresholds_remain_90():
    assert DEFAULT_CALL_SCORE_THRESHOLD == 90
    assert DEFAULT_PUT_SCORE_THRESHOLD == 90


def test_default_navigation_remains_trade_desk_with_paper_workspace():
    state = {}
    assert active_card_workspace(state) == "Trade Desk"
    assert CARD_NAVIGATION == (
        "Trade Desk",
        "SPY / QQQ",
        "Opportunities",
        "Paper Trading",
        "Strategy Lab",
        "Advanced",
    )


def test_modern_style_and_demo_data_are_disabled_by_default():
    assert modern_style_active({}, "develop") is False
    assert modern_style_active({"new_style": "1"}, "main") is False
    assert modern_style_active({"new_style": "1"}, "release/optimization-infrastructure") is False
    assert demo_scorecard_enabled({}, "develop") is False
    assert demo_scorecard_enabled({"demo_data": "1"}, "develop") is False


def test_experiment_modules_do_not_import_production_persistence_or_order_apis():
    for filename in (
        "false_breakout_experiment.py",
        "regime_selection_experiment.py",
        "signal_funnel_experiment.py",
    ):
        source = Path(filename).read_text(encoding="utf-8")
        for forbidden in (
            "record_scanner_result",
            "create_trade_record",
            "process_scanner_trade_plan",
            "paper_option_positions",
            "submit_order",
            "place_order",
            "buy_to_open",
            "sell_to_open",
        ):
            assert forbidden not in source


def test_shadow_hooks_run_after_production_processing_and_before_return():
    source = Path("optionbeacon_live.py").read_text(encoding="utf-8")
    process = source.index("process_scanner_trade_plan(result)")
    lifecycle = source.index("update_trade_outcomes_from_result(result)")
    journal = source.index("record_scanner_result(result)")
    first_shadow = source.index("from false_breakout_experiment import record_live_shadow")
    final_return = source.index("return result", first_shadow)
    assert process < lifecycle < journal < first_shadow < final_return
    assert source.count("except Exception as exc:") >= 3


def test_no_experimental_output_is_rendered_in_app():
    source = Path("app.py").read_text(encoding="utf-8")
    assert "experiment_001_shadow" not in source
    assert "experiment_002_shadow" not in source
    assert "experiment_003_signal_funnel" not in source
    assert "false_breakout_experiment" not in source
    assert "regime_selection_experiment" not in source
    assert "signal_funnel_experiment" not in source
