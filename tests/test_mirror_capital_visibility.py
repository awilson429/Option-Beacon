import inspect
from datetime import date, datetime, timedelta, timezone

import app

from mirror_execution import mirror_capital_summary
from trade_desk_comparison import comparison_markup, trade_comparison_model


NOW = datetime(2026, 8, 6, 14, 0, tzinfo=timezone.utc)


def position(identity, debit, *, opened=NOW, closed=None, status="OPEN", quantity=1,
             realized=None, unrealized=0):
    return {
        "opportunity_id": identity, "entry_event_at": opened,
        "opened_at": opened, "exit_quote_at": closed, "status": status,
        "quantity": quantity, "total_debit": debit,
        "realized_pnl": realized, "unrealized_pnl": unrealized,
    }


def test_zero_open_positions_has_known_zero_current_deployment():
    summary = mirror_capital_summary([])
    assert summary["current_capital_required"] == 0
    assert summary["open_contracts"] == 0
    assert summary["peak_capital_required"] == 0
    assert summary["cumulative_gross_debit"] == 0


def test_one_and_multiple_open_positions_sum_persisted_initial_debits():
    one = mirror_capital_summary([position("a", 200)])
    assert one["current_capital_required"] == 200
    assert one["open_contracts"] == 1
    multiple = mirror_capital_summary([
        position("a", 200), position("b", 250, quantity=2),
    ])
    assert multiple["current_capital_required"] == 450
    assert multiple["open_contracts"] == 3


def test_closed_positions_leave_current_but_preserve_peak_and_cumulative_debit():
    rows = [
        position("a", 200, closed=NOW + timedelta(minutes=30), status="CLOSED", realized=20),
        position("b", 250, opened=NOW + timedelta(minutes=20),
                 closed=NOW + timedelta(minutes=40), status="CLOSED", realized=30),
    ]
    summary = mirror_capital_summary(rows)
    assert summary["current_capital_required"] == 0
    assert summary["peak_capital_required"] == 450
    assert summary["cumulative_gross_debit"] == 450
    assert summary["open_contracts"] == 0
    assert summary["return_on_peak_capital_percent"] == 50 / 450 * 100


def test_cumulative_turnover_is_distinct_from_nonoverlapping_peak():
    rows = [
        position("a", 200, closed=NOW + timedelta(minutes=10), status="CLOSED", realized=10),
        position("b", 250, opened=NOW + timedelta(minutes=20), status="OPEN", unrealized=5),
    ]
    summary = mirror_capital_summary(rows)
    assert summary["current_capital_required"] == 250
    assert summary["peak_capital_required"] == 250
    assert summary["cumulative_gross_debit"] == 450


def test_missing_persisted_values_remain_unknown_instead_of_fabricated_zero():
    missing_debit = position("unknown", None)
    summary = mirror_capital_summary([missing_debit])
    assert summary["current_capital_required"] is None
    assert summary["peak_capital_required"] is None
    assert summary["cumulative_gross_debit"] is None
    assert summary["return_on_peak_capital_percent"] is None


def test_trade_desk_primary_card_hides_control_capital_but_model_preserves_it():
    rows = [position("a", 200, unrealized=20)]
    model = trade_comparison_model(
        [], [], [], [], session_date=date(2026, 8, 6), mirror_rows=rows,
        mirror_runtime={"enabled": 1, "status": "ACTIVE", "experiment_start_date": "2026-08-06"},
    )
    markup = comparison_markup(model)
    assert "MIRROR CAPITAL DEPLOYED" not in markup
    assert model["mirror"]["capital_limit"] is None


def test_unknown_capital_renders_honestly_and_streamlit_stays_read_only():
    rows = [position("unknown", None)]
    model = trade_comparison_model(
        [], [], [], [], session_date=date(2026, 8, 6), mirror_rows=rows,
        mirror_runtime={"enabled": 1, "status": "ACTIVE", "experiment_start_date": "2026-08-06"},
    )
    markup = comparison_markup(model)
    assert "MIRROR CAPITAL DEPLOYED" not in markup
    source = inspect.getsource(app.render_outcome_trade_journal)
    for forbidden in ("run_mirror_execution", "record_disposition", "update_mark", "save_runtime_state"):
        assert forbidden not in source
