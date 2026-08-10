import inspect
import json
import math
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import app
from broad_filter_effectiveness import (
    MIN_CLASSIFICATION_SAMPLE,
    broad_filter_effectiveness,
    effectiveness_label,
)


NOW = datetime(2026, 8, 7, 16, tzinfo=timezone.utc)


def event(identity, kind, *, days=0, auth_return=None):
    row = {
        "id": f"event-{identity}-{kind}", "opportunity_id": identity,
        "trade_id": f"auth-{identity}", "event_type": kind,
        "event_timestamp": NOW - timedelta(days=days), "symbol": identity.upper(),
        "direction": "Bullish",
    }
    if auth_return is not None:
        row["realized_return"] = auth_return
    return row


def capture(identity):
    return SimpleNamespace(trade_id=f"paper-{identity}", source_signal_id=identity)


def decision(identity, reason, accepted=False):
    return {
        "trade_id": f"paper-{identity}", "accepted": int(accepted), "reason_code": reason,
        "created_at": NOW, "metadata_json": json.dumps({"journal_type": "ENTRY_DECISION"}),
    }


def mirror(identity, pnl, *, opened_at=None, closed_at=None):
    opened_at = opened_at or NOW
    closed_at = closed_at or NOW + timedelta(hours=1)
    final_return = pnl / 110 * 100
    return {
        "mirror_trade_id": f"mirror-{identity}", "opportunity_id": identity,
        "symbol": identity.upper(), "direction": "Bullish", "option_symbol": f"{identity}-OCC",
        "opened_at": opened_at, "exit_quote_at": closed_at, "updated_at": closed_at,
        "status": "CLOSED", "entry_mid": 1.0, "entry_fill": 1.1,
        "exit_mid": 1.5, "exit_fill": 1.1 + pnl / 100, "realized_pnl": pnl,
        "realized_return_percent": final_return, "quantity": 1, "contract_multiplier": 100,
        "total_debit": 110, "spread_percent": 10, "entry_bid": .95, "entry_ask": 1.05,
        "exit_bid": 1.4, "exit_ask": 1.6, "dte": 7, "strike": 100,
        "underlying_entry_price": 102, "open_interest": 200, "option_volume": 50,
        "metadata_json": "{}",
    }


def mark(identity, return_pct, *, mfe=None, mae=None):
    return {
        "mirror_trade_id": f"mirror-{identity}", "return_pct": return_pct,
        "mfe_pct": return_pct if mfe is None else mfe,
        "mae_pct": return_pct if mae is None else mae,
        "peak_return_pct": return_pct if mfe is None else mfe,
    }


def model(*, include_old=False):
    specs = [
        ("score", "SCORE_TOO_LOW", 40, 1.0),
        ("spread", "SPREAD_TOO_WIDE", -30, -1.0),
        ("expensive", "CONTRACT_TOO_EXPENSIVE", 10, 0.5),
        ("opened", "ELIGIBLE", 25, 0.8),
    ]
    events, captures, decisions, mirrors, marks = [], [], [], [], []
    for identity, reason, pnl, auth_return in specs:
        events += [event(identity, "TRADE_ENTERED"), event(identity, "TRADE_CLOSED", auth_return=auth_return)]
        captures.append(capture(identity))
        decisions.append(decision(identity, reason, accepted=reason == "ELIGIBLE"))
        mirrors.append(mirror(identity, pnl))
        marks += [mark(identity, -10, mfe=-10, mae=-10), mark(identity, 30, mfe=30, mae=-10)]
    if include_old:
        events += [event("old", "TRADE_ENTERED", days=10), event("old", "TRADE_CLOSED", days=10, auth_return=2)]
        captures.append(capture("old")); decisions.append(decision("old", "SCORE_TOO_LOW"))
        mirrors.append(mirror("old", 999, opened_at=NOW - timedelta(days=10), closed_at=NOW - timedelta(days=10, hours=-1)))
    return broad_filter_effectiveness(
        events, decisions, captures, mirrors, marks,
        {"experiment_start_date": "2026-08-01"}, now=NOW,
    )


def groups(result):
    return {row["reason"]: row for row in result["groups"]}


def test_exact_id_join_and_named_rejection_group_aggregation():
    result = model()
    by_reason = groups(result)
    assert set(by_reason) == {"SCORE_TOO_LOW", "SPREAD_TOO_WIDE", "CONTRACT_TOO_EXPENSIVE", "BROAD OPENED"}
    assert by_reason["SCORE_TOO_LOW"]["net_pnl"] == 40
    assert by_reason["SPREAD_TOO_WIDE"]["mirror_losses"] == 1
    assert by_reason["CONTRACT_TOO_EXPENSIVE"]["mirror_wins"] == 1
    assert {trade["opportunity_id"] for trade in by_reason["SCORE_TOO_LOW"]["trades"]} == {"score"}
    unmatched = broad_filter_effectiveness(
        [event("unmatched", "TRADE_ENTERED")], [], [],
        [mirror("unmatched", 999)], [], {"experiment_start_date": "2026-08-01"}, now=NOW)
    assert unmatched["groups"] == [] and unmatched["trades"] == []


def test_accepted_rejected_missed_winner_and_avoided_loser():
    result = model()
    comparison = {row["reason"]: row for row in result["comparison"]}
    assert comparison["BROAD OPENED"]["net_pnl"] == 25
    assert comparison["BROAD REJECTED"]["net_pnl"] == 20
    score = groups(result)["SCORE_TOO_LOW"]
    spread = groups(result)["SPREAD_TOO_WIDE"]
    assert score["authoritative_winners_rejected"] == 1
    assert score["rejected_auth_winner_mirror_wins"] == 1
    assert spread["authoritative_losers_rejected"] == 1
    assert spread["rejected_auth_loser_mirror_losses"] == 1
    assert spread["rejected_auth_loser_net_pnl"] == -30


