import os
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh
from datetime import datetime
from zoneinfo import ZoneInfo

st.set_page_config(page_title="Option Beacon", layout="wide")
st_autorefresh(interval=60000, key="option_beacon_refresh")

HISTORY_FILE = "signal_history.csv"

COLUMNS = [
    "timestamp", "symbol", "signal", "confidence",
    "entry", "stop", "target", "breakeven",
    "breakeven_active", "status",
    "exit_price", "exit_time", "pnl_percent"
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
    if result["signal"] not in ["BUY CALL", "BUY PUT"]:
        return

    history = load_history()

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
        "confidence": str(result.get("confidence", "")),
        "entry": str(round(result["entry"], 2)),
        "stop": str(round(result["stop"], 2)),
        "target": str(round(result["target"], 2)),
        "breakeven": str(round(result["breakeven"], 2)),
        "breakeven_active": "False",
        "status": "OPEN",
        "exit_price": "",
        "exit_time": "",
        "pnl_percent": ""
    }

    updated = pd.concat([history, pd.DataFrame([new_row])], ignore_index=True)
    save_history(updated)


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

        if signal == "BUY CALL":
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

        elif signal == "BUY PUT":
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


def calculate_performance(history):
    if len(history) == 0:
        return {
            "total": 0, "open": 0, "wins": 0, "losses": 0,
            "breakevens": 0, "win_rate": 0,
            "total_pnl": 0, "profit_factor": 0
        }

    wins = len(history[history["status"] == "WIN"])
    losses = len(history[history["status"] == "LOSS"])
    breakevens = len(history[history["status"] == "BREAKEVEN"])
    open_trades = len(history[history["status"] == "OPEN"])

    completed = wins + losses
    win_rate = (wins / completed * 100) if completed > 0 else 0

    closed = history[history["status"].isin(["WIN", "LOSS", "BREAKEVEN"])]
    pnl_values = pd.to_numeric(closed["pnl_percent"], errors="coerce").fillna(0)

    gross_wins = pnl_values[pnl_values > 0].sum()
    gross_losses = abs(pnl_values[pnl_values < 0].sum())
    profit_factor = gross_wins / gross_losses if gross_losses > 0 else 0

    return {
        "total": len(history),
        "open": open_trades,
        "wins": wins,
        "losses": losses,
        "breakevens": breakevens,
        "win_rate": win_rate,
        "total_pnl": pnl_values.sum(),
        "profit_factor": profit_factor
    }


def open_trade_pnl(row, current_price):
    entry = float(row["entry"])

    if row["signal"] == "BUY CALL":
        return ((current_price - entry) / entry) * 100

    if row["signal"] == "BUY PUT":
        return ((entry - current_price) / entry) * 100

    return 0


def status_badge(status):
    if status == "WIN":
        return "🟢 WIN"
    if status == "LOSS":
        return "🔴 LOSS"
    if status == "BREAKEVEN":
        return "🟡 BREAKEVEN"
    if status == "OPEN":
        return "🔵 OPEN"
    return status


def signal_label(signal):
    if signal == "BUY CALL":
        return "🟢 BUY CALL"
    if signal == "BUY PUT":
        return "🔴 BUY PUT"
    if signal == "MARKET CLOSED / WAIT":
        return "⚪ MARKET CLOSED"
    return "⚪ WAIT"


def quality_summary(result):
    reasons = " ".join(result.get("reasons", [])).lower()

    checks = {
        "VWAP": "PASS" if "vwap" in reasons else "WAIT",
        "EMA": "PASS" if "ema" in reasons else "WAIT",
        "RSI": "PASS" if "rsi" in reasons else "WAIT",
        "Volume": "PASS" if "volume" in reasons else "WAIT",
        "Breakout": "PASS" if "breakout" in reasons or "breakdown" in reasons else "WAIT",
    }

    return checks


st.title("🚨 Option Beacon")
st.caption(f"Last refreshed: {eastern_now().strftime('%Y-%m-%d %I:%M:%S %p ET')}")
st.warning("Paper-trading dashboard only. Not financial advice.")

