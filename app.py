import os
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh
from datetime import datetime
from zoneinfo import ZoneInfo

st.set_page_config(page_title="Option Beacon", layout="wide")

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
        "price"
    ])


def save_signal(result):
    if result["signal"] not in ["BUY CALL", "BUY PUT"]:
        return

    history = load_history()

    new_row = {
        "timestamp": eastern_now().strftime("%Y-%m-%d %I:%M:%S %p ET"),
        "symbol": result["symbol"],
        "signal": result["signal"],
        "confidence": result["confidence"],
        "entry": round(result["entry"], 2),
        "stop": round(result["stop"], 2),
        "target": round(result["target"], 2),
        "breakeven": round(result["breakeven"], 2),
        "price": round(result["price"], 2),
    }

    # Avoid duplicate saves on refresh
    duplicate = (
        (history["symbol"] == new_row["symbol"]) &
        (history["signal"] == new_row["signal"]) &
        (history["entry"] == new_row["entry"])
    )

    if len(history) > 0 and duplicate.any():
        return

    updated = pd.concat([history, pd.DataFrame([new_row])], ignore_index=True)
    updated.to_csv(HISTORY_FILE, index=False)


st.title("🚨 Option Beacon")
st.subheader("Real-Time Options Trade Indicators")

st.warning("Paper-trading dashboard only. Not financial advice.")

st.caption(
    f"Last refreshed: {eastern_now().strftime('%Y-%m-%d %I:%M:%S %p ET')}"
)

try:
    from optionbeacon_live import generate_signal

    for symbol in ["SPY", "QQQ"]:
        result = generate_signal(symbol)

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
            save_signal(result)

        elif signal == "BUY PUT":
            st.error("🔴 PUT SIGNAL")
            save_signal(result)

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

    st.divider()
    st.header("Recent Signals")

    history = load_history()

    if len(history) == 0:
        st.info("No BUY signals logged yet.")
    else:
        st.dataframe(
            history.tail(25).sort_index(ascending=False),
            use_container_width=True
        )

except Exception as e:
    st.error("Scanner Error")
    st.exception(e)
