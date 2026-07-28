from trade_desk_view_models import UNAVAILABLE, opportunity_entry_presentation
from trade_evidence import actionable_trade_plan, scanner_entry_eligibility


def result(**overrides):
    value = {
        "symbol": "TSLA",
        "bias": "Bullish",
        "confidence": 80,
        "setup_stage": "Armed",
        "entry_timing": "Watch closely",
        "trade_plan": {
            "direction": "Bullish",
            "setup_type": "Breakout",
            "trigger_price": 100,
            "technical_stop": 95,
            "target_1": 105,
        },
    }
    value.update(overrides)
    return value


def test_confidence_below_entry_threshold_is_not_actionable():
    assert actionable_trade_plan(result(confidence=45)) is False


def test_timing_too_early_is_not_actionable():
    assert actionable_trade_plan(result(entry_timing="Too early")) is False


def test_watch_only_candidate_is_not_actionable():
    assert actionable_trade_plan(result(watch_only=True)) is False


def test_eligible_untriggered_waits_and_never_holds():
    presentation = opportunity_entry_presentation(
        scanner_entry_eligibility(result()),
        is_open=False,
    )
    assert presentation["eligibility"] == "QUALIFIED"
    assert presentation["entry_status"] == "WAITING FOR TRIGGER"
    assert presentation["suggested_action"] == "WAIT FOR ENTRY"
    assert presentation["coach_status"] == UNAVAILABLE
    assert "HOLD" not in presentation.values()


def test_open_entered_trade_may_show_hold():
    presentation = opportunity_entry_presentation(
        scanner_entry_eligibility(result()),
        is_open=True,
        coach={"status": "HOLD", "action": "Continue holding"},
    )
    assert presentation["entry_status"] == "OPEN"
    assert presentation["coach_status"] == "HOLD"
    assert presentation["suggested_action"] == "Continue holding"


def test_developing_setup_is_not_eligible_or_actionable_styled():
    presentation = opportunity_entry_presentation(
        scanner_entry_eligibility(result(confidence=45)),
        is_open=False,
    )
    assert presentation["eligibility"] == "NOT ELIGIBLE"
    assert presentation["suggested_action"] == "WATCH — NOT ELIGIBLE"
    assert presentation["treatment"] == "neutral"
    assert presentation["coach_status"] == UNAVAILABLE


def test_eligibility_reasons_include_confidence_and_timing():
    eligibility = scanner_entry_eligibility(
        result(confidence=45, entry_timing="Too early")
    )
    assert eligibility["reasons"] == [
        "Confidence 45% is below the 65% entry requirement.",
        "Timing is too early.",
    ]


def test_no_match_history_does_not_reject_candidate():
    candidate = result()
    candidate["historical_grade"] = "NO MATCH"
    assert scanner_entry_eligibility(candidate)["eligible"] is True


def test_incomplete_plan_is_not_actionable():
    candidate = result()
    candidate["trade_plan"] = {
        "direction": "Bullish",
        "trigger_price": 100,
    }
    eligibility = scanner_entry_eligibility(candidate)
    assert eligibility["eligible"] is False
    assert "Entry plan is incomplete." in eligibility["reasons"]


def test_closed_trade_is_not_actionable():
    assert actionable_trade_plan(
        result(entry_time="2026-07-28T10:00:00", exit_time="2026-07-28T10:30:00")
    ) is False
