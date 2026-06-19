import os
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh
from datetime import datetime
from zoneinfo import ZoneInfo

st.set_page_config(
    page_title="Option Beacon",
    layout="wide"
)

# Refresh every 1 minute
st_autorefresh(interval=60000, key="option_beacon_refresh")

HISTORY_FILE = "signal_history.csv"


def eastern_now():
    return datetime.now(ZoneInfo("America/New_York"))


def load_history():
    if os.path.exists(HISTORY_FILE):
        return pd.read_csv(HISTORY_FILE)

    return pd.DataFrame(columns=[
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
        "pnl_percent"
    ])


def save_history(history):
    history.to_csv(HISTORY_FILE, index=False)


def add_new_signal(result):
    """
    Saves a new BUY CALL or BUY PUT signal.
    Avoids saving duplicates if there is already an open trade
    for the same symbol and signal.
    """

    if result["signal"] not in ["BUY CALL", "BUY PUT"]:
        return

    history = load_history()

    # Avoid duplicate open signals
    if len(history) > 0:
        duplicate_open = history[
            (history["symbol"] == result["symbol"]) &
            (history["signal"] == result["signal"]) &
            (history["status"] == "OPEN")
        ]

        if len(duplicate_open) > 0:
            return

    new_row = {
        "timestamp": eastern_now().strftime("%Y-%m-%d %I:%M:%S %p ET"),
        "symbol": result["symbol"],
        "signal": result["signal"],
        "confidence": result["confidence"],
        "entry": round(result["entry"], 2),
        "stop": round(result["stop"], 2),
        "target": round(result["target"], 2),
        "breakeven": round(result["breakeven"], 2),
        "breakeven_active": False,
        "status": "OPEN",
        "exit_price": "",
        "exit_time": "",
        "pnl_percent": ""
    }

    updated = pd.concat([history, pd.DataFrame([new_row])], ignore_index=True)
    save_history(updated)


def update_open_signals(current_prices):
    """
    Checks every OPEN trade and updates it to:
    WIN, LOSS, BREAKEVEN, or keeps it OPEN.
    """

    history = load_history()

    if len(history) == 0:
        return history

    for i, row in history.iterrows():
        if row["status"] != "OPEN":
            continue

        symbol = row["symbol"]

        if symbol not in current_prices:
            continue

        current_price = current_prices[symbol]

        entry = float(row["entry"])
        stop = float(row["stop"])
        target = float(row["target"])
        breakeven = float(row["breakeven"])
        signal = row["signal"]

        breakeven_active = str(row["breakeven_active"]).lower() == "true"

        if signal == "BUY CALL":
            # Activate breakeven once price reaches breakeven trigger
            if current_price >= breakeven:
                breakeven_active = True
                history.at[i, "breakeven_active"] = True

            # WIN
            if current_price >= target:
                pnl = ((target - entry) / entry) * 100
                history.at[i, "status"] = "WIN"
                history.at[i, "exit_price"] = round(target, 2)
                history.at[i, "exit_time"] = eastern_now().strftime("%Y-%m-%d %I:%M:%S %p ET")
                history.at[i, "pnl_percent"] = round(pnl, 3)

            # BREAKEVEN
            elif breakeven_active and current_price <= entry:
                history.at[i, "status"] = "BREAKEVEN"
                history.at[i, "exit_price"] = round(entry, 2)
                history.at[i, "exit_time"] = eastern_now().strftime("%Y-%m-%d %I:%M:%S %p ET")
                history.at[i, "pnl_percent"] = 0.0

            # LOSS
            elif current_price <= stop:
                pnl = ((stop - entry) / entry) * 100
                history.at[i, "status"] = "LOSS"
                history.at[i, "exit_price"] = round(stop, 2)
                history.at[i, "exit_time"] = eastern_now().strftime("%Y-%m-%d %I:%M:%S %p ET")
                history.at[i, "pnl_percent"] = round(pnl, 3)

        elif signal == "BUY PUT":
            # Activate breakeven once price reaches breakeven trigger
            if current_price <= breakeven:
                breakeven_active = True
                history.at[i, "breakeven_active"] = True

            # WIN
            if current_price <= target:
                pnl = ((entry - target) / entry) * 100
                history.at[i, "status"] = "WIN"
                history.at[i, "exit_price"] = round(target, 2)
                history.at[i, "exit_time"] = eastern_now().strftime("%Y-%m-%d %I:%M:%S %p ET")
                history.at[i, "pnl_percent"] = round(pnl, 3)

            # BREAKEVEN
            elif breakeven_active and current_price >= entry:
                history.at[i, "status"] = "BREAKEVEN"
                history.at[i, "exit_price"] = round(entry, 2)
                history.at[i, "exit_time"] = eastern_now().strftime("%Y-%m-%d %I:%M:%S %p ET")
                history.at[i, "pnl_percent"] = 0.0

            # LOSS
            elif current_price >= stop:
                pnl = ((entry - stop) / entry) * 100
                history.at[i, "status"] = "LOSS"
                history.at[i, "exit_price"] = round(stop, 2)
                history.at[i, "exit_time"] = eastern_now().strftime("%Y-%m-%d %I:%M:%S %p ET")
                history.at[i, "pnl_percent"] = round(pnl, 3)

    save_history(history)
    return history


