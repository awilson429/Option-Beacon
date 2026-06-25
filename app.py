from datetime import time
from html import escape

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from optionbeacon_history import add_high_score_snapshot, eastern_now, load_high_score_history
from optionbeacon_live import generate_signal
from optionbeacon_snapshot import load_latest_results


ETF_SYMBOLS = ["SPY", "QQQ", "IWM", "DIA"]
STOCK_SYMBOLS = ["NVDA", "TSLA", "AAPL", "AMD"]
SYMBOL_GROUPS = {
    "ETF Scanner": ETF_SYMBOLS,
    "Single Stock Scanner": STOCK_SYMBOLS,
}
SYMBOLS = ETF_SYMBOLS + STOCK_SYMBOLS
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


def signal_label(signal):
    labels = {
        "BUY CALL": "BUY CALL",
        "BUY PUT": "BUY PUT",
        "BULLISH SETUP": "BULLISH SETUP",
        "BEARISH SETUP": "BEARISH SETUP",
        "MARKET CLOSED / WAIT": "MARKET CLOSED",
        "WAIT": "WATCHLIST",
        "WATCHLIST": "WATCHLIST",
        "DATA UNAVAILABLE": "DATA UNAVAILABLE",
    }
    return labels.get(signal, signal)


def signal_class(signal):
    if signal in ["BUY CALL", "BULLISH SETUP"]:
        return "signal-call"
    if signal in ["BUY PUT", "BEARISH SETUP"]:
        return "signal-put"
    return "signal-wait"


def quality_summary(result):
    if any(key in result for key in ["trend_score", "momentum_score", "volume_score"]):
        return {
            "Trend": f"{result.get('trend_score', 0)}/25",
            "Momentum": f"{result.get('momentum_score', 0)}/20",
            "Volume": f"{result.get('volume_score', 0)}/20",
            "Volatility": f"{result.get('volatility_score', 0)}/15",
            "Price Action": f"{result.get('price_action_score', 0)}/20",
        }

    reasons = " ".join(result.get("reasons", [])).lower()
    return {
        "Trend": "PASS" if "ema" in reasons else "WAIT",
        "Momentum": "PASS" if "rsi" in reasons else "WAIT",
        "Volume": "PASS" if "volume" in reasons else "WAIT",
        "Volatility": "WAIT",
        "Price Action": "PASS" if "breakout" in reasons or "breakdown" in reasons else "WAIT",
    }


