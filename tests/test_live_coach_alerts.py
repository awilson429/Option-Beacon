import pandas as pd

from live_coach_alerts import (
    append_live_coach_alert,
    build_live_coach_alert,
    symbol_alert_timeline,
    timeline_summary,
)


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


def test_timeline_summary_detects_latest_story():
    alerts = pd.DataFrame(
        [
            {
                "timestamp": "2026-07-23 09:45 AM ET",
                "symbol": "SPY",
                "bias": "Bullish",
                "score": "82",
                "action": "Watch for trigger",
                "live_read": "New read",
                "exit_score": "5",
                "chase_risk": "Low",
            },
            {
                "timestamp": "2026-07-23 10:00 AM ET",
                "symbol": "SPY",
                "bias": "Bullish",
                "score": "91",
                "action": "Entry zone active",
                "live_read": "Improving",
                "exit_score": "10",
                "chase_risk": "Low",
            },
        ]
    )

    summary = timeline_summary(alerts, symbol="SPY")

    assert summary["headline"] == "Idea improving"
    assert summary["events"] == 2
    assert summary["latest_action"] == "Entry zone active"


def test_symbol_alert_timeline_filters_symbol():
    alerts = pd.DataFrame(
        [
            {"symbol": "SPY", "action": "Watch for trigger"},
            {"symbol": "QQQ", "action": "Avoid chasing"},
        ]
    )

    timeline = symbol_alert_timeline(alerts, symbol="QQQ")

    assert len(timeline) == 1
    assert timeline.iloc[0]["symbol"] == "QQQ"