def test_profit_factor_fill_drag_and_contract_quality_use_persisted_values():
    rejected = {row["reason"]: row for row in model()["comparison"]}["BROAD REJECTED"]
    assert rejected["profit_factor"] == pytest.approx(50 / 30)
    assert rejected["midpoint_pnl"] == 150
    assert rejected["total_fill_drag"] == 130
    assert rejected["average_entry_spread_percent"] == 10
    assert rejected["average_exit_spread_percent"] == pytest.approx(200 / 15)
    assert rejected["average_dte"] == 7
    assert rejected["average_moneyness_percent"] == pytest.approx((100 / 102 - 1) * 100)
    assert rejected["delta_coverage"] == 0 and rejected["iv_coverage"] == 0


def test_mfe_mae_giveback_and_profitable_to_loser_reversal():
    spread = groups(model())["SPREAD_TOO_WIDE"]
    assert spread["average_mfe"] == 30
    assert spread["average_mae"] == -10
    assert spread["average_peak_return"] == 30
    assert spread["ever_profitable_count"] == 1
    assert spread["profitable_to_final_loser_count"] == 1
    assert spread["average_giveback"] == pytest.approx(30 - (-30 / 110 * 100))


def test_peak_capital_is_distinct_from_cumulative_debit():
    result = model()
    rejected = {row["reason"]: row for row in result["comparison"]}["BROAD REJECTED"]
    assert rejected["cumulative_debit"] == 330
    assert rejected["peak_capital"] == 330  # all three overlap
    sequential = [mirror("a", 1, opened_at=NOW, closed_at=NOW + timedelta(minutes=5)),
                  mirror("b", 1, opened_at=NOW + timedelta(minutes=10), closed_at=NOW + timedelta(minutes=15))]
    events = [event(x, kind) for x in ("a", "b") for kind in ("TRADE_ENTERED", "TRADE_CLOSED")]
    value = broad_filter_effectiveness(events, [decision("a", "SCORE_TOO_LOW"), decision("b", "SCORE_TOO_LOW")],
        [capture("a"), capture("b")], sequential, [], {"experiment_start_date": "2026-08-01"}, now=NOW)
    group = groups(value)["SCORE_TOO_LOW"]
    assert group["peak_capital"] == 110 and group["cumulative_debit"] == 220


def test_classification_thresholds_are_conservative_and_transparent():
    assert MIN_CLASSIFICATION_SAMPLE == 10
    assert effectiveness_label(realized_count=9, net_pnl=-1000, profit_factor=.1) == "INSUFFICIENT DATA"
    assert effectiveness_label(realized_count=10, net_pnl=-100, profit_factor=.5) == "PROTECTIVE"
    assert effectiveness_label(realized_count=10, net_pnl=100, profit_factor=2) == "COSTLY FILTER"
    assert effectiveness_label(realized_count=10, net_pnl=1, profit_factor=1.01) == "NEUTRAL / INCONCLUSIVE"


def test_missing_telemetry_and_pre_experiment_rows_are_not_inferred():
    result = model(include_old=True)
    assert "old" not in {trade["opportunity_id"] for trade in result["trades"]}
    value = broad_filter_effectiveness(
        [event("score", "TRADE_ENTERED"), event("score", "TRADE_CLOSED", auth_return=1)],
        [decision("score", "SCORE_TOO_LOW")], [capture("score")], [mirror("score", 5)], [],
        {"experiment_start_date": "2026-08-01"}, now=NOW)
    score = groups(value)["SCORE_TOO_LOW"]
    assert score["telemetry_coverage"] == 0
    assert score["average_mfe"] is None and score["average_mae"] is None


def test_today_previous_and_rolling_session_windows_use_persisted_sessions():
    events, captures, decisions, mirrors = [], [], [], []
    for days in range(6):
        identity = f"day-{days}"
        events += [event(identity, "TRADE_ENTERED", days=days),
                   event(identity, "TRADE_CLOSED", days=days, auth_return=1)]
        captures.append(capture(identity)); decisions.append(decision(identity, "SCORE_TOO_LOW"))
        mirrors.append(mirror(identity, 1, opened_at=NOW - timedelta(days=days),
                              closed_at=NOW - timedelta(days=days) + timedelta(hours=1)))
    common = (events, decisions, captures, mirrors, [], {"experiment_start_date": "2026-08-01"})
    today = broad_filter_effectiveness(*common, window="TODAY", now=NOW)
    previous = broad_filter_effectiveness(*common, window="PREVIOUS SESSION", now=NOW)
    rolling = broad_filter_effectiveness(*common, window="LAST 5 SESSIONS", now=NOW)
    assert {trade["opportunity_id"] for trade in today["trades"]} == {"day-0"}
    assert {trade["opportunity_id"] for trade in previous["trades"]} == {"day-1"}
    assert len(rolling["sessions"]) == 5 and len(rolling["trades"]) == 5


def test_analytics_and_streamlit_are_read_only_and_have_no_provider_calls():
    analytics_source = inspect.getsource(broad_filter_effectiveness)
    ui_source = inspect.getsource(app.render_paper_trading_page)
    for forbidden in ("provider", "option_quote", "record_disposition", "update_mark", "run_mirror_execution"):
        assert forbidden not in analytics_source
    for forbidden in ("record_disposition(", "update_mark(", "run_mirror_execution(", ".save("):
        assert forbidden not in ui_source
    assert "mirror_repository.mark_summaries(" in ui_source
    assert "mirror_repository.marks()" not in ui_source
    assert "BROAD FILTER EFFECTIVENESS" in ui_source
