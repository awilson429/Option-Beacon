from datetime import time

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from optionbeacon_alerts import send_trade_alert, twilio_configured
from optionbeacon_history import add_new_signal, eastern_now, mark_alert_status, update_open_signals
from optionbeacon_live import generate_signal
from optionbeacon_stats import calculate_performance, calculate_symbol_stats, open_trade_pnl


ETF_SYMBOLS = ["SPY", "QQQ", "IWM", "DIA"]
STOCK_SYMBOLS = ["NVDA", "TSLA", "AAPL", "AMD"]
SYMBOL_GROUPS = {
    "ETF Scanner": ETF_SYMBOLS,
    "Single Stock Scanner": STOCK_SYMBOLS,
}
SYMBOLS = ETF_SYMBOLS + STOCK_SYMBOLS
BUY_SIGNALS = {"BUY CALL", "BUY PUT"}
LOGO_URL = "https://img1.wsimg.com/isteam/ip/3334c900-83eb-4af4-9363-381bdd4d9924/OptionBeaconLLC%20Logo%20V2.png"


def is_market_open_now():
    now = eastern_now()

    try:
        import pandas_market_calendars as mcal

        nyse = mcal.get_calendar("NYSE")
        schedule = nyse.schedule(start_date=now.date(), end_date=now.date())

        if schedule.empty:
            return False

        market_open = schedule.iloc[0]["market_open"].tz_convert("America/New_York")
        market_close = schedule.iloc[0]["market_close"].tz_convert("America/New_York")
        return market_open <= pd.Timestamp(now) < market_close
    except Exception:
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


def signal_class(signal):
    if signal == "BUY CALL":
        return "signal-call"
    if signal == "BUY PUT":
        return "signal-put"
    return "signal-wait"


def symbol_category(symbol):
    if symbol in ETF_SYMBOLS:
        return "ETF"
    if symbol in STOCK_SYMBOLS:
        return "Stock"
    return "Other"


