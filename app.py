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

            st.write(result)

    except Exception as e:

        st.error("Scanner Error")
        st.exception(e)
