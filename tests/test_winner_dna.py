import inspect
import math
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import app
from winner_dna import (
    MIN_PATTERN_SAMPLE,
    analyze_winner_dna,
    classify_outcome,
    feature_bin,
    outcome_thresholds,
    session_bucket,
    summarize,
)
from winner_dna_dashboard import render_winner_dna


NOW = datetime(2026, 1, 2, 15, tzinfo=timezone.utc)


def data(count=20):
    snapshots, outcomes, mirrors, marks, journal, captures = [], [], [], [], [], []
    returns = [-1, -.05, .2, .5, 1, 2]
    for index in range(count):
        identity = f"trade-{index:03d}"
        at = NOW + timedelta(days=index)
        value = returns[index % len(returns)]
        strong = index % 2 == 0
        snapshots.append({"snapshot": {
            "opportunity_id": identity, "symbol": "SPY" if index < count * .6 else f"S{index}",
            "direction": "Bullish" if index % 3 else "Bearish", "setup_type": "Breakout",
            "entry_timestamp": at.isoformat(), "session_segment": "MORNING",
            "features": {"relative_volume": 1.8 if strong else .8, "rsi": 58 if strong else 72,
                         "vwap_relationship": "ABOVE", "distance_from_vwap": .2,
                         "trend_alignment": "BULLISH", "ema9": 101, "ema21": 100,
                         "atr": 1.2, "spy_direction": "UP", "qqq_direction": "UP"},
            "scoring": {"confidence": 80 if strong else 65, "quality": 82 if strong else 66},
            "market_regime": {"regime": "BULLISH_TREND"},
            "sector_context": {"sector": "Index", "alignment_status": "ALIGNED"},
        }})
        outcomes.append({"outcome": {
            "opportunity_id": identity, "entered": True, "never_entered": False,
            "entry_timestamp": at.isoformat(), "exit_timestamp": (at + timedelta(minutes=30)).isoformat(),
            "entry_price": 100, "realized_return": value, "maximum_favorable_excursion": max(value, .1),
            "maximum_adverse_excursion": min(value, -.1), "duration_minutes": 30,
        }})
        pnl = 20 if strong else -15
        mirrors.append({"mirror_trade_id": f"mirror-{identity}", "opportunity_id": identity,
                        "realized_pnl": pnl, "realized_return_percent": pnl / 100 * 100,
                        "total_debit": 100, "spread_percent": 10, "dte": 7,
                        "opened_at": at, "exit_quote_at": at + timedelta(minutes=30)})
        marks.append({"mirror_trade_id": f"mirror-{identity}", "return_pct": 5})
        captures.append(SimpleNamespace(trade_id=f"paper-{identity}", source_signal_id=identity))
        journal.append({"trade_id": f"paper-{identity}", "reason_code": "ELIGIBLE", "created_at": at})
    return snapshots, outcomes, mirrors, marks, journal, captures


def report(count=20):
    snapshots, outcomes, mirrors, marks, journal, captures = data(count)
    return analyze_winner_dna(snapshots, outcomes, mirror_rows=mirrors, mirror_marks=marks,
                              broad_journal=journal, broad_captures=captures)


def test_exact_opportunity_id_join_does_not_fuzzy_match():
    snapshots, outcomes, mirrors, marks, journal, captures = data(2)
    mirrors[0]["opportunity_id"] = "different-id"
    result = analyze_winner_dna(snapshots, outcomes, mirror_rows=mirrors, mirror_marks=marks,
                                broad_journal=journal, broad_captures=captures)
    row = next(row for row in result["rows"] if row["opportunity_id"] == "trade-000")
    assert row["mirror_pnl"] is None and row["option_translation_bucket"] == "MIRROR UNAVAILABLE"


def test_distribution_driven_outcome_buckets_separate_large_small_flat_and_loss():
    rows = [{"realized_return": value} for value in (-1, -.05, .2, .5, 1, 2)]
    thresholds = outcome_thresholds(rows)
    assert thresholds["large_winner_positive_75th_percentile"] == pytest.approx(1.25)
    assert classify_outcome(-1, thresholds) == "LOSER"
    assert classify_outcome(-.05, thresholds) == "FLAT / NOISE"
    assert classify_outcome(.2, thresholds) == "SMALL WINNER"
    assert classify_outcome(2, thresholds) == "LARGE WINNER"


def test_auth_win_mirror_loss_and_win_translation_are_separate():
    result = report()
    buckets = {group["group"] for group in result["option_translation"]}
    assert "AUTH WIN / MIRROR WIN" in buckets
    assert "AUTH WIN / MIRROR LOSS" in buckets
    rows = [row for row in result["rows"] if row["realized_return"] > 0]
    assert all(row["option_translation_bucket"].startswith("AUTH WIN") for row in rows)


def test_continuous_binning_expectancy_and_profit_factor():
    assert feature_bin("relative_volume", .8) == "-inf–1"
    assert feature_bin("relative_volume", 1.5) == "1.5–2"
    summary = summarize([{"realized_return": 2}, {"realized_return": -1}])
    assert summary["expectancy"] == .5 and summary["profit_factor"] == 2
    assert summary["average_winner"] == 2 and summary["average_loser"] == -1


def test_chronological_patterns_enforce_sample_size_and_validation():
    small = report(MIN_PATTERN_SAMPLE - 1)
    assert all(row["stability"] == "INSUFFICIENT DATA" for row in small["patterns"])
    larger = report(30)
    candidate = next(row for row in larger["patterns"] if row["pattern"].startswith("VWAP"))
    assert candidate["train_n"] == 21 and candidate["validation_n"] == 9
    assert candidate["train"]["n"] == 21 and candidate["validation"]["n"] == 9


def test_symbol_concentration_missing_coverage_and_session_bucket():
    result = report()
    assert result["symbol_concentration_warning"] is True
    assert result["coverage"]["confidence"] == 100
    assert result["coverage"]["mirror_marks"] == 100
    assert result["coverage"]["delta"] == 0 and result["coverage"]["iv"] == 0
    assert session_bucket("2026-08-07T13:45:00Z") == "OPEN"
    assert session_bucket("2026-08-07T16:30:00Z") == "MIDDAY"


def test_mirror_capital_efficiency_uses_debit_and_overlap():
    result = report(4)
    all_rows = result["option_translation"]
    combined_peak = max(group["peak_capital"] for group in all_rows)
    assert combined_peak > 0
    assert all(group["average_debit"] == 100 for group in all_rows)
    assert all(group["return_on_debit"] is not None for group in all_rows)


def test_no_provider_calls_writes_or_trading_behavior_hooks():
    analytics = inspect.getsource(analyze_winner_dna)
    dashboard = inspect.getsource(render_winner_dna)
    for forbidden in ("provider", "option_quote", "record_trade", "create_intelligence", "upsert_", "update_mark", "run_mirror"):
        assert forbidden not in analytics
    for forbidden in (".save(", ".append(", "record_disposition(", "update_mark(", "run_mirror_execution("):
        assert forbidden not in dashboard
    assert "render_winner_dna" in inspect.getsource(app.render_developer_tools)
