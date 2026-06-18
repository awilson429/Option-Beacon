import streamlit as st
from streamlit_autorefresh import st_autorefresh
from datetime import datetime

st.set_page_config(
    page_title="Option Beacon",
    layout="wide"
)

st_autorefresh(interval=300000, key="option_beacon_refresh")

st.title("🚨 Option Beacon")
st.subheader("SPY / QQQ Live Scanner")

st.warning("Paper-trading dashboard only. Not financial advice.")

st.caption(f"Last refreshed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

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

except Exception as e:
    st.error("Scanner Error")
    st.exception(e)
