import streamlit as st

st.set_page_config(page_title="Option Beacon", layout="wide")

st.title("🚨 Option Beacon")
st.subheader("SPY / QQQ Live Signal Dashboard")

st.warning("Paper-trading dashboard only. Not financial advice.")

if st.button("Scan Now"):
    try:
        from optionbeacon_live import generate_signal

        for symbol in ["SPY", "QQQ"]:
            st.divider()
            st.header(symbol)

            result = generate_signal(symbol)

            if result is None:
                st.error("No data returned.")
                continue

            st.metric("Signal", result.get("signal", "UNKNOWN"))
            st.metric("Price", f"${result.get('price', 0):.2f}")

            if "confidence" in result:
                col1, col2, col3 = st.columns(3)
                col1.metric("Confidence", f"{result['confidence']}%")
                col2.metric("CALL Score", result["call_score"])
                col3.metric("PUT Score", result["put_score"])

            if result.get("signal") not in ["WAIT", "MARKET CLOSED / WAIT"]:
                st.success("TRADE SETUP FOUND")
                st.write(f"**Entry:** ${result['entry']:.2f}")
                st.write(f"**Stop:** ${result['stop']:.2f}")
                st.write(f"**Target:** ${result['target']:.2f}")
                st.write(f"**Breakeven:** ${result['breakeven']:.2f}")

            if "reasons" in result:
                st.write("### Reasons")
                for reason in result["reasons"]:
                    st.write(f"- {reason}")

    except Exception as e:
        st.error("Scanner error")
        st.exception(e)