try:
    from optionbeacon_live import generate_signal

    current_prices = {}
    latest_results = {}

    for symbol in ["SPY", "QQQ"]:
        result = generate_signal(symbol)

        if result is None:
            continue

        latest_results[symbol] = result
        current_prices[symbol] = result.get("price", 0)

        add_new_signal(result)

    history = update_open_signals(current_prices)
    stats = calculate_performance(history)

    st.subheader("Current Scanner")

    col_spy, col_qqq = st.columns(2)

    for col, symbol in zip([col_spy, col_qqq], ["SPY", "QQQ"]):
        result = latest_results.get(symbol)

        with col:
            st.container(border=True)
            st.markdown(f"### {symbol}")

            if result is None:
                st.error("No data returned.")
                continue

            signal = result.get("signal", "UNKNOWN")
            price = result.get("price", 0)

            st.metric("Signal", signal_label(signal))
            st.metric("Price", f"${price:.2f}")

            if "confidence" in result:
                c1, c2, c3 = st.columns(3)
                c1.metric("Confidence", f"{result['confidence']}%")
                c2.metric("Call", result.get("call_score", ""))
                c3.metric("Put", result.get("put_score", ""))

            if signal in ["BUY CALL", "BUY PUT"]:
                st.success("Trade setup active")

                p1, p2, p3, p4 = st.columns(4)
                p1.metric("Entry", f"${result['entry']:.2f}")
                p2.metric("Stop", f"${result['stop']:.2f}")
                p3.metric("Target", f"${result['target']:.2f}")
                p4.metric("BE", f"${result['breakeven']:.2f}")

            with st.expander("Signal Details"):
                checks = quality_summary(result)

                q1, q2, q3, q4, q5 = st.columns(5)
                q1.metric("VWAP", checks["VWAP"])
                q2.metric("EMA", checks["EMA"])
                q3.metric("RSI", checks["RSI"])
                q4.metric("Volume", checks["Volume"])
                q5.metric("Breakout", checks["Breakout"])

                st.markdown("**Reasons**")
                if result.get("reasons"):
                    for reason in result["reasons"]:
                        st.write(f"- {reason}")
                else:
                    st.write("- No strong setup yet")

    st.divider()
    st.subheader("Performance")

    p1, p2, p3, p4 = st.columns(4)
    p1.metric("Total Signals", stats["total"])
    p2.metric("Open Trades", stats["open"])
    p3.metric("Win Rate", f"{stats['win_rate']:.2f}%")
    p4.metric("Profit Factor", f"{stats['profit_factor']:.2f}")

    p5, p6, p7, p8 = st.columns(4)
    p5.metric("Wins", stats["wins"])
    p6.metric("Losses", stats["losses"])
    p7.metric("Breakevens", stats["breakevens"])
    p8.metric("Total P/L", f"{stats['total_pnl']:.3f}%")

    st.divider()
    st.subheader("Open Trades")

    open_trades = history[history["status"] == "OPEN"]

    if len(open_trades) == 0:
        st.info("No open trades.")
    else:
        rows = []

        for _, row in open_trades.iterrows():
            symbol = row["symbol"]
            current_price = current_prices.get(symbol)

            live_pnl = ""
            if current_price:
                live_pnl = round(open_trade_pnl(row, current_price), 3)

            rows.append({
                "Time": row["timestamp"],
                "Symbol": symbol,
                "Signal": row["signal"],
                "Entry": row["entry"],
                "Current": round(current_price, 2) if current_price else "",
                "Stop": row["stop"],
                "Target": row["target"],
                "Live P/L %": live_pnl,
                "Status": status_badge(row["status"])
            })

        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Signal History")

    if len(history) == 0:
        st.info("No BUY signals logged yet.")
    else:
        display_history = history.copy()
        display_history["status"] = display_history["status"].apply(status_badge)

        st.dataframe(
            display_history.tail(50).sort_index(ascending=False),
            use_container_width=True,
            hide_index=True
        )

except Exception as e:
    st.error("Scanner Error")
    st.exception(e)
