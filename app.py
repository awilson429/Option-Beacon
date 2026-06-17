import streamlit as st
from optionbeacon_live import generate_signal

st.set_page_config(page_title="Option Beacon", layout="wide")

st.title("OPTION BEACON")
st.subheader("SPY / QQQ Live Signal Dashboard")

st.warning("Paper-trading dashboard only. Not financial advice.")

if st.button("Scan Now"):
    for symbol in ["SPY", "QQQ"]:
        result = generate_signal(symbol)

        st.divider()
        st.header(symbol)

        if result is None:
            st.error("No data found.")
            continue

        st.metric("Signal", result["signal"])
        st.metric("Price", f"${result['price']:.2f}")

        if result["signal"] not in ["WAIT", "MARKET CLOSED / WAIT"]:
            st.success("TRADE SETUP FOUND")

            col1, col2, col3 = st.columns(3)
            col1.metric("Entry", f"${result['entry']:.2f}")
            col2.metric("Stop", f"${result['stop']:.2f}")
            col3.metric("Target", f"${result['target']:.2f}")

        if "confidence" in result:
            col1, col2, col3 = st.columns(3)
            col1.metric("Confidence", f"{result['confidence']}%")
            col2.metric("CALL Score", result["call_score"])
            col3.metric("PUT Score", result["put_score"])

        if "reasons" in result:
            st.write("### Reasons")
            for reason in result["reasons"]:
                st.write(f"- {reason}")
