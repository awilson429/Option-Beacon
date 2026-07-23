import pandas as pd

from live_coach_alerts import append_live_coach_alert, build_live_coach_alert


def triggered_result():
    return {
        "symbol": "SPY",
        "signal": "BULLISH SETUP",
        "bias": "Bullish",
        "confidence": 91,
        "price": 600,
        "entry_timing": "Trigger confirmed",
        "setup_stage": "Triggered",
        "bullish_score": 91,
        "bearish_score": 30,
        "trend_score": 20,
        "momentum_score": 18,
        "volume_score": 15,
        "price_action_score": 14,
        "atr": 2,
        "trade_plan": {
            "trigger_price": 599.5,
            "invalidation_level": 597,
            "target_1": 603,
            "target_2": 606,
            "max_entry_price": 601,
        },
    }


def test_build_live_coach_alert_for_entry_zone():
    alert = build_live_coach_alert(triggered_result())

    assert alert["symbol"] == "SPY"
    assert alert["action"] == "Entry zone active"
    assert alert["headline"].startswith("SPY Entry zone active")


def test_append_live_coach_alert_suppresses_duplicate(tmp_path, monkeypatch):
    alert_file = tmp_path / "live_coach_alerts.csv"
    monkeypatch.setattr("live_coach_alerts.ALERT_FILE", str(alert_file))
    alert = build_live_coach_alert(triggered_result())

    first_added, _ = append_live_coach_alert(alert, alerts=pd.DataFrame())
    second_added, _ = append_live_coach_alert(alert)

    assert first_added is True
    assert second_added is False
