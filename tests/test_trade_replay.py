import pandas as pd

from trade_replay import replay_summary, replay_trade


def test_replay_trade_tracks_breakeven_partials_and_trailing_stop():
    df = pd.DataFrame(
        [
            {"Open": 100, "High": 100, "Low": 100, "Close": 100, "Volume": 1000},
            {"Open": 100, "High": 100.45, "Low": 100.05, "Close": 100.4, "Volume": 1100},
            {"Open": 100.4, "High": 100.55, "Low": 100.25, "Close": 100.5, "Volume": 1200},
            {"Open": 100.5, "High": 101.05, "Low": 100.35, "Close": 101, "Volume": 1300},
            {"Open": 101, "High": 101.1, "Low": 100.45, "Close": 100.5, "Volume": 1400},
        ],
        index=pd.date_range("2026-07-20 09:45", periods=5, freq="5min"),
    )
    setup = {
        "signal": "BULLISH SETUP",
        "price": 100,
        "entry": 100,
        "stop": 99.75,
        "target": 100.5,
        "breakeven": 100.4,
    }

    result = replay_trade(df, 0, setup, max_hold_candles=4)

    assert result["Breakeven Stop"] == "Yes"
    assert result["Target 1 Hit"] == "Yes"
    assert result["Target 2 Hit"] == "Yes"
    assert result["Exit Reason"] == "STOP"
    assert result["Exit Price"] == 100.5


def test_replay_summary_handles_result_rows():
    results = pd.DataFrame(
        [
            {"P/L %": 0.5, "Peak P/L %": 1.0, "Target 1 Hit": "Yes", "Breakeven Stop": "Yes"},
            {"P/L %": -0.25, "Peak P/L %": 0.1, "Target 1 Hit": "No", "Breakeven Stop": "No"},
        ]
    )

    summary = replay_summary(results)

    assert summary["Trades"] == 2
    assert summary["Win Rate"] == "50.00%"
    assert summary["Target 1 Rate"] == "50.00%"
