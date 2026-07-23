from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
from pandas.errors import EmptyDataError

from live_trade_coach import coach_live_setup
from market_intelligence import setup_momentum_snapshot
from optionbeacon_snapshot import REMOTE_DATA_BASE_URL


ALERT_FILE = "live_coach_alerts.csv"
REMOTE_ALERT_URL = f"{REMOTE_DATA_BASE_URL}/{ALERT_FILE}"
ALERT_COLUMNS = [
    "timestamp",
    "symbol",
    "bias",
    "score",
    "action",
    "live_read",
    "exit_score",
    "exit_label",
    "chase_risk",
    "headline",
    "next_step",
    "reason",
    "dedupe_key",
]

WATCH_ACTIONS = {"Entry zone active", "Watch for trigger", "Avoid chasing"}
WATCH_LIVE_READS = {"Bias flipped", "Weakening", "Improving", "State changed"}


def eastern_timestamp():
    return datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %I:%M %p ET")


def empty_alerts():
    return pd.DataFrame(columns=ALERT_COLUMNS)


def normalize_alerts(alerts):
    if alerts is None or alerts.empty:
        return empty_alerts()
    normalized = alerts.copy()
    for column in ALERT_COLUMNS:
        if column not in normalized.columns:
            normalized[column] = ""
    return normalized[ALERT_COLUMNS]


def load_live_coach_alerts():
    try:
        return normalize_alerts(pd.read_csv(ALERT_FILE, dtype=str))
    except (FileNotFoundError, EmptyDataError):
        pass

    try:
        return normalize_alerts(pd.read_csv(REMOTE_ALERT_URL, dtype=str))
    except (EmptyDataError, Exception):
        return empty_alerts()


def save_live_coach_alerts(alerts):
    normalize_alerts(alerts).tail(300).to_csv(ALERT_FILE, index=False)


def alert_reason(coach, momentum):
    if coach["action"] in WATCH_ACTIONS:
        return coach["summary"]
    if momentum["label"] in WATCH_LIVE_READS:
        return momentum["detail"]
    if coach["exit_score"] >= 80:
        return f"Exit score reached {coach['exit_score']}/100: {coach['exit_label']}."
    if coach["exit_score"] >= 55:
        return f"Exit score moved into caution territory: {coach['exit_label']}."
    if coach["chase_risk"] == "High":
        return coach["chase_reason"]
    return ""


def should_log_live_coach_alert(result, coach, momentum):
    signal = result.get("signal")
    if signal in ["MARKET CLOSED / WAIT", "WAITING FOR CANDLE", "DATA UNAVAILABLE"]:
        return False

    return (
        coach["action"] in WATCH_ACTIONS
        or momentum["label"] in WATCH_LIVE_READS
        or coach["exit_score"] >= 55
        or coach["chase_risk"] == "High"
    )


def build_live_coach_alert(result, history=None):
    coach = coach_live_setup(result)
    momentum = setup_momentum_snapshot(result, history)

    if not should_log_live_coach_alert(result, coach, momentum):
        return None

    symbol = result.get("symbol", "")
    bias = result.get("bias", "Neutral")
    score = int(result.get("confidence", 0) or 0)
    reason = alert_reason(coach, momentum)
    headline = f"{symbol} {coach['action']} - {momentum['label']}"
    dedupe_key = "|".join(
        [
            symbol,
            bias,
            coach["action"],
            momentum["label"],
            str(coach["exit_score"]),
            coach["chase_risk"],
        ]
    )

    return {
        "timestamp": eastern_timestamp(),
        "symbol": symbol,
        "bias": bias,
        "score": str(score),
        "action": coach["action"],
        "live_read": momentum["label"],
        "exit_score": str(coach["exit_score"]),
        "exit_label": coach["exit_label"],
        "chase_risk": coach["chase_risk"],
        "headline": headline,
        "next_step": coach["next_step"],
        "reason": reason,
        "dedupe_key": dedupe_key,
    }


def append_live_coach_alert(alert, alerts=None):
    if not alert:
        return False, None

    alerts = normalize_alerts(alerts if alerts is not None else load_live_coach_alerts())
    recent_keys = set(alerts.tail(50)["dedupe_key"].dropna().astype(str))
    if alert["dedupe_key"] in recent_keys:
        return False, alert

    updated = pd.concat([alerts, pd.DataFrame([alert])], ignore_index=True)
    save_live_coach_alerts(updated)
    return True, alert


def record_live_coach_alert(result, history=None, alerts=None):
    alert = build_live_coach_alert(result, history=history)
    return append_live_coach_alert(alert, alerts=alerts)


def symbol_alert_timeline(alerts, symbol=None, limit=25):
    alerts = normalize_alerts(alerts)
    if alerts.empty:
        return alerts

    timeline = alerts.copy()
    if symbol:
        timeline = timeline[timeline["symbol"] == symbol]

    return timeline.tail(limit)


def timeline_summary(alerts, symbol=None):
    timeline = symbol_alert_timeline(alerts, symbol=symbol, limit=50)
    if timeline.empty:
        return {
            "headline": "No timeline yet",
            "detail": "No guide alerts have been logged for this symbol yet.",
            "events": 0,
            "latest_action": "N/A",
            "latest_read": "N/A",
        }

    first = timeline.iloc[0]
    latest = timeline.iloc[-1]
    events = len(timeline)
    latest_action = latest.get("action", "N/A")
    latest_read = latest.get("live_read", "N/A")
    latest_score = latest.get("score", "N/A")
    latest_exit_score = latest.get("exit_score", "N/A")

    if latest_read == "Bias flipped":
        headline = "Bias changed"
    elif latest_read == "Improving":
        headline = "Idea improving"
    elif latest_read == "Weakening":
        headline = "Idea weakening"
    elif latest_action == "Avoid chasing":
        headline = "Chase risk active"
    elif latest_action == "Entry zone active":
        headline = "Entry zone active"
    elif latest_action == "Watch for trigger":
        headline = "Setup on watch"
    else:
        headline = "Guide updated"

    detail = (
        f"{first.get('timestamp', 'First read')} -> {latest.get('timestamp', 'latest read')}. "
        f"Latest action: {latest_action}. Live read: {latest_read}. "
        f"Score {latest_score}/100, exit score {latest_exit_score}/100."
    )

    return {
        "headline": headline,
        "detail": detail,
        "events": events,
        "latest_action": latest_action,
        "latest_read": latest_read,
    }
