import json
import inspect
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import app

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


def mirror_row(identity, *, at=NOW, status="CLOSED", opened=True, pnl=25.0, code="MIRROR_CLOSED"):
    return {
        "opportunity_id": identity, "entry_event_at": at,
        "opened_at": at if opened else None, "status": status,
        "exit_quote_at": at + timedelta(minutes=30) if opened and status == "CLOSED" else None,
        "disposition_code": code,
        "realized_pnl": pnl if status == "CLOSED" else None,
        "unrealized_pnl": pnl if status != "CLOSED" and opened else None,
        "symbol": "ARKG", "expiration": "2026-08-07", "strike": 40,
        "option_type": "put", "option_symbol": "ARKG260807P00040000",
        "entry_bid": 1.10, "entry_ask": 1.30, "entry_mid": 1.20,
        "entry_fill": 1.25, "quantity": 1, "total_debit": 125,
        "current_mark": 1.40 if status != "CLOSED" else None,
        "exit_fill": 1.50 if status == "CLOSED" else None,
    }


def mirror_runtime(status="ACTIVE", *, enabled=1, start="2026-08-05"):
    return {"status": status, "enabled": enabled, "experiment_start_date": start}


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
        "accepted_position_missing": 0,
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


def test_three_equal_cards_include_persisted_mirror_metrics_and_status():
    model = trade_comparison_model(
        [
            event("win-opened", "TRADE_ENTERED", 1, "NVDA"),
            event("win-opened", "TRADE_CLOSED", 2, "NVDA", realized_return=.88),
            event("unexec", "TRADE_ENTERED", 3, "XLE"),
        ], [], [], [], session_date=NOW.astimezone().date(),
        mirror_rows=[
            mirror_row("win-opened", pnl=34.5),
            mirror_row("unexec", opened=False, status="UNEXECUTABLE", pnl=None, code="MIRROR_NO_VALID_CONTRACT"),
        ], mirror_runtime=mirror_runtime(),
    )
    assert model["mirror"] == {
        "available": True, "status": "ACTIVE", "evaluated": 2,
        "opened": 1, "unexecutable": 1, "pending": 0,
        "participation_rate": 50.0, "closed": 1,
        "wins": 1, "losses": 0, "pnl": 34.5,
        "current_capital_required": 0.0, "peak_capital_required": 125.0,
        "cumulative_gross_debit": 125.0, "open_contracts": 0,
        "return_on_peak_capital_percent": 27.6, "capital_limit": None,
    }
    markup = comparison_markup(model)
    assert "OptionBeacon vs PAPER vs MIRROR" in markup
    assert markup.count('class="ob-compare-column"') == 3
    assert "BROAD PAPER" in markup and "MIRROR · ACTIVE" in markup
    assert 'class="ob-experiment-summary"' in markup
    assert "PARTICIPATION" in markup and "OPTION P&amp;L" in markup
    assert "BROAD</small><strong>0 / 2" in markup
    assert "MIRROR</small><strong>1 / 2" in markup
    assert "BROAD</small><strong>$+0.00" in markup
    assert "MIRROR</small><strong>$+34.50" in markup
    for redundant in (
        "Authoritative Entries", "BROAD: Evaluated", "MIRROR: Evaluated",
        "Unexecutable", "Pending",
    ):
        assert redundant not in markup


def test_compact_experiment_summary_keeps_missing_values_honest_and_capital_visible():
    model = trade_comparison_model(
        [event("opened", "TRADE_ENTERED", 1, "ARKG")], [], [], [],
        session_date=NOW.astimezone().date(),
        mirror_rows=[mirror_row("opened", status="OPEN", pnl=None)],
        mirror_runtime=mirror_runtime(),
    )
    model["paper"]["pnl"] = None
    markup = comparison_markup(model, has_previous=True, selected="PREVIOUS")
    assert markup.count("—") >= 2
    assert "MIRROR CAPITAL DEPLOYED" in markup
    assert "Peak" in markup and "Cumulative gross debit" in markup
    assert "Open contracts" in markup and "Return on peak" in markup
    assert "No limit" in markup
    assert "desk_session=TODAY" in markup
    assert "desk_session=PREVIOUS" in markup
    assert 'class="ob-session-tab is-active" href="?page=trade-desk&amp;desk_session=PREVIOUS"' in markup


def test_mirror_today_and_previous_filter_by_entry_session():
    prior = NOW - timedelta(days=1)
    events = [event("today", "TRADE_ENTERED", 0, "SPY"),
              {**event("prior", "TRADE_ENTERED", 0, "QQQ"), "event_timestamp": prior}]
    rows = [mirror_row("today"), mirror_row("prior", at=prior, pnl=-12)]
    today = trade_comparison_model(events, [], [], [], session_date=NOW.astimezone().date(),
                                   mirror_rows=rows, mirror_runtime=mirror_runtime(start="2026-08-04"))
    previous = trade_comparison_model(events, [], [], [], session_date=prior.astimezone().date(),
                                      mirror_rows=rows, mirror_runtime=mirror_runtime(start="2026-08-04"))
    assert today["mirror"]["opened"] == 1 and today["mirror"]["pnl"] == 25
    assert previous["mirror"]["opened"] == 1 and previous["mirror"]["pnl"] == -12


