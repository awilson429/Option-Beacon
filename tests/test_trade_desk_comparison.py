import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from trade_desk_comparison import (
    authoritative_trades_markup,
    available_session_dates,
    comparison_markup,
    trade_comparison_model,
)


NOW = datetime(2026, 8, 5, 16, tzinfo=timezone.utc)


def event(identity, kind, seconds, symbol, **values):
    return {
        "id": f"event-{identity}-{kind}-{seconds}",
        "opportunity_id": identity,
        "trade_id": f"auth-{identity}",
        "event_type": kind,
        "event_timestamp": NOW + timedelta(seconds=seconds),
        "symbol": symbol,
        "direction": values.pop("direction", "Bullish"),
        **values,
    }


def capture(paper_id, source_id):
    return SimpleNamespace(trade_id=paper_id, source_signal_id=source_id)


def journal(paper_id, accepted, reason, seconds=10, **risk):
    return {
        "trade_id": paper_id,
        "accepted": int(accepted),
        "reason_code": reason,
        "created_at": NOW + timedelta(seconds=seconds),
        "metadata_json": json.dumps({
            "journal_type": "ENTRY_DECISION",
            "simulation_profile": "BROAD",
            "effective_min_score": 40,
        }),
        "risk_state_json": json.dumps(risk),
    }


def position(paper_id, *, pnl, status="CLOSED"):
    return SimpleNamespace(
        trade_id=paper_id, quantity=1, entry_mid=2.0,
        current_mid=2.0 + pnl / 100,
        exit_mid=2.0 + pnl / 100 if status == "CLOSED" else None,
        status=status,
    )


def sample_model():
    events = [
        event("win-opened", "TRADE_ENTERED", 1, "NVDA", underlying_price=181.42, rule_score=92),
        event("win-opened", "TRADE_CLOSED", 2, "NVDA", exit_price=183.01, realized_return=.88),
        event("win-rejected", "TRADE_ENTERED", 3, "XLE", underlying_price=88.61, rule_score=39, direction="Bearish"),
        event("win-rejected", "TRADE_CLOSED", 4, "XLE", exit_price=87.94, realized_return=.76, direction="Bearish"),
        event("loss-pending", "TRADE_ENTERED", 5, "BAC", underlying_price=47.18, rule_score=72),
        event("loss-pending", "TRADE_CLOSED", 6, "BAC", exit_price=46.99, realized_return=-.41),
        # Repeated persisted entry event must not duplicate a trade.
        event("win-opened", "TRADE_ENTERED", 7, "NVDA", underlying_price=181.42, rule_score=92),
    ]
    captures = [capture("paper-open", "win-opened"), capture("paper-reject", "win-rejected")]
    journals = [
        journal("paper-open", True, "ELIGIBLE", 11),
        journal("paper-reject", False, "SCORE_TOO_LOW", 12, open_positions=5, available_buying_power=125),
    ]
    positions = [position("paper-open", pnl=42.50)]
    return trade_comparison_model(
        events, journals, captures, positions, session_date=NOW.astimezone().date()
    )


def test_authoritative_daily_summary_and_paper_metrics_remain_separate():
    model = sample_model()
    assert model["authoritative"]["trades"] == 3
    assert model["authoritative"]["closed"] == 3
    assert model["authoritative"]["wins"] == 2
    assert model["authoritative"]["losses"] == 1
    assert model["authoritative"]["win_rate"] == pytest.approx(2 / 3 * 100)
    assert model["authoritative"]["average_return"] == pytest.approx((.88 + .76 - .41) / 3)
    assert {key: value for key, value in model["paper"].items() if key != "participation_rate"} == {
        "evaluated": 2, "opened": 1, "rejected": 1, "pending": 1,
        "closed": 1, "wins": 1, "losses": 0, "pnl": 42.5,
    }
    assert model["paper"]["participation_rate"] == pytest.approx(100 / 3)


def test_durable_ids_join_opened_rejected_pending_and_exact_reason():
    rows = {row["authoritative_id"]: row for row in sample_model()["rows"]}
    assert rows["win-opened"]["paper_disposition"] == "OPENED"
    assert rows["win-opened"]["paper_pnl"] == 42.5
    assert rows["win-rejected"]["paper_disposition"] == "REJECTED"
    assert rows["win-rejected"]["paper_reason"] == "SCORE_TOO_LOW"
    assert rows["loss-pending"]["paper_disposition"] == "PENDING"


def test_missed_winners_and_rejection_breakdown_reconcile():
    missed = sample_model()["missed_winners"]
    assert missed["count"] == 1
    assert missed["average_return"] == .76
    assert missed["rejection_counts"] == {"SCORE_TOO_LOW": 1}


def test_markup_labels_underlying_auth_return_and_paper_option_pnl_distinctly():
    model = sample_model()
    table = authoritative_trades_markup(model)
    summary = comparison_markup(model)
    assert "Today's OptionBeacon Trades" in table
    assert "AUTH RETURN" in table and "PAPER OPTION P&L" in table
    assert "SCORE_TOO_LOW" in table and "Why missed?" in table
    assert "OptionBeacon vs PAPER" in summary
    assert "MISSED AUTHORITATIVE WINNERS" in summary
    assert "Avg auth underlying return" in summary


def test_previous_session_is_available_only_from_persisted_authoritative_entries():
    prior = NOW - timedelta(days=1)
    events = [
        event("today", "TRADE_ENTERED", 0, "SPY"),
        {**event("prior", "TRADE_ENTERED", 0, "QQQ"), "event_timestamp": prior},
    ]
    sessions = available_session_dates(events, NOW)
    assert sessions["today"] == NOW.astimezone().date()
    assert sessions["previous"] == prior.astimezone().date()
    previous = trade_comparison_model(
        events, [], [], [], session_date=sessions["previous"]
    )
    assert [row["authoritative_id"] for row in previous["rows"]] == ["prior"]
    assert "Previous Session OptionBeacon Trades" in authoritative_trades_markup(
        previous, selected="PREVIOUS"
    )


def test_unproven_match_is_pending_instead_of_symbol_time_guessing():
    events = [event("auth-id", "TRADE_ENTERED", 1, "SPY", underlying_price=600)]
    unrelated = [capture("paper-id", "different-auth-id")]
    model = trade_comparison_model(
        events, [journal("paper-id", True, "ELIGIBLE")], unrelated, [],
        session_date=NOW.astimezone().date(),
    )
    assert model["rows"][0]["paper_disposition"] == "PENDING"
