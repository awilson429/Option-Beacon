import streamlit as st

st.set_page_config(
    page_title="Option Beacon",
    layout="wide"
)

st.title("🚨 Option Beacon")
st.subheader("SPY / QQQ Live Scanner")

st.write("Live market signals")

if st.button("Scan Now"):

    st.write("Running scanner...")

    try:
        from optionbeacon_live import generate_signal

        for symbol in ["SPY", "QQQ"]:

            result = generate_signal(symbol)

            st.divider()

            st.header(symbol)

            signal = result["signal"]
            price = result["price"]

            col1, col2 = st.columns(2)

            with col1:
                    st.metric("Signal", signal)

            with col2:
                    st.metric("Price", f"${price:.2f}")

            if signal == "CALL":
                    st.success("🟢 CALL SIGNAL")

            elif signal == "PUT":
                    st.error("🔴 PUT SIGNAL")
    
            else:
                    st.info("⚪ WAIT")

            except Exception as e:

        st.error("Scanner Error")
        st.exception(e)
