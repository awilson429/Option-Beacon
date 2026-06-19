from datetime import time

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from optionbeacon_alerts import send_trade_alert, twilio_configured
from optionbeacon_history import add_new_signal, eastern_now, mark_alert_status, update_open_signals
from optionbeacon_live import generate_signal
from optionbeacon_stats import calculate_performance, calculate_symbol_stats, open_trade_pnl


SYMBOLS = ["SPY", "QQQ"]
BUY_SIGNALS = {"BUY CALL", "BUY PUT"}


def is_market_open_now():
    now = eastern_now()
    current_time = now.time()
    return now.weekday() < 5 and time(9, 30) <= current_time < time(16, 0)


def setup_grade(confidence):
    try:
        score = int(confidence)
    except (TypeError, ValueError):
        return "N/A"

    if score >= 98:
        return "A+"
    if score >= 95:
        return "A"
    if score >= 90:
        return "B+"
    if score >= 85:
        return "B"
    return "WAIT"


def status_badge(status):
    badges = {
        "WIN": "WIN",
        "LOSS": "LOSS",
        "BREAKEVEN": "BREAKEVEN",
        "OPEN": "OPEN",
    }
    return badges.get(status, status)


def signal_label(signal):
    labels = {
        "BUY CALL": "BUY CALL",
        "BUY PUT": "BUY PUT",
        "MARKET CLOSED / WAIT": "MARKET CLOSED",
        "WAIT": "WAIT",
    }
    return labels.get(signal, signal)


def quality_summary(result):
    reasons = " ".join(result.get("reasons", [])).lower()
    return {
        "VWAP": "PASS" if "vwap" in reasons else "WAIT",
        "EMA": "PASS" if "ema" in reasons else "WAIT",
        "RSI": "PASS" if "rsi" in reasons else "WAIT",
        "Volume": "PASS" if "volume" in reasons else "WAIT",
        "Breakout": "PASS" if "breakout" in reasons or "breakdown" in reasons else "WAIT",
    }


def configure_page():
    st.set_page_config(page_title="Option Beacon", layout="wide")
    st_autorefresh(interval=60000, key="option_beacon_refresh")
    st.markdown(
        """
        <style>
        .main { background-color: #050505; }
        h1, h2, h3 { letter-spacing: 0; }
        div[data-testid="stMetric"] {
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 8px;
            padding: 0.75rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header():
    st.title("Option Beacon")
    st.subheader("Real-Time Options Trade Intelligence")

    market_status = "Market Open" if is_market_open_now() else "Market Closed"
    refreshed_at = eastern_now().strftime("%Y-%m-%d %I:%M:%S %p ET")
    st.caption(f"{market_status} | Last refreshed: {refreshed_at} | Auto-refresh: 1 minute")
    st.warning("Paper-trading dashboard only. Not financial advice.")

    if not twilio_configured(st.secrets):
        st.info("SMS alerts are off until Twilio secrets are added in Streamlit.")


def scan_symbols():
    current_prices = {}
    latest_results = {}

    for symbol in SYMBOLS:
        result = generate_signal(symbol)

        if result is None:
            continue

        latest_results[symbol] = result
        current_prices[symbol] = result.get("price", 0)

        added, row = add_new_signal(result)
        if added and result["signal"] in BUY_SIGNALS:
            sent, alert_status = send_trade_alert(result, st.secrets)
            mark_alert_status(row, sent=sent, status=alert_status)

    history = update_open_signals(current_prices)
    return latest_results, current_prices, history


def render_signal_card(symbol, result):
    with st.container(border=True):
        st.markdown(f"### {symbol}")

        if result is None:
            st.error("No data returned.")
            return

        signal = result.get("signal", "UNKNOWN")
        price = result.get("price", 0)
        confidence = result.get("confidence", 0)

        st.metric("Signal", signal_label(signal))
        st.metric("Price", f"${price:.2f}")

        if "confidence" in result:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Score", f"{confidence}%")
            c2.metric("Grade", setup_grade(confidence))
            c3.metric("Call", result.get("call_score", ""))
            c4.metric("Put", result.get("put_score", ""))

        if signal in BUY_SIGNALS:
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
            reasons = result.get("reasons") or ["No strong setup yet"]
            for reason in reasons:
                st.write(f"- {reason}")


def render_current_scanner(latest_results):
    st.subheader("Current Scanner")
    columns = st.columns(len(SYMBOLS))

    for column, symbol in zip(columns, SYMBOLS):
        with column:
            render_signal_card(symbol, latest_results.get(symbol))


def render_performance(history):
    stats = calculate_performance(history)

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


def render_symbol_stats(history):
    st.subheader("Symbol Stats")
    columns = st.columns(len(SYMBOLS))

    for column, symbol in zip(columns, SYMBOLS):
        symbol_stats = calculate_symbol_stats(history, symbol)
        with column:
            with st.container(border=True):
                st.markdown(f"### {symbol}")
                a, b, c = st.columns(3)
                a.metric("Signals", symbol_stats["signals"])
                b.metric("Win Rate", f"{symbol_stats['win_rate']:.2f}%")
                c.metric("Profit Factor", f"{symbol_stats['profit_factor']:.2f}")


def render_open_trades(history, current_prices):
    st.subheader("Open Trades")
    open_trades = history[history["status"] == "OPEN"]

    if len(open_trades) == 0:
        st.info("No open trades.")
        return

    rows = []
    for _, row in open_trades.iterrows():
        symbol = row["symbol"]
        current_price = current_prices.get(symbol)
        live_pnl = round(open_trade_pnl(row, current_price), 3) if current_price else ""

        rows.append(
            {
                "Time": row["timestamp"],
                "Symbol": symbol,
                "Signal": row["signal"],
                "Entry": row["entry"],
                "Current": round(current_price, 2) if current_price else "",
                "Stop": row["stop"],
                "Target": row["target"],
                "Live P/L %": live_pnl,
                "Status": status_badge(row["status"]),
            }
        )

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def render_signal_history(history):
    st.subheader("Signal History")

    if len(history) == 0:
        st.info("No BUY signals logged yet.")
        return

    display_history = history.copy()
    display_history["status"] = display_history["status"].apply(status_badge)
    st.dataframe(
        display_history.tail(50).sort_index(ascending=False),
        use_container_width=True,
        hide_index=True,
    )


def main():
    configure_page()
    render_header()

    latest_results, current_prices, history = scan_symbols()

    render_current_scanner(latest_results)
    st.divider()
    render_performance(history)
    st.divider()
    render_symbol_stats(history)
    st.divider()
    render_open_trades(history, current_prices)
    st.divider()
    render_signal_history(history)
    st.caption("Option Beacon (c) 2026")


try:
    main()
except Exception as e:
    st.error("Scanner Error")
    st.exception(e)
