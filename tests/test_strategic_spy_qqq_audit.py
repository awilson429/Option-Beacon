from strategic_spy_qqq_audit import build_strategic_audit, excursions, performance


def trade(identity, symbol, pnl, *, day="2026-08-17", spread=4, mfe=12, mae=-3):
    return {"trade_id": identity, "opportunity_id": f"o-{identity}", "symbol": symbol, "direction": "CALL",
        "setup": "VWAP_RECLAIM", "regime": "RISK_ON_TREND", "time_bucket": "10:00-11:30",
        "signal_at": f"{day}T14:00:00+00:00", "session": day, "opened_at": f"{day}T14:01:00+00:00",
        "closed_at": f"{day}T14:30:00+00:00", "pnl": pnl, "return_pct": pnl, "mfe": mfe, "mae": mae,
        "spread_percent": spread, "signal_age_seconds": 60, "signal_age_bucket": "LE_60", "entry_fill": 1,
        "debit": 100, "dte": 0, "option_volume": 1000, "open_interest": 2000, "fill_model": "TEST"}


def snapshot():
    spy = [trade(f"s{i}", "SPY", 5 if i % 2 == 0 else -2, day=f"2026-08-{17+i//2:02d}") for i in range(6)]
    qqq = [trade(f"q{i}", "QQQ", 3 if i % 3 else -4, day=f"2026-08-{17+i//2:02d}") for i in range(6)]
    broad = [trade(f"b{i}", "AAPL", -1 if i % 2 else 2) for i in range(6)]
    return {"metadata": {"database_fingerprint": "safe"}, "lanes": {"SPY": spy, "QQQ": qqq, "BROAD": broad,
        "MIRROR": broad, "FILTERED": broad}, "AUTHORITATIVE": [], "OPPORTUNITY_CONTEXT": [], "CONTEXT_SHADOW": [],
        "POSITION_CONTEXT": [], "DAILY_SCORECARD_ANALYTICS": broad, "underlying_records": {"intraday_trades": spy + qqq}}


def test_complete_actual_system_comparison_and_nested_records_preserved():
    report = build_strategic_audit(snapshot())
    assert set(report["performance"]) == {"BROAD", "MIRROR", "FILTERED", "SPY", "QQQ", "SPY_QQQ"}
    assert report["performance"]["SPY_QQQ"]["closed_trades"] == 12
    assert report["underlying_records"]["intraday_trades"][0]["trade_id"] == "s0"
    assert report["breakdowns"]["SPY"]["setup"][0]["group"] == "VWAP_RECLAIM"
    assert report["audit_metadata"]["read_only"] is True
    assert report["data_quality"]["AUTHORITATIVE"]["grade"] == "INSUFFICIENT"


def test_metrics_include_consistency_risk_execution_and_excursions():
    report = build_strategic_audit(snapshot())
    assert performance(snapshot()["lanes"]["SPY"])["worst_5_trade_sequence"] is not None
    assert report["execution"]["SPY"]["p90_spread_percent"] == 4
    assert report["mfe_mae_exit"]["SPY"]["coverage"] == 6
    assert report["signal_frequency_and_sample_efficiency"]["SPY"]["estimated_sessions_for_samples"]["50"]


def test_profitable_trade_with_missing_mfe_is_unavailable_not_type_error():
    row = trade("missing-mfe", "SPY", 5)
    row["mfe"] = None
    result = excursions([row])
    assert result["coverage"] == 0
    assert result["winner_giveback_over_25pct_of_mfe"] == 0


def test_insufficient_sample_is_not_promoted_or_hindsight_filtered():
    report = build_strategic_audit(snapshot())
    assert report["verdict"]["architecture_recommendation"] == "NOT ENOUGH EVIDENCE"
    assert all(value is False for value in report["verdict"]["positive_expectancy_evidence"].values())
    assert "unchanged" in report["next_experiment"]["predeclared_rule"]


def test_production_reader_is_projected_bounded_read_only_and_provider_free():
    source = open("analysis/run_spy_qqq_strategic_audit.py", encoding="utf-8").read().lower()
    assert "set transaction read only" not in source  # centralized enforced connection
    assert "select *" not in source
    assert "limit %s" in source
    assert all(token not in source for token in ("insert ", "update ", "delete ", "create table", "option_quote", "chain_provider"))
