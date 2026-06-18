import streamlit as st

st.set_page_config(page_title="Option Beacon", layout="wide")

st.title("🚨 Option Beacon")
st.subheader("Live Scanner Dashboard")

st.warning("Paper-trading dashboard only. Not financial advice.")

st.write("If you can see this, Streamlit is working.")

if st.button("Test App"):
    st.success("Button works. Dashboard is alive.")