def test_mirror_session_membership_uses_exact_authoritative_id_not_row_timestamp():
    events = [event("exact", "TRADE_ENTERED", 0, "SPY")]
    model = trade_comparison_model(
        events, [], [], [], session_date=NOW.astimezone().date(),
        mirror_rows=[mirror_row("exact", at=NOW + timedelta(days=1)), mirror_row("unrelated")],
        mirror_runtime=mirror_runtime(),
    )
    assert model["mirror"]["evaluated"] == 1
    assert model["mirror"]["opened"] == 1
    assert model["rows"][0]["mirror_disposition"] == "OPENED"


def test_pre_experiment_session_is_not_interpreted_as_zero_performance():
    prior = NOW - timedelta(days=1)
    events = [{**event("prior", "TRADE_ENTERED", 0, "QQQ"), "event_timestamp": prior}]
    model = trade_comparison_model(events, [], [], [], session_date=prior.astimezone().date(),
                                   mirror_rows=[], mirror_runtime=mirror_runtime(start="2026-08-05"))
    assert model["mirror"]["available"] is False
    assert model["rows"][0]["mirror_disposition"] == "NO MIRROR DATA"
    markup = comparison_markup(model, selected="PREVIOUS")
    assert "MIRROR</small><strong>—" in markup
    assert "MIRROR</small><strong>$" not in markup


@pytest.mark.parametrize("runtime,label", [
    (mirror_runtime("ACTIVE"), "MIRROR · ACTIVE"),
    (mirror_runtime("WAITING"), "MIRROR · WAITING"),
    (mirror_runtime("DEGRADED"), "MIRROR · DEGRADED"),
    (mirror_runtime("ACTIVE", enabled=0), "MIRROR · DISABLED"),
    (None, "MIRROR · WAITING"),
])
def test_mirror_status_rendering(runtime, label):
    model = trade_comparison_model([], [], [], [], session_date=NOW.astimezone().date(),
                                   mirror_rows=[], mirror_runtime=runtime)
    assert label in comparison_markup(model)


def test_exact_id_join_only_and_trade_table_has_three_system_units():
    events = [event("auth-id", "TRADE_ENTERED", 1, "SPY"),
              event("auth-id", "TRADE_CLOSED", 2, "SPY", realized_return=.42)]
    model = trade_comparison_model(
        events, [], [], [], session_date=NOW.astimezone().date(),
        mirror_rows=[mirror_row("different-id", pnl=99)], mirror_runtime=mirror_runtime(),
    )
    row = model["rows"][0]
    assert row["mirror_disposition"] == "NOT RECORDED" and row["mirror_pnl"] is None
    markup = authoritative_trades_markup(model)
    assert "AUTH RETURN" in markup
    assert "BROAD PAPER OPTION P&L" in markup and "MIRROR OPTION P&L" in markup


def test_opened_mirror_uses_persisted_contract_and_quote_fields_in_trade_table():
    events = [event("opened", "TRADE_ENTERED", 1, "ARKG")]
    persisted = mirror_row("opened", status="OPEN", pnl=15)
    model = trade_comparison_model(
        events, [], [], [], session_date=NOW.astimezone().date(),
        mirror_rows=[persisted], mirror_runtime=mirror_runtime(),
    )
    row = model["rows"][0]
    assert row["mirror_contract"] == "ARKG 08/07/26 $40 PUT"
    assert row["mirror_entry"] == 1.25
    assert row["mirror_option_price"] == 1.40
    assert "ARKG260807P00040000" in row["mirror_contract_details"]
    assert "Entry bid: $1.10" in row["mirror_contract_details"]
    assert "Current mark: $1.40" in row["mirror_contract_details"]
    markup = authoritative_trades_markup(model)
    assert "MIRROR CONTRACT" in markup and "MIRROR ENTRY" in markup
    assert "ARKG 08/07/26 $40 PUT" in markup
    assert "Contract details" in markup and "ARKG260807P00040000" in markup


def test_closed_mirror_shows_persisted_exit_fill_and_unopened_has_no_contract():
    events = [event("closed", "TRADE_ENTERED", 1, "ARKG"), event("unexec", "TRADE_ENTERED", 2, "XLE")]
    model = trade_comparison_model(
        events, [], [], [], session_date=NOW.astimezone().date(),
        mirror_rows=[
            mirror_row("closed", status="CLOSED", pnl=25),
            mirror_row("unexec", opened=False, status="UNEXECUTABLE", pnl=None, code="MIRROR_NO_VALID_CONTRACT"),
        ], mirror_runtime=mirror_runtime(),
    )
    rows = {row["authoritative_id"]: row for row in model["rows"]}
    assert rows["closed"]["mirror_option_price"] == 1.50
    assert "Exit fill: $1.50" in rows["closed"]["mirror_contract_details"]
    assert rows["unexec"]["mirror_contract"] == "—"
    assert rows["unexec"]["mirror_entry"] is None
    assert rows["unexec"]["mirror_contract_details"] is None


def test_responsive_three_card_css_and_streamlit_remains_read_only():
    css = open("ui/theme.py", encoding="utf-8").read()
    assert "grid-template-columns:repeat(3,minmax(0,1fr))" in css
    assert ".ob-compare-grid {grid-template-columns:minmax(0,1fr)}" in css
    assert ".ob-experiment-summary {grid-template-columns:minmax(0,1fr)}" in css
    experiment_css = css[css.index(".ob-experiment-summary"):css.index(".ob-auth-summary")]
    assert "overflow-x" not in experiment_css
    source = inspect.getsource(app.render_outcome_trade_journal)
    assert "MirrorExecutionRepository" in source
    for forbidden in ("run_mirror_execution", "save_runtime_state", "record_disposition", ".close(", ".update_mark("):
        assert forbidden not in source