def calculate_performance(history):
    if len(history) == 0:
        return {
            "total_signals": 0,
            "open_signals": 0,
            "wins": 0,
            "losses": 0,
            "breakevens": 0,
            "win_rate": 0,
            "total_pnl": 0,
            "profit_factor": 0
        }

    closed = history[history["status"].isin(["WIN", "LOSS", "BREAKEVEN"])]

    wins = len(history[history["status"] == "WIN"])
    losses = len(history[history["status"] == "LOSS"])
    breakevens = len(history[history["status"] == "BREAKEVEN"])
    open_signals = len(history[history["status"] == "OPEN"])

    completed = wins + losses
    win_rate = (wins / completed * 100) if completed > 0 else 0

    pnl_values = pd.to_numeric(closed["pnl_percent"], errors="coerce").fillna(0)

    total_pnl = pnl_values.sum()

    gross_wins = pnl_values[pnl_values > 0].sum()
    gross_losses = abs(pnl_values[pnl_values < 0].sum())

    profit_factor = gross_wins / gross_losses if gross_losses != 0 else 0

    return {
        "total_signals": len(history),
        "open_signals": open_signals,
        "wins": wins,
        "losses": losses,
        "breakevens": breakevens,
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "profit_factor": profit_factor
    }


st.title("🚨 Option Beacon")
st.subheader("Real-Time Options Trade Intelligence")

st.warning("Paper-trading dashboard only. Not financial advice.")

st.caption(
    f"Last refreshed: {eastern_now().strftime('%Y-%m-%d %I:%M:%S %p ET')}"
)

try:
    from optionbeacon_live import generate_signal

    current_prices = {}
    latest_results = {}

    # Run scanner
    for symbol in ["SPY", "QQQ"]:
        result = generate_signal(symbol)

    if symbol == "SPY":
        result = {
            "symbol": "SPY",
            "signal": "BUY CALL",
            "confidence": 95,
            "entry": 100,
            "stop": 99,
            "target": 102,
            "breakeven": 101,
            "price": 100,
            "call_score": 95,
            "put_score": 20,
            "reasons": ["TEST SIGNAL"]
        }

        if result is None:
            continue

        latest_results[symbol] = result
        current_prices[symbol] = result.get("price", 0)

        # Save new BUY signals only
        add_new_signal(result)

    # Update open signals based on latest prices
    history = update_open_signals(current_prices)

    # Performance stats
    stats = calculate_performance(history)

    st.divider()
    st.header("Performance")

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Total Signals", stats["total_signals"])
    col2.metric("Open Signals", stats["open_signals"])
    col3.metric("Win Rate", f"{stats['win_rate']:.2f}%")
    col4.metric("Profit Factor", f"{stats['profit_factor']:.2f}")

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Wins", stats["wins"])
    col2.metric("Losses", stats["losses"])
    col3.metric("Breakevens", stats["breakevens"])
    col4.metric("Total P/L", f"{stats['total_pnl']:.3f}%")

    # Current scanner display
    st.divider()
    st.header("Current Scanner")

    for symbol in ["SPY", "QQQ"]:
        result = latest_results.get(symbol)

        st.divider()
        st.header(symbol)

        if result is None:
            st.error("No data returned.")
            continue

        signal = result.get("signal", "UNKNOWN")
        price = result.get("price", 0)

        col1, col2 = st.columns(2)

        with col1:
            st.metric("Signal", signal)

        with col2:
            st.metric("Price", f"${price:.2f}")

        if signal == "BUY CALL":
            st.success("🟢 CALL SIGNAL")

        elif signal == "BUY PUT":
            st.error("🔴 PUT SIGNAL")

        elif signal == "MARKET CLOSED / WAIT":
            st.info("⚪ Market closed — waiting for next session.")

        else:
            st.info("⚪ WAIT")

        if "confidence" in result:
            col1, col2, col3 = st.columns(3)

            with col1:
                st.metric("Confidence", f"{result['confidence']}%")

            with col2:
                st.metric("CALL Score", result["call_score"])

            with col3:
                st.metric("PUT Score", result["put_score"])

        if signal in ["BUY CALL", "BUY PUT"]:
            st.subheader("Trade Plan")

            col1, col2, col3, col4 = st.columns(4)

            with col1:
                st.metric("Entry", f"${result['entry']:.2f}")

            with col2:
                st.metric("Stop", f"${result['stop']:.2f}")

            with col3:
                st.metric("Target", f"${result['target']:.2f}")

            with col4:
                st.metric("Breakeven", f"${result['breakeven']:.2f}")

        if "reasons" in result:
            st.subheader("Reasons")

            if result["reasons"]:
                for reason in result["reasons"]:
                    st.write(f"- {reason}")
            else:
                st.write("- No strong setup yet")

    # Signal history
    st.divider()
    st.header("Signal History")

    history = load_history()

    if len(history) == 0:
        st.info("No BUY signals logged yet.")
    else:
        st.dataframe(
            history.tail(50).sort_index(ascending=False),
            use_container_width=True
        )

except Exception as e:
    st.error("Scanner Error")
    st.exception(e)
