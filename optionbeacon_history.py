import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd


HISTORY_FILE = "signal_history.csv"

BUY_SIGNALS = {"BUY CALL", "BUY PUT", "BULLISH SETUP", "BEARISH SETUP"}

COLUMNS = [
    "timestamp",
    "symbol",
    "signal",
    "confidence",
    "entry",
    "stop",
    "target",
    "breakeven",
    "breakeven_active",
    "status",
    "exit_price",
    "exit_time",
    "pnl_percent",
]


def eastern_now():
    return datetime.now(ZoneInfo("America/New_York"))


def load_history():
    if os.path.exists(HISTORY_FILE):
        history = pd.read_csv(HISTORY_FILE, dtype=str)
        for col in COLUMNS:
            if col not in history.columns:
                history[col] = ""
        return history[COLUMNS]

    return pd.DataFrame(columns=COLUMNS)


def save_history(history):
    for col in COLUMNS:
        if col not in history.columns:
            history[col] = ""
    history[COLUMNS].to_csv(HISTORY_FILE, index=False)


def add_new_signal(result):
    if result["signal"] not in BUY_SIGNALS:
        return False, None

    history = load_history()

    duplicate_open = history[
        (history["symbol"] == result["symbol"])
        & (history["signal"] == result["signal"])
        & (history["status"] == "OPEN")
    ]

    if len(duplicate_open) > 0:
        return False, None

    new_row = {
        "timestamp": eastern_now().strftime("%Y-%m-%d %I:%M:%S %p ET"),
        "symbol": result["symbol"],
        "signal": result["signal"],
        "confidence": str(result.get("confidence", "")),
        "entry": str(round(result["entry"], 2)),
        "stop": str(round(result["stop"], 2)),
        "target": str(round(result["target"], 2)),
        "breakeven": str(round(result["breakeven"], 2)),
        "breakeven_active": "False",
        "status": "OPEN",
        "exit_price": "",
        "exit_time": "",
        "pnl_percent": "",
    }

    updated = pd.concat([history, pd.DataFrame([new_row])], ignore_index=True)
    save_history(updated)
    return True, new_row


def update_open_signals(current_prices):
    history = load_history()

    for i, row in history.iterrows():
        if row["status"] != "OPEN":
            continue

        symbol = row["symbol"]

        if symbol not in current_prices:
            continue

        current_price = float(current_prices[symbol])
        entry = float(row["entry"])
        stop = float(row["stop"])
        target = float(row["target"])
        breakeven = float(row["breakeven"])
        signal = row["signal"]

        breakeven_active = str(row["breakeven_active"]).lower() == "true"

        if signal in ["BUY CALL", "BULLISH SETUP"]:
            if current_price >= breakeven:
                breakeven_active = True
                history.at[i, "breakeven_active"] = "True"

            if current_price >= target:
                pnl = ((target - entry) / entry) * 100
                history.at[i, "status"] = "WIN"
                history.at[i, "exit_price"] = str(round(target, 2))
                history.at[i, "exit_time"] = eastern_now().strftime("%Y-%m-%d %I:%M:%S %p ET")
                history.at[i, "pnl_percent"] = str(round(pnl, 3))

            elif breakeven_active and current_price <= entry:
                history.at[i, "status"] = "BREAKEVEN"
                history.at[i, "exit_price"] = str(round(entry, 2))
                history.at[i, "exit_time"] = eastern_now().strftime("%Y-%m-%d %I:%M:%S %p ET")
                history.at[i, "pnl_percent"] = "0.0"

            elif current_price <= stop:
                pnl = ((stop - entry) / entry) * 100
                history.at[i, "status"] = "LOSS"
                history.at[i, "exit_price"] = str(round(stop, 2))
                history.at[i, "exit_time"] = eastern_now().strftime("%Y-%m-%d %I:%M:%S %p ET")
                history.at[i, "pnl_percent"] = str(round(pnl, 3))

        elif signal in ["BUY PUT", "BEARISH SETUP"]:
            if current_price <= breakeven:
                breakeven_active = True
                history.at[i, "breakeven_active"] = "True"

            if current_price <= target:
                pnl = ((entry - target) / entry) * 100
                history.at[i, "status"] = "WIN"
                history.at[i, "exit_price"] = str(round(target, 2))
                history.at[i, "exit_time"] = eastern_now().strftime("%Y-%m-%d %I:%M:%S %p ET")
                history.at[i, "pnl_percent"] = str(round(pnl, 3))

            elif breakeven_active and current_price >= entry:
                history.at[i, "status"] = "BREAKEVEN"
                history.at[i, "exit_price"] = str(round(entry, 2))
                history.at[i, "exit_time"] = eastern_now().strftime("%Y-%m-%d %I:%M:%S %p ET")
                history.at[i, "pnl_percent"] = "0.0"

            elif current_price >= stop:
                pnl = ((entry - stop) / entry) * 100
                history.at[i, "status"] = "LOSS"
                history.at[i, "exit_price"] = str(round(stop, 2))
                history.at[i, "exit_time"] = eastern_now().strftime("%Y-%m-%d %I:%M:%S %p ET")
                history.at[i, "pnl_percent"] = str(round(pnl, 3))

    save_history(history)
    return history
