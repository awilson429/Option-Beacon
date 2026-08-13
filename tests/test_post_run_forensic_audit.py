from datetime import date, datetime, timedelta, timezone
import inspect

import pytest

from analysis.run_post_run_forensic_audit import read_sessions, session_bounds
from post_run_forensic_audit import build_forensic_report, data_integrity, performance


NOW = datetime(2026, 8, 6, 13, 30, tzinfo=timezone.utc)


def fixture(count=12):
    snapshots, outcomes, mirrors, marks, paper, journal = [], [], [], [], [], []
    for index in range(count):
        identity, mirror_id, paper_id = f"a-{index}", f"m-{index}", f"p-{index}"
        entered = NOW + timedelta(minutes=index * 15)
        auth_return = .5 if index % 2 == 0 else -.4
        mirror_return = -10 if index % 3 == 0 else 15
        snapshots.append({"snapshot": {"opportunity_id": identity, "symbol": "SPY", "direction": "Bullish",
            "setup_type": "BREAKOUT", "entry_timestamp": entered.isoformat(), "session_segment": "OPEN",
            "features": {"relative_volume": 1.5, "rsi": 55}, "scoring": {"confidence": 75, "quality": 80},
            "market_regime": {"regime": "TREND"}}})
        outcomes.append({"outcome": {"opportunity_id": identity, "entered": True, "never_entered": False,
            "entry_timestamp": entered.isoformat(), "exit_timestamp": (entered + timedelta(minutes=10)).isoformat(),
            "entry_price": 100, "exit_price": 100 + auth_return, "realized_return": auth_return,
            "duration_minutes": 10}})
        mirrors.append({"mirror_trade_id": mirror_id, "opportunity_id": identity, "symbol": "SPY", "direction": "Bullish",
            "option_type": "CALL", "strike": 100, "dte": 2, "quantity": 1, "contract_multiplier": 100,
            "underlying_entry_price": 100, "entry_bid": .9, "entry_ask": 1.1, "entry_mid": 1, "entry_fill": 1.05,
            "spread_percent": 20, "total_debit": 105, "entry_event_at": entered,
            "opened_at": entered + timedelta(seconds=index * 12), "exit_quote_at": entered + timedelta(minutes=10),
            "status": "CLOSED", "exit_mid": 1, "exit_fill": .95,
            "realized_return_percent": mirror_return, "realized_pnl": mirror_return / 100 * 105})
        for minute, value in ((1, -5), (3, 20), (10, mirror_return)):
            marks.append({"mark_id": f"{mirror_id}-{minute}", "mirror_trade_id": mirror_id,
                "opportunity_id": identity, "observed_at": entered + timedelta(minutes=minute),
                "return_pct": value, "conservative_mark": 1.05 * (1 + value / 100),
                "unrealized_pnl": value / 100 * 105, "time_since_entry_seconds": minute * 60})
        paper.append({"trade_id": paper_id, "source_signal_id": identity})
        journal.append({"trade_id": paper_id, "accepted": index % 2 == 0,
                        "reason_code": "ACCEPTED" if index % 2 == 0 else "SCORE_TOO_LOW",
                        "created_at": entered.isoformat()})
    return snapshots, outcomes, mirrors, marks, paper, journal


def test_exact_identity_integrity_duplicates_orphans_and_incomplete_are_quantified():
    values = list(fixture(2))
    values[0].append(values[0][0])
    values[3].append({"mark_id": "orphan", "mirror_trade_id": "missing", "observed_at": NOW})
    integrity = data_integrity(*values)
    assert integrity["duplicate_source_identities"]["snapshots"] == {"a-0": 2}
    assert integrity["orphaned_records"]["marks_without_mirror_trade"] == ["missing"]
    assert integrity["classification"] == "ELIGIBLE FOR ANALYSIS"


def test_et_session_bounds_are_half_open_and_handle_dst():
    start, end = session_bounds(date(2026, 3, 8), date(2026, 3, 8))
    assert start.isoformat() == "2026-03-08T05:00:00+00:00"
    assert end.isoformat() == "2026-03-09T04:00:00+00:00"


def test_report_classifies_translation_broad_latency_mfe_and_giveback_without_future_data():
    report = build_forensic_report(*fixture())
    assert report["analysis_window"]["authoritative_opportunities"] == 12
    assert sum(row["n"] for row in report["translation_matrix"]) == 12
    assert {row["group"] for row in report["broad_selectivity"]} == {"ACCEPTED", "REJECTED"}
    assert {row["group"] for row in report["entry_timing"]} >= {"0-15 sec", "16-30 sec", ">120 sec"}
    excursions = report["mfe_mae_exit"]["loser_excursions"]
    assert excursions["profitable_first"]["20"]["n"] == excursions["losers_n"]
    assert excursions["average_giveback"] > 0
    assert report["counterfactual_exits"]["label"].startswith("HISTORICAL COUNTERFACTUAL")


def test_flat_noise_and_missing_values_are_not_coerced_to_zero():
    result = performance([{"r": None}, {"r": .05}, {"r": .2}, {"r": -.2}], return_key="r")
    assert result["decided_n"] == 3 and result["flat_noise"] == 1
    assert result["wins"] == result["losses"] == 1


def test_incomplete_telemetry_is_explicit_and_counterfactuals_use_ordered_open_marks_only():
    values = list(fixture(1))
    values[3] = []
    report = build_forensic_report(*values)
    assert report["analysis_window"]["adequate_mirror_telemetry"] == 0
    assert report["data_integrity"]["mirror_trades_without_telemetry"] == 1
    assert report["data_integrity"]["classification"] == "INSUFFICIENT / INCOMPLETE DATA"
    assert report["contract_selection"]["greeks_iv"].startswith("NOT PERSISTED")


def test_production_reader_is_read_only_projected_bounded_and_not_trade_desk_controlled():
    source = inspect.getsource(read_sessions).lower()
    assert "default_transaction_read_only=on" in source and "set_session(readonly=true" in source
    assert "select *" not in source and " limit %s" in source
    assert "start_date" in source and "end_date" in source
    assert "history" not in source and "dropdown" not in source
    for forbidden in ("insert ", "update ", "delete ", "commit(", "option_quote", "tradier"):
        assert forbidden not in source