def score_value(result, key):
    try:
        return int(result.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0


def opportunity_rows(latest_results, direction, limit=3):
    score_key = "bullish_score" if direction == "Bullish" else "bearish_score"
    signal_name = "BULLISH SETUP" if direction == "Bullish" else "BEARISH SETUP"
    rows = []

    for symbol, result in latest_results.items():
        if not result or result.get("signal") == "DATA UNAVAILABLE":
            continue

        score = score_value(result, score_key)
        if score <= 0:
            continue

        rows.append(
            {
                "symbol": symbol,
                "score": score,
                "signal": result.get("signal", "WATCHLIST"),
                "is_active": result.get("signal") == signal_name,
                "price": result.get("price"),
                "quality": result.get("quality", setup_grade(score)),
                "reasons": result.get("reasons", []),
            }
        )

    return sorted(rows, key=lambda row: (row["is_active"], row["score"]), reverse=True)[:limit]


def configure_page():
    st.set_page_config(page_title="Option Beacon", layout="wide")
    st_autorefresh(interval=60000, key="option_beacon_refresh")
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@500;600;700&family=Source+Sans+3:wght@400;600;700&display=swap');

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
            font-family: 'Orbitron', 'Source Sans 3', sans-serif;
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
            font-family: 'Orbitron', 'Source Sans 3', sans-serif;
            font-size: clamp(1.65rem, 3vw, 3.4rem);
            font-weight: 600;
            letter-spacing: 0.18em;
            line-height: 1;
            margin: 0;
            text-transform: uppercase;
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

        .pill-stack {
            flex-direction: column;
            gap: 0.05rem;
            line-height: 1.05;
        }

        .pill-subtext {
            color: var(--ob-muted);
            font-size: 0.64rem;
            font-weight: 600;
            letter-spacing: 0;
            text-transform: none;
        }

        .pill-open {
            border-color: rgba(47, 211, 122, 0.55);
            color: var(--ob-green);
        }

        .pill-closed {
            border-color: rgba(255, 255, 255, 0.18);
            color: var(--ob-muted);
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

        .opportunity-row {
            align-items: center;
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
            display: grid;
            gap: 0.75rem;
            grid-template-columns: minmax(4rem, 0.8fr) minmax(5rem, 0.8fr) minmax(5rem, 0.8fr) 1fr;
            padding: 0.75rem 0;
        }

        .opportunity-row:last-child {
            border-bottom: 0;
        }

        .opportunity-symbol {
            color: var(--ob-text);
            font-size: 1.2rem;
            font-weight: 700;
        }

        .opportunity-score {
            color: var(--ob-gold);
            font-size: 1.15rem;
            font-weight: 700;
        }

        .opportunity-meta {
            color: var(--ob-muted);
            font-size: 0.88rem;
        }

        .opportunity-reason {
            color: var(--ob-muted);
            font-size: 0.92rem;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
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

            .brand-left {
                gap: 1.25rem;
            }

            .brand-title {
                font-size: clamp(1.35rem, 6vw, 2rem);
                letter-spacing: 0.12em;
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

            .opportunity-row {
                grid-template-columns: 1fr 1fr;
            }

            .opportunity-reason {
                grid-column: 1 / -1;
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
                        <span class="pill pill-secondary pill-stack">
                            <span>Refresh 1 min</span>
                            <span class="pill-subtext">Last refreshed {refreshed_at}</span>
                        </span>
                        <span class="pill pill-secondary">{access_status}</span>
                    </div>
                </div>
            </div>
        </div>
        """,
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


@st.cache_data(ttl=60, show_spinner=False)
def cached_generate_signal(symbol):
    try:
        return generate_signal(symbol), ""
    except Exception as exc:
        return None, str(exc)


def scan_symbols():
    snapshot_results, snapshot_time = load_latest_results()
    if snapshot_results:
        return snapshot_results, load_high_score_history(), snapshot_time

    latest_results = {}
    market_open = is_market_open_now()

    for symbol in SYMBOLS:
        result, error = cached_generate_signal(symbol)

        if result is None:
            reason = f"Data unavailable: {error}" if error else "Data unavailable: not enough recent 5-minute candles returned."
            latest_results[symbol] = {
                "symbol": symbol,
                "signal": "DATA UNAVAILABLE",
                "price": None,
                "confidence": 0,
                "bullish_score": 0,
                "bearish_score": 0,
                "call_score": "",
                "put_score": "",
                "reasons": [reason],
            }
            continue

        if not market_open and result.get("signal") != "DATA UNAVAILABLE":
            result = {**result, "signal": "MARKET CLOSED / WAIT"}

        latest_results[symbol] = result

        if market_open and result.get("signal") != "MARKET CLOSED / WAIT":
            add_high_score_snapshot(result)

    history = load_high_score_history()
    return latest_results, history, None


def render_opportunity_list(title, rows):
    with st.container(border=True):
        st.markdown(f"### {title}")

        if not rows:
            render_empty_state("No scored opportunities yet.")
            return

        for row in rows:
            price = row.get("price")
            price_label = f"${price:.2f}" if price else "N/A"
            status = escape("Active" if row["is_active"] else signal_label(row["signal"]))
            reason = escape(row["reasons"][0] if row["reasons"] else "No strong reason yet")
            symbol = escape(row["symbol"])
            quality = escape(row["quality"])
            st.markdown(
                f"""
                <div class="opportunity-row">
                    <div class="opportunity-symbol">{symbol}</div>
                    <div class="opportunity-score">{row["score"]}/100</div>
                    <div class="opportunity-meta">{price_label}<br>{quality}</div>
                    <div class="opportunity-reason">{status} - {reason}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def render_top_opportunities(latest_results):
    render_section_header("Top Opportunities", "Highest-scoring bullish and bearish setups")
    bullish_rows = opportunity_rows(latest_results, "Bullish")
    bearish_rows = opportunity_rows(latest_results, "Bearish")
    bullish_column, bearish_column = st.columns(2)

    with bullish_column:
        render_opportunity_list("Top Bullish", bullish_rows)

    with bearish_column:
        render_opportunity_list("Top Bearish", bearish_rows)


def render_score_guide():
    render_section_header("Score Guide", "How to read bullish and bearish setup scores")
    guide_rows = [
        {
            "Score Range": "90-100",
            "Meaning": "High-probability setup",
            "Action": "Alert-worthy. Review the setup, price levels, and risk before paper trading.",
        },
        {
            "Score Range": "80-89",
            "Meaning": "Strong watchlist candidate",
            "Action": "Worth watching closely. Wait for confirmation or a stronger score before acting.",
        },
        {
            "Score Range": "70-79",
            "Meaning": "Developing setup",
            "Action": "Early signal only. Monitor trend, volume, and price action.",
        },
        {
            "Score Range": "Below 70",
            "Meaning": "Weak or mixed setup",
            "Action": "Usually no action. Conditions are not aligned enough.",
        },
    ]
    st.dataframe(pd.DataFrame(guide_rows), use_container_width=True, hide_index=True)
    st.markdown(
        '<div class="notice notice-info">Bullish and bearish scores are decision-support signals, not automatic trade instructions. A higher score means more scanner conditions are aligned.</div>',
        unsafe_allow_html=True,
    )


def render_signal_card(symbol, result):
    with st.container(border=True):
        st.markdown(f'<div class="ticker-title">{symbol}</div>', unsafe_allow_html=True)

        if result is None:
            st.error("No data returned.")
            return

        signal = result.get("signal", "UNKNOWN")
        price = result.get("price")
        confidence = result.get("confidence", 0)
        bias = result.get("bias", "Neutral")
        quality = result.get("quality", setup_grade(confidence))

        st.markdown(
            f'<div class="signal-pill {signal_class(signal)}">{signal_label(signal)}</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f"""
            <div class="price-metric">
                <div class="price-label">Price</div>
                <div class="price-value">{f"${price:.2f}" if price else "N/A"}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if "confidence" in result:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Setup Score", f"{confidence}/100")
            c2.metric("Bias", bias)
            c3.metric("Bullish", result.get("bullish_score", result.get("call_score", "")))
            c4.metric("Bearish", result.get("bearish_score", result.get("put_score", "")))

            st.metric("Quality", quality)

        if signal in ["BULLISH SETUP", "BEARISH SETUP"]:
            st.success("High-probability setup active")
            p1, p2, p3, p4 = st.columns(4)
            p1.metric("Entry", f"${result['entry']:.2f}")
            p2.metric("Stop", f"${result['stop']:.2f}")
            p3.metric("Target", f"${result['target']:.2f}")
            p4.metric("BE", f"${result['breakeven']:.2f}")

        with st.expander("Signal Details"):
            checks = quality_summary(result)
            q1, q2, q3, q4, q5 = st.columns(5)
            q1.metric("Trend", checks["Trend"])
            q2.metric("Momentum", checks["Momentum"])
            q3.metric("Volume", checks["Volume"])
            q4.metric("Volatility", checks["Volatility"])
            q5.metric("Price Action", checks["Price Action"])

            st.markdown("**Reasons**")
            reasons = result.get("reasons") or ["No strong setup yet"]
            for reason in reasons:
                st.write(f"- {reason}")


def render_current_scanner(latest_results):
    st.markdown('<div class="section-title">Scanner</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-kicker">Real-time opportunity groups</div>',
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


def render_recent_high_scores(history):
    render_section_header("Recent High Scores", "Neutral log of scores at 80 or higher")

    if len(history) == 0:
        render_empty_state("No high-score scanner readings logged yet.")
        return

    display_history = history.copy()
    display_history = display_history.rename(
        columns={
            "timestamp": "Time",
            "symbol": "Symbol",
            "bias": "Bias",
            "score": "Score",
            "signal": "State",
            "price": "Price",
            "quality": "Quality",
            "reason": "Primary Reason",
        }
    )
    st.dataframe(
        display_history.tail(50).sort_index(ascending=False),
        use_container_width=True,
        hide_index=True,
    )


def main():
    configure_page()
    require_app_access()
    render_header()

    latest_results, high_score_history, _ = scan_symbols()

    render_top_opportunities(latest_results)
    st.divider()
    render_recent_high_scores(high_score_history)
    st.divider()
    render_score_guide()
    st.divider()
    render_current_scanner(latest_results)
    st.markdown(
        '<div class="notice notice-warning">Paper-trading dashboard only. Not financial advice.</div>',
        unsafe_allow_html=True,
    )
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