def filter_history_by_symbols(history, symbols):
    return history[history["symbol"].isin(symbols)]


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
        @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&family=Source+Sans+3:wght@400;600;700&display=swap');

        :root {
            --ob-bg: #050505;
            --ob-panel: #101010;
            --ob-panel-soft: #151515;
            --ob-border: rgba(255, 255, 255, 0.12);
            --ob-border-strong: rgba(255, 255, 255, 0.22);
            --ob-text: #f7f7f2;
            --ob-muted: #a9aaa5;
            --ob-green: #2fd37a;
            --ob-red: #ff5d5d;
            --ob-gold: #d8b35a;
        }

        html, body, [data-testid="stAppViewContainer"] {
            background:
                radial-gradient(circle at top right, rgba(216, 179, 90, 0.10), transparent 28rem),
                var(--ob-bg);
            color: var(--ob-text);
            font-family: 'Source Sans 3', sans-serif;
        }

        [data-testid="stHeader"] {
            background: transparent;
        }

        .block-container {
            max-width: 1240px;
            padding-top: 2rem;
            padding-bottom: 2rem;
        }

        h1, h2, h3 {
            letter-spacing: 0;
        }

        h1, .brand-title {
            font-family: 'Playfair Display', Georgia, serif;
        }

        h2, h3 {
            font-family: 'Source Sans 3', sans-serif;
            font-weight: 700;
        }

        [data-testid="stMarkdownContainer"] p {
            color: var(--ob-muted);
        }

        .brand-shell {
            border: 1px solid var(--ob-border-strong);
            border-radius: 8px;
            padding: 1.15rem 1.25rem;
            background: linear-gradient(135deg, rgba(255, 255, 255, 0.08), rgba(255, 255, 255, 0.02));
            margin-bottom: 1rem;
        }

        .brand-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
        }

        .brand-left {
            display: flex;
            align-items: center;
            gap: 1rem;
            min-width: 0;
            flex: 1 1 auto;
        }

        .brand-logo {
            width: 88px;
            height: 88px;
            object-fit: contain;
            background: #ffffff;
            border: 1px solid rgba(255, 255, 255, 0.20);
            border-radius: 8px;
            padding: 0;
            flex: 0 0 auto;
        }

        .brand-copy {
            align-items: center;
            display: flex;
            flex-direction: column;
            justify-content: center;
            min-width: 0;
            text-align: center;
        }

        .brand-title {
            color: var(--ob-text);
            font-size: clamp(2rem, 3.7vw, 4.2rem);
            font-family: 'Playfair Display', Georgia, serif;
            font-weight: 900;
            line-height: 0.95;
            margin: 0;
            white-space: nowrap;
        }

        .brand-subtitle {
            color: var(--ob-muted);
            font-size: clamp(0.78rem, 1.7vw, 1rem);
            margin-top: 0.45rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            white-space: nowrap;
        }

        .status-strip {
            display: flex;
            flex-direction: column;
            gap: 0.55rem;
            align-items: flex-end;
            justify-content: center;
            flex: 0 0 auto;
        }

        .status-primary,
        .status-secondary {
            display: flex;
            flex-wrap: wrap;
            gap: 0.55rem;
            justify-content: flex-end;
        }

        .pill, .signal-pill {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            border-radius: 999px;
            border: 1px solid var(--ob-border-strong);
            padding: 0.38rem 0.75rem;
            font-size: 0.82rem;
            font-weight: 700;
            letter-spacing: 0.04em;
            text-transform: uppercase;
            color: var(--ob-text);
            background: rgba(255, 255, 255, 0.04);
            white-space: nowrap;
        }

        .pill-market {
            font-size: 0.95rem;
            min-width: 14.5rem;
            padding: 0.52rem 1.15rem;
        }

        .pill-secondary {
            font-size: 0.74rem;
            padding: 0.3rem 0.65rem;
        }

        .pill-open {
            border-color: rgba(47, 211, 122, 0.55);
            color: var(--ob-green);
        }

        .pill-closed {
            border-color: rgba(255, 255, 255, 0.18);
            color: var(--ob-muted);
        }

        .pill-sms {
            border-color: rgba(216, 179, 90, 0.55);
            color: var(--ob-gold);
        }

        .signal-pill {
            margin: 0.2rem 0 0.8rem;
            width: 100%;
            min-height: 2.45rem;
            font-size: 1rem;
        }

        .signal-call {
            border-color: rgba(47, 211, 122, 0.75);
            color: var(--ob-green);
            background: rgba(47, 211, 122, 0.09);
        }

        .signal-put {
            border-color: rgba(255, 93, 93, 0.75);
            color: var(--ob-red);
            background: rgba(255, 93, 93, 0.09);
        }

        .signal-wait {
            border-color: rgba(255, 255, 255, 0.18);
            color: var(--ob-muted);
        }

        .section-title {
            color: var(--ob-text);
            font-size: 2.25rem;
            font-weight: 700;
            letter-spacing: 0;
            line-height: 1.15;
            margin: 0.35rem 0 0.15rem;
        }

        .section-kicker {
            color: var(--ob-muted);
            font-size: 0.95rem;
            letter-spacing: 0.04em;
            margin: 0 0 1.1rem;
            text-transform: uppercase;
        }

        .section-subtitle {
            align-items: center;
            background: rgba(255, 255, 255, 0.045);
            border: 1px solid var(--ob-border);
            border-left: 6px solid var(--ob-gold);
            border-radius: 8px;
            color: var(--ob-text);
            display: flex;
            font-size: 1.55rem;
            font-weight: 700;
            justify-content: space-between;
            letter-spacing: 0;
            line-height: 1.2;
            margin: 1.2rem 0 0.8rem;
            padding: 0.9rem 1rem;
        }

        .section-count {
            color: var(--ob-muted);
            font-size: 0.78rem;
            font-weight: 700;
            letter-spacing: 0.06em;
            text-transform: uppercase;
        }

        .content-section {
            margin: 0.25rem 0 1rem;
        }

        .content-title {
            color: var(--ob-text);
            font-size: 1.75rem;
            font-weight: 700;
            line-height: 1.2;
            margin: 0;
        }

        .content-kicker {
            color: var(--ob-muted);
            font-size: 0.9rem;
            letter-spacing: 0.04em;
            margin-top: 0.2rem;
            text-transform: uppercase;
        }

        .notice {
            border: 1px solid var(--ob-border);
            border-radius: 8px;
            color: var(--ob-muted);
            font-size: 0.95rem;
            margin: 0.75rem 0 1.25rem;
            padding: 0.75rem 0.9rem;
        }

        .notice-warning {
            background: rgba(216, 179, 90, 0.08);
            border-color: rgba(216, 179, 90, 0.28);
            color: #d9c385;
        }

        .notice-info {
            background: rgba(255, 255, 255, 0.035);
        }

        .empty-state {
            background: rgba(255, 255, 255, 0.035);
            border: 1px dashed var(--ob-border-strong);
            border-radius: 8px;
            color: var(--ob-muted);
            padding: 1rem;
            text-align: center;
        }

        .ticker-title {
            color: var(--ob-text);
            font-size: 1.28rem;
            font-weight: 700;
            line-height: 1.2;
            margin: 0 0 0.65rem;
        }

        .price-metric {
            background: rgba(255, 255, 255, 0.035);
            border: 1px solid var(--ob-border);
            border-radius: 8px;
            margin-bottom: 0.75rem;
            padding: 0.75rem;
        }

        .price-label {
            color: var(--ob-muted);
            font-size: 0.82rem;
            font-weight: 700;
            letter-spacing: 0.04em;
            text-transform: uppercase;
        }

        .price-value {
            color: var(--ob-text);
            font-size: 1.45rem;
            font-weight: 700;
            line-height: 1.2;
            margin-top: 0.15rem;
        }

        div[data-testid="stVerticalBlockBorderWrapper"] {
            border-color: var(--ob-border);
            border-radius: 8px;
            background: linear-gradient(180deg, rgba(255,255,255,0.055), rgba(255,255,255,0.018));
        }

        div[data-testid="stMetric"] {
            background: rgba(255, 255, 255, 0.035);
            border: 1px solid var(--ob-border);
            border-radius: 8px;
            padding: 0.75rem;
        }

        div[data-testid="stMetricValue"] {
            color: var(--ob-text);
            font-weight: 700;
        }

        div[data-testid="stMetricLabel"] {
            color: var(--ob-muted);
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }

        .stAlert {
            border-radius: 8px;
        }

        [data-testid="stDataFrame"] {
            border: 1px solid var(--ob-border);
            border-radius: 8px;
            overflow: hidden;
        }

        hr {
            border-color: rgba(255, 255, 255, 0.10);
        }

        .footer-line {
            color: var(--ob-muted);
            font-size: 0.9rem;
            text-align: center;
            padding: 1rem 0 0.4rem;
        }

        .footer-line a {
            color: var(--ob-text);
            text-decoration: none;
            border-bottom: 1px solid var(--ob-border-strong);
        }

        @media (max-width: 760px) {
            .brand-row {
                align-items: flex-start;
                flex-direction: column;
            }

            .status-strip {
                align-items: flex-start;
            }

            .status-primary,
            .status-secondary {
                justify-content: flex-start;
            }

            .pill-market {
                min-width: 0;
            }

            .brand-logo {
                width: 72px;
                height: 72px;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def app_access_configured():
    return bool(st.secrets.get("APP_ACCESS_CODE"))


def require_app_access():
    expected_code = st.secrets.get("APP_ACCESS_CODE")

    if not expected_code:
        return True

    if st.session_state.get("app_access_granted"):
        return True

    st.markdown(
        f"""
        <div class="brand-shell">
            <div class="brand-row">
                <div class="brand-left">
                    <img class="brand-logo" src="{LOGO_URL}" alt="Option Beacon logo" />
                    <div class="brand-copy">
                        <div class="brand-title">Option Beacon</div>
                        <div class="brand-subtitle">Private Scanner Access</div>
                    </div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    entered_code = st.text_input("Access code", type="password")

    if st.button("Enter", type="primary"):
        if entered_code == expected_code:
            st.session_state["app_access_granted"] = True
            st.rerun()
        else:
            st.error("Invalid access code.")

    st.stop()


def render_header():
    market_open = is_market_open_now()
    market_status = "Market Open" if market_open else "Market Closed"
    market_class = "pill-open" if market_open else "pill-closed"
    refreshed_at = eastern_now().strftime("%Y-%m-%d %I:%M:%S %p ET")
    sms_status = "SMS On" if twilio_configured(st.secrets) else "SMS Off"
    access_status = "Private" if app_access_configured() else "Public"

    st.markdown(
        f"""
        <div class="brand-shell">
            <div class="brand-row">
                <div class="brand-left">
                    <img class="brand-logo" src="{LOGO_URL}" alt="Option Beacon logo" />
                    <div class="brand-copy">
                        <div class="brand-title">Option Beacon</div>
                        <div class="brand-subtitle">ETF + Single Stock Scanner</div>
                    </div>
                </div>
                <div class="status-strip">
                    <div class="status-primary">
                        <span class="pill pill-market {market_class}">{market_status}</span>
                    </div>
                    <div class="status-secondary">
                        <span class="pill pill-secondary">Refresh 1 min</span>
                        <span class="pill pill-secondary pill-sms">{sms_status}</span>
                        <span class="pill pill-secondary">{access_status}</span>
                    </div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.caption(f"Last refreshed: {refreshed_at}")
    st.markdown(
        '<div class="notice notice-warning">Paper-trading dashboard only. Not financial advice.</div>',
        unsafe_allow_html=True,
    )

    if not twilio_configured(st.secrets):
        st.markdown(
            '<div class="notice notice-info">SMS alerts are off until Twilio secrets are added in Streamlit.</div>',
            unsafe_allow_html=True,
        )


def render_section_header(title, kicker=None):
    kicker_html = f'<div class="content-kicker">{kicker}</div>' if kicker else ""
    st.markdown(
        f'<div class="content-section"><div class="content-title">{title}</div>{kicker_html}</div>',
        unsafe_allow_html=True,
    )


def render_empty_state(message):
    st.markdown(f'<div class="empty-state">{message}</div>', unsafe_allow_html=True)


def scan_symbols():
    current_prices = {}
    latest_results = {}
    market_open = is_market_open_now()

    for symbol in SYMBOLS:
        result = generate_signal(symbol)

        if result is None:
            continue

        if not market_open:
            result = {**result, "signal": "MARKET CLOSED / WAIT"}

        latest_results[symbol] = result
        current_prices[symbol] = result.get("price", 0)

        if market_open:
            added, row = add_new_signal(result)
            if added and result["signal"] in BUY_SIGNALS:
                sent, alert_status = send_trade_alert(result, st.secrets)
                mark_alert_status(row, sent=sent, status=alert_status)

    history = update_open_signals(current_prices)
    return latest_results, current_prices, history


def render_signal_card(symbol, result):
    with st.container(border=True):
        st.markdown(f'<div class="ticker-title">{symbol}</div>', unsafe_allow_html=True)

        if result is None:
            st.error("No data returned.")
            return

        signal = result.get("signal", "UNKNOWN")
        price = result.get("price", 0)
        confidence = result.get("confidence", 0)

        st.markdown(
            f'<div class="signal-pill {signal_class(signal)}">{signal_label(signal)}</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f"""
            <div class="price-metric">
                <div class="price-label">Price</div>
                <div class="price-value">${price:.2f}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

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
    st.markdown('<div class="section-title">Scanner</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-kicker">Real-time signal groups</div>',
        unsafe_allow_html=True,
    )
    for group_name, symbols in SYMBOL_GROUPS.items():
        st.markdown(
            f'<div class="section-subtitle"><span>{group_name}</span>'
            f'<span class="section-count">{len(symbols)} Symbols</span></div>',
            unsafe_allow_html=True,
        )
        for row_start in range(0, len(symbols), 2):
            columns = st.columns(2)
            for column, symbol in zip(columns, symbols[row_start:row_start + 2]):
                with column:
                    render_signal_card(symbol, latest_results.get(symbol))


def render_performance(history):
    stats = calculate_performance(history)

    render_section_header("Performance", "Overall signal journal")
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

    st.markdown(
        '<div class="section-subtitle"><span>Group Performance</span>'
        '<span class="section-count">ETF vs Stock</span></div>',
        unsafe_allow_html=True,
    )
    group_columns = st.columns(2)
    for column, (label, symbols) in zip(group_columns, SYMBOL_GROUPS.items()):
        group_stats = calculate_performance(filter_history_by_symbols(history, symbols))
        with column:
            with st.container(border=True):
                st.markdown(f"### {label}")
                a, b, c = st.columns(3)
                a.metric("Signals", group_stats["total"])
                b.metric("Win Rate", f"{group_stats['win_rate']:.2f}%")
                c.metric("Profit Factor", f"{group_stats['profit_factor']:.2f}")


def render_symbol_stats(history):
    render_section_header("Symbol Stats", "Performance by ticker")
    for group_name, symbols in SYMBOL_GROUPS.items():
        st.markdown(
            f'<div class="section-subtitle"><span>{group_name}</span>'
            f'<span class="section-count">{len(symbols)} Symbols</span></div>',
            unsafe_allow_html=True,
        )
        for row_start in range(0, len(symbols), 2):
            columns = st.columns(2)
            for column, symbol in zip(columns, symbols[row_start:row_start + 2]):
                symbol_stats = calculate_symbol_stats(history, symbol)
                with column:
                    with st.container(border=True):
                        st.markdown(f"### {symbol}")
                        a, b, c = st.columns(3)
                        a.metric("Signals", symbol_stats["signals"])
                        b.metric("Win Rate", f"{symbol_stats['win_rate']:.2f}%")
                        c.metric("Profit Factor", f"{symbol_stats['profit_factor']:.2f}")


def render_open_trades(history, current_prices):
    render_section_header("Open Trades", "Active paper setups")
    open_trades = history[history["status"] == "OPEN"]

    if len(open_trades) == 0:
        render_empty_state("No open trades.")
        return

    rows = []
    for _, row in open_trades.iterrows():
        symbol = row["symbol"]
        current_price = current_prices.get(symbol)
        live_pnl = round(open_trade_pnl(row, current_price), 3) if current_price else ""

        rows.append(
            {
                "Time": row["timestamp"],
                "Group": symbol_category(symbol),
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
    render_section_header("Signal History", "Most recent logged buy signals")

    if len(history) == 0:
        render_empty_state("No BUY signals logged yet.")
        return

    display_history = history.copy()
    display_history["group"] = display_history["symbol"].apply(symbol_category)
    display_history["status"] = display_history["status"].apply(status_badge)
    st.dataframe(
        display_history.tail(50).sort_index(ascending=False),
        use_container_width=True,
        hide_index=True,
    )


def main():
    configure_page()
    require_app_access()
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
    st.markdown(
        '<div class="footer-line">Option Beacon LLC - '
        '<a href="https://option-beacon.com" target="_blank">option-beacon.com</a></div>',
        unsafe_allow_html=True,
    )


try:
    main()
except Exception as e:
    st.error("Scanner Error")
    st.exception(e)
