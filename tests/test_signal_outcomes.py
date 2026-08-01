from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from signal_outcomes import (
    build_outcome_row,
    directional_return,
    record_signal_outcomes,
    summarize_outcomes,
    load_signal_outcomes,
)


def setup_result(symbol="SPY", bias="Bullish", score=82, price=100):
    signal = "BULLISH SETUP" if bias == "Bullish" else "BEARISH SETUP"
    return {
        "symbol": symbol,
        "signal": signal,
        "bias": bias,
        "confidence": score,
        "price": price,
        "entry_timing": "Watch closely",
        "setup_stage": "Armed",
        "trade_plan": {
            "trigger_price": price,
            "technical_stop": price - 2 if bias == "Bullish" else price + 2,
            "target_1": price + 3 if bias == "Bullish" else price - 3,
        },
        "timestamp": datetime(2026, 7, 24, 10, 0, tzinfo=ZoneInfo("America/New_York")).isoformat(),
    }


def test_build_outcome_row_tracks_actionable_setup():
    now = datetime(2026, 7, 24, 10, 0, tzinfo=ZoneInfo("America/New_York"))

    row = build_outcome_row("SPY", setup_result(), now)

    assert row["symbol"] == "SPY"
    assert row["bias"] == "Bullish"
    assert row["action"] == "Watch for trigger"
    assert row["status"] == "OPEN"


def test_directional_return_flips_for_bearish_setups():
    assert directional_return("Bullish", 100, 102) == 2
    assert directional_return("Bearish", 100, 98) == 2


def test_record_signal_outcomes_updates_10_minute_result(tmp_path):
    file_name = tmp_path / "signal_outcomes.csv"
    opened_at = datetime(2026, 7, 24, 10, 0, tzinfo=ZoneInfo("America/New_York"))
    first_results = {"SPY": setup_result(price=100)}

    history, new_rows = record_signal_outcomes(
        first_results,
        now=opened_at,
        file_name=file_name,
    )

    assert new_rows == 1
    assert len(history) == 1

    later_result = setup_result(price=101)
    later_result["timestamp"] = (opened_at + timedelta(minutes=10)).isoformat()
    history, new_rows = record_signal_outcomes(
        {"SPY": later_result},
        history=history,
        now=opened_at + timedelta(minutes=10),
        file_name=file_name,
    )

    assert new_rows == 1
    assert history.iloc[0]["outcome_10m"] == "Strong follow-through"
    assert history.iloc[0]["return_10m"] == "1.00"

    summary = summarize_outcomes(history)
    assert summary["completed_10m"] == 1
    assert summary["win_rate_10m"] == 100.0


def test_missing_explicit_history_path_does_not_load_remote_history(tmp_path, monkeypatch):
    monkeypatch.setattr("signal_outcomes.pd.read_csv", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("remote read attempted")))
    assert load_signal_outcomes(tmp_path / "isolated.csv").empty
