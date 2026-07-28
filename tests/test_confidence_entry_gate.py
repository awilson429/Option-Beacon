from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from signal_history import (
    DEFAULT_MIN_ENTRY_CONFIDENCE,
    entry_confidence_eligible,
    expire_trade_outcome,
    load_trade_outcomes,
    rewrite_trade_outcomes,
    scanner_result_to_trade_outcome,
    update_trade_outcome,
    update_trade_outcomes_from_result,
)
from trade_journal_dashboard import (
    entry_eligibility_label,
    trade_outcome_status,
)


SIGNAL_TIME = datetime(2026, 7, 28, 14, 0, tzinfo=timezone.utc)
UPDATE_TIME = SIGNAL_TIME + timedelta(minutes=5)


def scanner_result(confidence=84, direction="Bullish"):
    bearish = direction == "Bearish"
    return {
        "symbol": "SPY",
        "bias": direction,
        "confidence": confidence,
        "timestamp": SIGNAL_TIME.isoformat(),
        "setup_stage": "Armed",
        "entry_timing": "Watch closely",
        "trade_plan": {
            "direction": direction,
            "setup_type": "Bearish breakdown" if bearish else "Bullish breakout",
            "trigger_price": 100,
            "technical_stop": 105 if bearish else 95,
            "target_1": 97 if bearish else 103,
            "target_2": 94 if bearish else 106,
            "target_3": 91 if bearish else 109,
        },
    }


def candidate(confidence=84, direction="Bullish"):
    record = scanner_result_to_trade_outcome(
        scanner_result(confidence, direction)
    )
    assert record is not None
    return record


@pytest.mark.parametrize("confidence", [43, 64.99])
def test_below_threshold_price_cross_remains_candidate(confidence):
    record = candidate(confidence)

    update_trade_outcome(record, 101, UPDATE_TIME)

    assert record.entry_time is None
    assert record.exit_time is None
    assert trade_outcome_status(record) == "CANDIDATE"


@pytest.mark.parametrize("confidence", [65, 66])
def test_at_or_above_threshold_price_cross_enters(confidence):
    record = candidate(confidence)

    update_trade_outcome(record, 100, UPDATE_TIME)

    assert record.entry_time == UPDATE_TIME


def test_bullish_entry_still_requires_price_cross():
    record = candidate(80, "Bullish")

    update_trade_outcome(record, 99.99, UPDATE_TIME)

    assert record.entry_time is None


def test_bearish_entry_uses_directional_price_cross():
    above_entry = candidate(80, "Bearish")
    at_entry = candidate(80, "Bearish")

    update_trade_outcome(above_entry, 100.01, UPDATE_TIME)
    update_trade_outcome(at_entry, 100, UPDATE_TIME)

    assert above_entry.entry_time is None
    assert at_entry.entry_time == UPDATE_TIME


@pytest.mark.parametrize(
    "confidence",
    ["malformed", None, float("nan"), float("inf"), float("-inf")],
)
def test_non_finite_or_malformed_confidence_never_enters(confidence):
    record = candidate()
    record.confidence = confidence

    update_trade_outcome(record, 101, UPDATE_TIME)

    assert entry_confidence_eligible(record) is False
    assert record.entry_time is None


def test_custom_threshold_works():
    record = candidate(70)

    update_trade_outcome(
        record,
        101,
        UPDATE_TIME,
        minimum_entry_confidence=75,
    )

    assert record.entry_time is None


def test_shared_result_updater_passes_custom_threshold(tmp_path):
    history_file = tmp_path / "signal_history.jsonl"
    rewrite_trade_outcomes([candidate(70)], history_file)

    updated = update_trade_outcomes_from_result(
        {
            "symbol": "SPY",
            "price": 101,
            "timestamp": UPDATE_TIME.isoformat(),
        },
        history_file,
        minimum_entry_confidence=70,
    )

    assert updated == 1
    assert load_trade_outcomes(history_file)[0].entry_time == UPDATE_TIME


def test_existing_entered_low_confidence_record_continues_updating():
    record = candidate(43)
    record.entry_time = SIGNAL_TIME

    update_trade_outcome(record, 102, UPDATE_TIME)

    assert record.entry_time == SIGNAL_TIME
    assert record.max_favorable_excursion == 2
    assert record.max_adverse_excursion == 0
    assert record.hold_minutes == 5


def test_low_confidence_candidate_expires_as_never_triggered():
    record = candidate(43)
    checked_at = SIGNAL_TIME + timedelta(minutes=60)

    update_trade_outcome(record, 101, SIGNAL_TIME + timedelta(minutes=59))
    expire_trade_outcome(record, 101, checked_at)

    assert record.entry_time is None
    assert record.exit_time == checked_at
    assert record.exit_reason == "NEVER_TRIGGERED"


def test_low_confidence_candidate_does_not_accumulate_excursions():
    record = candidate(43)

    update_trade_outcome(record, 104, UPDATE_TIME)

    assert record.max_favorable_excursion is None
    assert record.max_adverse_excursion is None
    assert record.realized_return is None
    assert record.hold_minutes is None


def test_closed_record_remains_unchanged():
    record = candidate(43)
    record.exit_time = UPDATE_TIME
    record.exit_reason = "NEVER_TRIGGERED"
    original = deepcopy(record)

    update_trade_outcome(record, 101, UPDATE_TIME + timedelta(minutes=5))

    assert record == original


def test_low_confidence_candidates_are_still_recorded():
    record = scanner_result_to_trade_outcome(scanner_result(43))

    assert record is not None
    assert record.confidence == 43
    assert record.entry_time is None


def test_journal_labels_low_confidence_candidate_watch_only():
    record = candidate(DEFAULT_MIN_ENTRY_CONFIDENCE - 1)

    assert (
        entry_eligibility_label(record)
        == "WATCH ONLY — BELOW ENTRY CONFIDENCE"
    )
