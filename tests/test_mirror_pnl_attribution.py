from datetime import date

import pytest

from analysis.mirror_pnl_attribution import build_session_audit


def test_exact_join_and_attribution_calculations_preserve_unknowns():
    events = [
        {"id": "e1", "opportunity_id": "a", "event_type": "TRADE_ENTERED", "event_timestamp": "2026-08-06T14:00:00Z", "symbol": "SPY", "direction": "Bullish", "underlying_price": 100},
        {"id": "x1", "opportunity_id": "a", "event_type": "TRADE_CLOSED", "event_timestamp": "2026-08-06T15:00:00Z", "symbol": "SPY", "realized_return": 1, "exit_price": 101, "exit_reason": "TARGET"},
        {"id": "e2", "opportunity_id": "b", "event_type": "TRADE_ENTERED", "event_timestamp": "2026-08-06T14:30:00Z", "symbol": "QQQ", "direction": "Bearish", "underlying_price": 100},
        {"id": "x2", "opportunity_id": "b", "event_type": "TRADE_CLOSED", "event_timestamp": "2026-08-06T15:30:00Z", "symbol": "QQQ", "realized_return": -1},
    ]
    mirror = [
        {"mirror_trade_id": "m1", "opportunity_id": "a", "option_type": "call", "strike": 99, "quantity": 1, "contract_multiplier": 100, "entry_mid": 2, "entry_fill": 2.05, "exit_mid": 2.30, "exit_fill": 2.25, "total_debit": 205, "realized_pnl": 20, "realized_return_percent": 20 / 205 * 100, "opened_at": "2026-08-06T14:00:00Z", "exit_quote_at": "2026-08-06T15:00:00Z"},
        {"mirror_trade_id": "m2", "opportunity_id": "b", "option_type": "put", "strike": 98, "quantity": 1, "contract_multiplier": 100, "entry_mid": 1, "entry_fill": 1.10, "exit_mid": .85, "exit_fill": .80, "total_debit": 110, "realized_pnl": -30, "realized_return_percent": -30 / 110 * 100, "opened_at": "2026-08-06T14:30:00Z", "exit_quote_at": "2026-08-06T15:30:00Z"},
    ]
    audit = build_session_audit(events, [{"id": "a", "confidence": 80, "entry_reference": 100}], mirror, [{"trade_id": "p1", "source_signal_id": "a"}], [{"trade_id": "p1", "accepted": 0, "reason_code": "SCORE_TOO_LOW", "created_at": "2026-08-06T14:01:00Z", "metadata_json": "{}"}], session_date=date(2026, 8, 6))
    first, second = audit["trades"]
    assert first["option_pnl"] == 20 and second["option_pnl"] == -30
    assert first["moneyness_status"] == "ITM" and first["moneyness_dollars"] == 1
    assert second["moneyness_status"] == "OTM" and second["moneyness_dollars"] == -2
    assert first["entry_fill_penalty"] == pytest.approx(5)
    assert first["exit_fill_penalty"] == pytest.approx(5)
    assert first["total_fill_penalty"] == pytest.approx(10)
    assert first["broad_disposition"] == "REJECTED" and first["broad_reason"] == "SCORE_TOO_LOW"
    assert first["delta"] is None and first["mfe"] is None
    assert first["capital_share_percent"] == pytest.approx(205 / 315 * 100)
    summary = audit["summary"]
    assert summary["gross_profit"] == 20 and summary["gross_loss"] == -30
    assert summary["profit_factor"] == pytest.approx(2 / 3)
    assert summary["average_winner_dollars"] == 20
    assert summary["average_loser_dollars"] == -30
    assert summary["cumulative_gross_debit"] == 315
    assert summary["peak_simultaneous_debit"] == 315


def test_no_fuzzy_symbol_join_and_missing_quotes_do_not_become_zero():
    events = [{"opportunity_id": "exact", "event_type": "TRADE_ENTERED", "event_timestamp": "2026-08-06T14:00:00Z", "symbol": "SPY"}]
    audit = build_session_audit(events, [], [{"mirror_trade_id": "wrong", "opportunity_id": "other", "symbol": "SPY"}], [], [], session_date=date(2026, 8, 6))
    row = audit["trades"][0]
    assert row["mirror_trade_id"] is None
    assert row["debit"] is None
    assert row["total_fill_penalty"] is None
    assert audit["summary"]["total_identifiable_fill_penalty"] is None


def test_analysis_module_contains_no_provider_or_persistence_operations():
    source = open("analysis/mirror_pnl_attribution.py", encoding="utf-8").read().lower()
    for forbidden in ("requests.", "yfinance", "tradier", "finnhub", "insert ", "update ", "delete ", "create table", "commit("):
        assert forbidden not in source
    runner = open("analysis/run_mirror_pnl_attribution.py", encoding="utf-8").read().lower()
    assert "default_transaction_read_only=on" in runner
    assert "set_session(readonly=true" in runner
    assert "connection.rollback()" in runner
    for forbidden in ("insert ", "update ", "delete ", "create table", "commit("):
        assert forbidden not in runner
