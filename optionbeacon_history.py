import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd


HIGH_SCORE_FILE = "high_score_history.csv"

HIGH_SCORE_THRESHOLD = 80

HIGH_SCORE_COLUMNS = [
    "timestamp",
    "symbol",
    "bias",
    "score",
    "signal",
    "price",
    "quality",
    "reason",
]


def eastern_now():
    return datetime.now(ZoneInfo("America/New_York"))


def load_high_score_history():
    if os.path.exists(HIGH_SCORE_FILE):
        history = pd.read_csv(HIGH_SCORE_FILE, dtype=str)
        for col in HIGH_SCORE_COLUMNS:
            if col not in history.columns:
                history[col] = ""
        return history[HIGH_SCORE_COLUMNS]

    return pd.DataFrame(columns=HIGH_SCORE_COLUMNS)


def save_high_score_history(history):
    for col in HIGH_SCORE_COLUMNS:
        if col not in history.columns:
            history[col] = ""
    history[HIGH_SCORE_COLUMNS].tail(250).to_csv(HIGH_SCORE_FILE, index=False)


def add_high_score_snapshot(result):
    score = int(result.get("confidence", 0) or 0)
    if score < HIGH_SCORE_THRESHOLD:
        return False, None

    history = load_high_score_history()
    now_label = eastern_now().strftime("%Y-%m-%d %I:%M %p ET")
    reason = result.get("reasons", [""])[0] if result.get("reasons") else ""

    duplicate_recent = history[
        (history["timestamp"] == now_label)
        & (history["symbol"] == result["symbol"])
        & (history["bias"] == result.get("bias", "Neutral"))
    ]

    if len(duplicate_recent) > 0:
        return False, None

    new_row = {
        "timestamp": now_label,
        "symbol": result["symbol"],
        "bias": result.get("bias", "Neutral"),
        "score": str(score),
        "signal": result.get("signal", "WATCHLIST"),
        "price": str(round(result["price"], 2)) if result.get("price") else "",
        "quality": result.get("quality", ""),
        "reason": reason,
    }

    updated = pd.concat([history, pd.DataFrame([new_row])], ignore_index=True)
    save_high_score_history(updated)
    return True, new_row
