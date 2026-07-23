import json
from datetime import time
from html import escape

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from after_hours import after_hours_focus_rows, fetch_after_hours_briefing
from finnhub_universe import (
    DEFAULT_SYMBOL_GROUPS,
    MARKET_CONTEXT_SYMBOLS,
    flatten_symbol_groups,
)
from optionbeacon_history import (
    HIGH_SCORE_THRESHOLD,
    add_high_score_snapshot,
    eastern_now,
    load_high_score_history,
)
from live_coach_alerts import (
    load_live_coach_alerts,
    symbol_alert_timeline,
    timeline_summary,
)
from live_trade_coach import coach_live_setup, coach_rows
from market_intelligence import (
    chase_risk,
    confidence_explanation,
    liquidity_quality,
    market_regime,
    sector_strength_rows,
    setup_quality,
    setup_quality_summary,
    setup_market_support,
    setup_momentum_snapshot,
    setup_sector_support,
)
from trade_journal import (
    filter_journal_rows,
    lesson_pattern_rows,
    outcome_review_rows,
    review_dashboard_rows,
    review_trend_rows,
)
from optionbeacon_live import generate_signal
from optionbeacon_snapshot import load_latest_results
from trade_management import coach_recommendation, trade_summary
from trade_replay import (
    DEFAULT_MAX_HOLD_CANDLES,
    DEFAULT_REPLAY_SYMBOLS,
    replay_summary,
    replay_symbols,
)
from trade_storage import (
    close_position,
    load_closed_positions,
    latest_recommendation,
    load_open_positions,
    load_recommendations,
    mark_partial_profit,
    record_recommendation,
    update_position_premium,
    update_position_stop,
)


SYMBOL_GROUPS = DEFAULT_SYMBOL_GROUPS
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
        "WAITING FOR CANDLE": "WAITING FOR CANDLE",
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


def opportunity_rows(latest_results, direction, limit=5):
    score_key = "bullish_score" if direction == "Bullish" else "bearish_score"
    signal_name = "BULLISH SETUP" if direction == "Bullish" else "BEARISH SETUP"
    rows = []

    for symbol, result in latest_results.items():
        if not result or result.get("signal") == "DATA UNAVAILABLE":
            continue

        if result.get("bias") != direction:
            continue

        score = score_value(result, score_key)
        if score <= 0:
            continue

        quality = setup_quality(result, latest_results)
        rows.append(
            {
                "symbol": symbol,
                "score": score,
                "quality_score": quality["score"],
                "quality_grade": quality["grade"],
                "signal": result.get("signal", "WATCHLIST"),
                "is_active": result.get("signal") == signal_name,
                "price": result.get("price"),
                "quality": result.get("quality", setup_grade(score)),
                "setup_stage": result.get("setup_stage", ""),
                "what_next": result.get("what_next", ""),
                "reasons": result.get("reasons", []),
                "result": result,
            }
        )

    return sorted(
        rows,
        key=lambda row: (row["is_active"], row["quality_score"], row["score"]),
        reverse=True,
    )[:limit]


def confirmation_count(result, latest_results=None):
    direction = result.get("bias", "Neutral")
    if direction not in ["Bullish", "Bearish"]:
        return 0

    confirmations = 0
    for _, status in factor_status(result, direction, latest_results):
        if status in ["Aligned", "Confirmed"]:
            confirmations += 1
    return confirmations


def ranked_setup_rows(latest_results, min_score=70, limit=60):
    rows = []
    for symbol, result in latest_results.items():
        if not result or result.get("signal") == "DATA UNAVAILABLE":
            continue

        bias = result.get("bias", "Neutral")
        if bias not in ["Bullish", "Bearish"]:
            continue

        score = score_value(result, "confidence")
        if score < min_score:
            continue

        sector = setup_sector_support(result, latest_results)
        quality = setup_quality(result, latest_results)
        rows.append(
            {
                "Symbol": symbol,
                "Bias": bias,
                "Quality Score": quality["score"],
                "Grade": quality["grade"],
                "Score": score,
                "Confirmations": confirmation_count(result, latest_results),
                "Sector Support": sector["status"],
                "Sector": sector["sector_etf"] or "N/A",
                "Sector Bias": sector["sector_bias"],
                "Market Support": quality["market_support"],
                "Liquidity": quality["liquidity"],
                "Chase Risk": quality["chase_risk"],
                "State": result.get("signal", "WATCHLIST"),
                "Timing": result.get("entry_timing", "Wait"),
                "Price": money(result.get("price")),
                "RVol": round(float(result.get("relative_volume") or 0), 2),
                "RSI": round(float(result.get("rsi") or 0), 1),
                "Trend": score_value(result, "trend_score"),
                "Momentum": score_value(result, "momentum_score"),
                "Volume": score_value(result, "volume_score"),
                "Volatility": score_value(result, "volatility_score"),
                "Price Action": score_value(result, "price_action_score"),
                "Why Here": setup_quality_summary(result, latest_results),
                "Primary Reason": (result.get("reasons") or [""])[0],
            }
        )

    rows.sort(key=lambda row: (row["Quality Score"], row["Score"], row["Confirmations"]), reverse=True)
    return rows[:limit]


def opportunity_grade(score):
    if score >= 95:
        return "A+"
    if score >= 90:
        return "A"
    if score >= 85:
        return "B+"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    return "Developing"


def money(value):
    try:
        return f"${float(value):.2f}" if value is not None else "N/A"
    except (TypeError, ValueError):
        return "N/A"


def factor_status(result, direction, latest_results=None):
    latest_results = latest_results or {}
    trend = score_value(result, "trend_score")
    momentum = score_value(result, "momentum_score")
    volume = score_value(result, "volume_score")
    price_action = score_value(result, "price_action_score")
    market_support = setup_market_support(result, latest_results)
    sector_support = setup_sector_support(result, latest_results)["status"]

    return [
        ("Trend", "Aligned" if trend >= 18 else "Developing"),
        ("Momentum", "Aligned" if momentum >= 14 else "Developing"),
        ("Volume", "Confirmed" if volume >= 14 else "Waiting"),
        ("Price Action", "Confirmed" if price_action >= 12 else "Waiting"),
        ("Market Support", market_support),
        ("Sector Support", sector_support),
    ]


def plan_value(plan, key, fallback=None):
    return plan.get(key) if plan and plan.get(key) is not None else fallback


def board_color_class(value):
    if value in ["Bullish", "Entry zone active", "Improving", "Aligned", "Low"]:
        return "board-green"
    if value in ["Bearish", "Avoid chasing", "Weakening", "Bias flipped", "Against", "High"]:
        return "board-red"
    return "board-muted"


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
            margin-bottom: 0.55rem;
        }

        .brand-row {
            display: flex;
            align-items: center;
            flex-direction: column;
            justify-content: space-between;
            gap: 1rem;
        }

        .brand-left {
            display: flex;
            align-items: center;
            gap: 1rem;
            justify-content: center;
            min-width: 0;
            flex: 1 1 auto;
            width: 100%;
        }

        .brand-logo {
            width: 116px;
            height: 116px;
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
            font-size: clamp(2rem, 3.65vw, 4rem);
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

        .status-shell {
            align-items: center;
            background: rgba(255, 255, 255, 0.035);
            border: 1px solid var(--ob-border);
            border-radius: 8px;
            display: flex;
            justify-content: center;
            margin: 0 0 1rem;
            padding: 0.45rem;
        }

        .status-strip {
            display: flex;
            flex-direction: row;
            flex-wrap: wrap;
            gap: 0.55rem;
            align-items: center;
            justify-content: center;
            width: 100%;
        }

        .status-primary,
        .status-secondary {
            display: flex;
            flex-wrap: wrap;
            gap: 0.55rem;
            justify-content: center;
            align-items: stretch;
        }

        .status-secondary {
            align-items: stretch;
            justify-content: center;
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
            font-size: 0.74rem;
        }

        .pill-secondary {
            font-size: 0.74rem;
            padding: 0.3rem 0.65rem;
        }

        .status-strip .pill {
            min-height: 2.25rem;
            min-width: 8.25rem;
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

        .opportunity-heading {
            background: transparent;
            border: 0;
            font-size: 1.75rem;
            font-weight: 700;
            line-height: 1.2;
            margin-bottom: 0.25rem;
            padding: 0;
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

        .coach-card {
            border: 1px solid var(--ob-border);
            border-radius: 8px;
            background: linear-gradient(180deg, rgba(255,255,255,0.055), rgba(255,255,255,0.018));
            padding: 1rem;
            margin-bottom: 0.85rem;
        }

        .coach-card-header {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 1rem;
            border-bottom: 1px solid rgba(255,255,255,0.08);
            padding-bottom: 0.75rem;
            margin-bottom: 0.75rem;
        }

        .coach-symbol {
            color: var(--ob-text);
            font-size: 1.55rem;
            font-weight: 700;
            line-height: 1.1;
        }

        .coach-grade {
            color: var(--ob-gold);
            font-size: 1.1rem;
            font-weight: 700;
            text-align: right;
        }

        .coach-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.65rem;
            margin: 0.75rem 0;
        }

        .coach-metric {
            border: 1px solid var(--ob-border);
            border-radius: 8px;
            background: rgba(255,255,255,0.035);
            padding: 0.65rem;
            min-height: 4.2rem;
        }

        .coach-label {
            color: var(--ob-muted);
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.04em;
            text-transform: uppercase;
        }

        .coach-value {
            color: var(--ob-text);
            font-size: 1.05rem;
            font-weight: 700;
            margin-top: 0.2rem;
        }

        .factor-list {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 0.45rem;
            margin: 0.75rem 0;
        }

        .factor-pill {
            border: 1px solid var(--ob-border);
            border-radius: 8px;
            color: var(--ob-muted);
            background: rgba(255,255,255,0.025);
            padding: 0.45rem 0.55rem;
            font-size: 0.86rem;
        }

        .factor-good {
            border-color: rgba(47, 211, 122, 0.35);
            color: var(--ob-green);
        }

        .factor-warn {
            border-color: rgba(216, 179, 90, 0.35);
            color: #d9c385;
        }

        .why-list {
            color: var(--ob-muted);
            margin: 0.65rem 0 0;
            padding-left: 1rem;
        }

        .why-list li {
            margin-bottom: 0.25rem;
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

        .stTabs [data-baseweb="tab-list"] {
            background: rgba(255, 255, 255, 0.035);
            border: 1px solid var(--ob-border);
            border-radius: 8px;
            gap: 0.45rem;
            padding: 0.45rem;
            margin-bottom: 1rem;
        }

        .stTabs [data-baseweb="tab"] {
            border: 1px solid var(--ob-border-strong);
            border-radius: 999px;
            color: var(--ob-muted);
            font-weight: 700;
            min-height: 2.5rem;
            padding: 0.35rem 1.2rem;
            text-transform: uppercase;
        }

        .stTabs [aria-selected="true"] {
            border-color: rgba(216, 179, 90, 0.65);
            color: var(--ob-text);
            background: rgba(216, 179, 90, 0.08);
        }

        .beacon-board {
            display: grid;
            gap: 0.65rem;
            grid-template-columns: 1.15fr 1fr 1fr;
            margin-top: 0.2rem;
        }

        .board-panel {
            background: #070707;
            border: 1px solid rgba(255, 255, 255, 0.16);
            border-radius: 8px;
            min-height: 10rem;
            overflow: hidden;
        }

        .board-panel-wide {
            grid-column: span 2;
        }

        .board-panel-full {
            grid-column: 1 / -1;
        }

        .board-header {
            align-items: center;
            background: rgba(255, 255, 255, 0.055);
            border-bottom: 1px solid rgba(255, 255, 255, 0.12);
            color: var(--ob-muted);
            display: flex;
            font-size: 0.78rem;
            font-weight: 800;
            justify-content: space-between;
            letter-spacing: 0.1em;
            padding: 0.55rem 0.7rem;
            text-transform: uppercase;
        }

        .board-body {
            padding: 0.55rem 0.7rem;
        }

        .board-row {
            align-items: center;
            border-bottom: 1px solid rgba(255, 255, 255, 0.075);
            display: grid;
            gap: 0.5rem;
            grid-template-columns: 0.7fr 1.05fr 0.6fr 0.8fr;
            min-height: 2.35rem;
            padding: 0.35rem 0;
        }

        .board-row:last-child {
            border-bottom: 0;
        }

        .board-row-compact {
            grid-template-columns: 0.7fr 1fr 0.55fr;
        }

        .board-symbol {
            color: var(--ob-text);
            font-size: 1.05rem;
            font-weight: 800;
        }

        .board-main {
            color: var(--ob-text);
            font-size: 0.93rem;
            font-weight: 700;
            line-height: 1.15;
        }

        .board-sub {
            color: var(--ob-muted);
            font-size: 0.78rem;
            line-height: 1.15;
        }

        .board-number {
            color: var(--ob-gold);
            font-size: 1rem;
            font-weight: 800;
            text-align: right;
        }

        .board-green {
            color: var(--ob-green);
        }

        .board-red {
            color: var(--ob-red);
        }

        .board-muted {
            color: var(--ob-muted);
        }

        .board-strip {
            display: grid;
            gap: 0.45rem;
            grid-template-columns: repeat(4, minmax(0, 1fr));
        }

        .board-tile {
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 8px;
            background: rgba(255, 255, 255, 0.035);
            padding: 0.55rem 0.65rem;
        }

        .board-tile-label {
            color: var(--ob-muted);
            font-size: 0.72rem;
            font-weight: 800;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }

        .board-tile-value {
            color: var(--ob-text);
            font-size: 1.2rem;
            font-weight: 800;
            margin-top: 0.15rem;
        }

        .board-note {
            color: var(--ob-muted);
            font-size: 0.85rem;
            line-height: 1.25;
            margin-top: 0.5rem;
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
                align-items: center;
                flex-direction: column;
            }

            .brand-left {
                gap: 1.25rem;
            }

            .brand-title {
                font-size: clamp(1.15rem, 5.2vw, 1.8rem);
                letter-spacing: 0.08em;
            }

            .status-strip {
                align-items: center;
            }

            .status-primary,
            .status-secondary {
                justify-content: center;
            }

            .pill-market {
                min-width: 0;
            }

            .brand-logo {
                width: 92px;
                height: 92px;
            }

            .opportunity-row {
                grid-template-columns: 1fr 1fr;
            }

            .opportunity-reason {
                grid-column: 1 / -1;
            }

            .coach-grid,
            .factor-list {
                grid-template-columns: 1fr 1fr;
            }

            .beacon-board {
                grid-template-columns: 1fr;
            }

            .board-panel-wide,
            .board-panel-full {
                grid-column: auto;
            }

            .board-strip {
                grid-template-columns: 1fr 1fr;
            }
        }

        @media (max-width: 390px) {
            .brand-left {
                gap: 0.75rem;
            }

            .brand-title {
                font-size: clamp(1rem, 4.8vw, 1.45rem);
                letter-spacing: 0.05em;
            }

            .brand-subtitle {
                font-size: 0.68rem;
                letter-spacing: 0.04em;
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
            </div>
        </div>
        <div class="status-shell">
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


def normalize_market_signal(result, market_open):
    if result.get("signal") == "MARKET CLOSED / WAIT" and market_open:
        return {**result, "signal": "WAITING FOR CANDLE"}
    if not market_open and result.get("signal") != "DATA UNAVAILABLE":
        return {**result, "signal": "MARKET CLOSED / WAIT"}
    return result


def symbol_groups_from_snapshot(snapshot_results):
    symbols = list(snapshot_results.keys())

    if len(symbols) <= len(flatten_symbol_groups(DEFAULT_SYMBOL_GROUPS)):
        return DEFAULT_SYMBOL_GROUPS

    context_symbols = [symbol for symbol in MARKET_CONTEXT_SYMBOLS if symbol in snapshot_results]
    remaining_symbols = [symbol for symbol in symbols if symbol not in context_symbols]
    bullish_symbols = [
        symbol for symbol in remaining_symbols
        if snapshot_results.get(symbol, {}).get("bias") == "Bullish"
    ]
    bearish_symbols = [
        symbol for symbol in remaining_symbols
        if snapshot_results.get(symbol, {}).get("bias") == "Bearish"
    ]
    other_symbols = [
        symbol for symbol in remaining_symbols
        if symbol not in bullish_symbols and symbol not in bearish_symbols
    ]

    if context_symbols or bullish_symbols or bearish_symbols:
        groups = {}
        if context_symbols:
            groups["Market Context"] = context_symbols
        if bullish_symbols:
            groups["Bullish Setups"] = bullish_symbols
        if bearish_symbols:
            groups["Bearish Setups"] = bearish_symbols
        if other_symbols:
            groups["Developing Setups"] = other_symbols
        return groups

    midpoint = min(25, max(1, len(symbols) // 2))
    return {
        "Top Bullish Movers": symbols[:midpoint],
        "Top Bearish Movers": symbols[midpoint:],
    }


def scan_symbols():
    market_open = is_market_open_now()
    snapshot_results, snapshot_time = load_latest_results()
    if snapshot_results:
        symbol_groups = symbol_groups_from_snapshot(snapshot_results)
        snapshot_results = {
            symbol: normalize_market_signal(result, market_open)
            for symbol, result in snapshot_results.items()
        }
        return snapshot_results, load_high_score_history(), snapshot_time, symbol_groups

    symbol_groups = DEFAULT_SYMBOL_GROUPS
    symbols = flatten_symbol_groups(symbol_groups)
    latest_results = {}

    for symbol in symbols:
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

        result = normalize_market_signal(result, market_open)

        latest_results[symbol] = result

        if market_open and result.get("signal") != "MARKET CLOSED / WAIT":
            add_high_score_snapshot(result)

    history = load_high_score_history()
    return latest_results, history, None, symbol_groups


@st.cache_data(ttl=900, show_spinner=False)
def cached_after_hours_briefing():
    return fetch_after_hours_briefing()


def render_opportunity_card(row, latest_results, high_score_history=None):
    result = row["result"]
    plan = result.get("trade_plan") or {}
    score = row["score"]
    direction = result.get("bias", "Neutral")
    coach = coach_live_setup(result)
    chase = chase_risk(result)
    sector = setup_sector_support(result, latest_results)
    quality = setup_quality(result, latest_results)
    liquidity = liquidity_quality(result)
    quality_note = setup_quality_summary(result, latest_results)
    confidence_note = confidence_explanation(result, latest_results)
    momentum = setup_momentum_snapshot(result, high_score_history)
    exit_reasons = coach.get("exit_reasons", [])
    factors = factor_status(result, direction, latest_results)
    factor_html = ""
    for label, status in factors:
        status_class = "factor-good" if status in ["Aligned", "Confirmed"] else "factor-warn"
        factor_html += (
            f'<div class="factor-pill {status_class}">'
            f'<strong>{escape(label)}</strong><br>{escape(status)}</div>'
        )

    reasons = result.get("reasons") or ["No strong reason yet"]
    reasons_html = "".join(
        f"<li>{escape(reason)}</li>" for reason in reasons[:6]
    )
    exit_reasons_html = "".join(
        f"<li>{escape(reason)}</li>" for reason in exit_reasons[:4]
    )

    entry_zone_low = money(plan_value(plan, "entry_zone_low", result.get("entry")))
    entry_zone_high = money(plan_value(plan, "entry_zone_high", result.get("entry")))
    stop = money(plan_value(plan, "technical_stop", result.get("stop")))
    target_1 = money(plan_value(plan, "target_1", result.get("target")))
    target_2 = money(plan_value(plan, "target_2"))
    target_3 = money(plan_value(plan, "target_3"))
    risk_reward = plan.get("risk_reward")
    risk_reward_label = f"{risk_reward}:1" if risk_reward else "N/A"
    contract = coach.get("contract", "N/A")

    st.markdown(
        f"""
        <div class="coach-card">
            <div class="coach-card-header">
                <div>
                    <div class="coach-symbol">{escape(row["symbol"])}</div>
                    <div class="content-kicker">{escape(direction)} {escape(contract)} idea</div>
                </div>
                <div class="coach-grade">
                    Quality: {escape(quality["grade"])}<br>
                    <span class="content-kicker">Quality {quality["score"]}/100 | Setup {score}%</span>
                </div>
            </div>
            <div class="factor-list">{factor_html}</div>
            <div class="coach-grid">
                <div class="coach-metric"><div class="coach-label">Entry Zone</div><div class="coach-value">{entry_zone_low}-{entry_zone_high}</div></div>
                <div class="coach-metric"><div class="coach-label">Stop</div><div class="coach-value">{stop}</div></div>
                <div class="coach-metric"><div class="coach-label">Target 1</div><div class="coach-value">{target_1}</div></div>
                <div class="coach-metric"><div class="coach-label">Risk/Reward</div><div class="coach-value">{risk_reward_label}</div></div>
                <div class="coach-metric"><div class="coach-label">Target 2</div><div class="coach-value">{target_2}</div></div>
                <div class="coach-metric"><div class="coach-label">Target 3</div><div class="coach-value">{target_3}</div></div>
                <div class="coach-metric"><div class="coach-label">Live Coach</div><div class="coach-value">{escape(coach["action"])}</div></div>
                <div class="coach-metric"><div class="coach-label">Exit Score</div><div class="coach-value">{coach["exit_score"]}/100</div></div>
                <div class="coach-metric"><div class="coach-label">Liquidity</div><div class="coach-value">{escape(liquidity["label"])}</div></div>
                <div class="coach-metric"><div class="coach-label">Sector</div><div class="coach-value">{escape(sector["status"])}</div></div>
            </div>
            <div class="notice notice-info"><strong>Why this is here</strong><br>{escape(quality_note)}</div>
            <div class="notice notice-info"><strong>What should I do next?</strong><br>{escape(coach["summary"])} {escape(coach["next_step"])}</div>
            <div class="notice"><strong>Sector Support: {escape(sector["status"])}</strong><br>{escape(sector["detail"])}</div>
            <div class="notice"><strong>Liquidity: {escape(liquidity["label"])}</strong><br>{escape(liquidity["detail"])}</div>
            <div class="notice"><strong>Live Read: {escape(momentum["label"])}</strong><br>{escape(momentum["detail"])}</div>
            <div class="notice"><strong>Chase Risk: {escape(chase["label"])}</strong><br>{escape(chase["reason"])}<br>{escape(confidence_note)}</div>
            <div class="content-kicker">Why?</div>
            <ul class="why-list">{reasons_html}</ul>
            <div class="content-kicker">Exit / Reversal Watch</div>
            <ul class="why-list">{exit_reasons_html}</ul>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_market_regime(latest_results):
    regime = market_regime(latest_results)
    render_section_header("Market Regime", "Simple read on whether the market supports new ideas")
    cols = st.columns(4)
    cols[0].metric("Regime", regime["regime"])
    cols[1].metric("Bullish ETFs", regime["bullish_count"])
    cols[2].metric("Bearish ETFs", regime["bearish_count"])
    cols[3].metric("Avg ETF Score", regime["average_score"])
    st.markdown(
        f'<div class="notice notice-info"><strong>{escape(regime["support"])}</strong><br>{escape(regime["best_strategy"])}</div>',
        unsafe_allow_html=True,
    )


def render_sector_strength(latest_results):
    render_section_header(
        "Sector Strength",
        "Shows whether major sectors are confirming or fighting individual setups",
    )
    rows = sector_strength_rows(latest_results)

    if not rows:
        render_empty_state("Sector ETF context has not been scanned yet.")
        return

    st.dataframe(
        pd.DataFrame(rows),
        use_container_width=True,
        hide_index=True,
    )


def render_opportunity_list(title, rows, latest_results, high_score_history=None):
    title_class = "signal-call" if "Bullish" in title else "signal-put" if "Bearish" in title else ""
    st.markdown(
        f'<div class="opportunity-heading {title_class}">{title}</div>',
        unsafe_allow_html=True,
    )

    if not rows:
        render_empty_state("No scored opportunities yet.")
        return

    for row in rows:
        render_opportunity_card(row, latest_results, high_score_history)


def render_top_opportunities(latest_results, high_score_history=None):
    render_section_header("Top Opportunities", "Highest-scoring bullish and bearish setups")
    bullish_rows = opportunity_rows(latest_results, "Bullish")
    bearish_rows = opportunity_rows(latest_results, "Bearish")
    bullish_column, bearish_column = st.columns(2)

    with bullish_column:
        render_opportunity_list("Top Bullish", bullish_rows, latest_results, high_score_history)

    with bearish_column:
        render_opportunity_list("Top Bearish", bearish_rows, latest_results, high_score_history)


def render_ranked_setup_table(latest_results):
    render_section_header(
        "Ranked Setup Screener",
        "Broader scored universe with confirmation count and factor breakdown",
    )

    min_score = st.slider(
        "Minimum score",
        min_value=50,
        max_value=95,
        value=70,
        step=5,
        help="Lower this to see more developing ideas; raise it to see only cleaner setups.",
    )
    rows = ranked_setup_rows(latest_results, min_score=min_score)

    if not rows:
        render_empty_state("No setups match the selected score filter yet.")
        return

    st.dataframe(
        pd.DataFrame(rows),
        use_container_width=True,
        hide_index=True,
    )


def render_after_hours(latest_results):
    render_section_header(
        "After Hours Briefing",
        "Earnings, market headlines, and next-session names to review after the close",
    )

    briefing = cached_after_hours_briefing()
    earnings = briefing.get("earnings") or []
    news = briefing.get("news") or []
    focus_rows = after_hours_focus_rows(latest_results, min_score=80)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Earnings Watch", len(earnings))
    c2.metric("Market Notes", len(news))
    c3.metric("Next-Session Setups", len(focus_rows))
    c4.metric("Updated", briefing.get("updated_at", "N/A").split(" ")[-3])

    if briefing.get("errors"):
        if briefing.get("key_configured"):
            error_intro = "Finnhub key detected, but one or more after-hours requests failed."
        else:
            error_intro = "FINNHUB_API_KEY is not detected in Streamlit Secrets."

        st.markdown(
            f'<div class="notice notice-warning">'
            f'<strong>Some after-hours data is unavailable.</strong><br>'
            f'{escape(error_intro)}'
            f'</div>',
            unsafe_allow_html=True,
        )
        with st.expander("After-hours data details"):
            for error in briefing.get("errors", []):
                st.write(error)

    if focus_rows:
        st.markdown(
            '<div class="opportunity-heading">Next-Session Watchlist</div>',
            unsafe_allow_html=True,
        )
        st.dataframe(pd.DataFrame(focus_rows), use_container_width=True, hide_index=True)
    else:
        render_empty_state("No 80+ score setups are ready for next-session review yet.")

    earnings_col, news_col = st.columns([1, 1.25])

    with earnings_col:
        st.markdown(
            '<div class="opportunity-heading">Earnings Calendar</div>',
            unsafe_allow_html=True,
        )
        if earnings:
            st.dataframe(
                pd.DataFrame(earnings),
                use_container_width=True,
                hide_index=True,
            )
        else:
            render_empty_state("No upcoming earnings returned yet.")

    with news_col:
        st.markdown(
            '<div class="opportunity-heading">Important Headlines</div>',
            unsafe_allow_html=True,
        )
        if news:
            display_news = pd.DataFrame(news)
            st.dataframe(
                display_news[["Time", "Source", "Headline", "Summary", "URL"]],
                use_container_width=True,
                hide_index=True,
            )
        else:
            render_empty_state("No current market headlines returned yet.")


def render_score_guide():
    render_section_header("Score Guide", "How to read bullish and bearish setup scores")
    guide_rows = [
        {
            "Score Range": "90-100",
            "Meaning": "High-probability setup",
            "Action": "Alert-worthy. Review the setup, price levels, and risk before taking action.",
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


def render_live_trade_coach(latest_results, high_score_history=None):
    render_section_header(
        "Live Trade Coach",
        "Current scanner ideas with entry, wait, and risk guidance",
    )
    rows = coach_rows(latest_results, min_score=75, history=high_score_history)

    if not rows:
        render_empty_state("No live trade ideas are ready yet.")
        return

    active_rows = [
        row for row in rows
        if row["Action"] in ["Entry zone active", "Watch for trigger", "Avoid chasing"]
    ]
    display_rows = active_rows or rows[:8]
    display_df = pd.DataFrame(display_rows)
    display_df["Price"] = pd.to_numeric(display_df["Price"], errors="coerce").round(2)

    st.dataframe(
        display_df[
            [
                "Symbol",
                "Action",
                "Bias",
                "Score",
                "Contract",
                "Price",
                "Stage",
                "Timing",
                "Coach Summary",
                "Next Step",
                "Exit Score",
                "Exit Label",
                "Chase Risk",
                "Live Read",
                "Missing",
                "Risk Note",
            ]
        ],
        use_container_width=True,
        hide_index=True,
    )

    with st.expander("Coach Details"):
        for row in display_rows[:6]:
            st.markdown(f"**{row['Symbol']} - {row['Action']} ({row['Score']}/100)**")
            st.write(f"Exit Score: {row['Exit Score']}/100 - {row['Exit Label']}")
            st.write(f"Chase Risk: {row['Chase Risk']}")
            st.write(f"Live Read: {row['Live Read']} - {row['Live Detail']}")
            st.write(f"Missing: {row['Missing']}")
            st.write(row["Coach Summary"])
            st.write(row["Next Step"])
            st.write(row["Risk Note"])


def render_beacon_board(latest_results, high_score_history=None):
    regime = market_regime(latest_results)
    coach_queue = coach_rows(latest_results, min_score=70, history=high_score_history)
    alerts = load_live_coach_alerts()
    bullish_rows = opportunity_rows(latest_results, "Bullish", limit=5)
    bearish_rows = opportunity_rows(latest_results, "Bearish", limit=5)
    risk_rows = [
        row for row in coach_queue
        if row["Chase Risk"] == "High" or int(row.get("Exit Score") or 0) >= 55
    ][:6]

    market_tiles = ""
    for symbol in ["SPY", "QQQ", "IWM", "DIA"]:
        result = latest_results.get(symbol, {})
        bias = result.get("bias", "N/A")
        score = result.get("confidence", 0)
        color = board_color_class(bias)
        market_tiles += (
            f'<div class="board-tile">'
            f'<div class="board-tile-label">{escape(symbol)}</div>'
            f'<div class="board-tile-value {color}">{escape(str(bias))}</div>'
            f'<div class="board-sub">Score {escape(str(score))}/100</div>'
            f'</div>'
        )

    coach_html = ""
    for row in coach_queue[:7]:
        action_color = board_color_class(row["Action"])
        coach_html += (
            '<div class="board-row">'
            f'<div class="board-symbol">{escape(row["Symbol"])}</div>'
            f'<div><div class="board-main {action_color}">{escape(row["Action"])}</div>'
            f'<div class="board-sub">{escape(row["Live Read"])} | {escape(row["Timing"])}</div></div>'
            f'<div class="board-number">{escape(str(row["Score"]))}</div>'
            f'<div class="board-sub">{escape(row["Chase Risk"])} chase<br>Exit {escape(str(row["Exit Score"]))}</div>'
            '</div>'
        )
    if not coach_html:
        coach_html = '<div class="board-note">No coach ideas are active yet.</div>'

    def setup_rows(rows):
        html = ""
        for row in rows:
            result = row["result"]
            plan = result.get("trade_plan") or {}
            html += (
                '<div class="board-row board-row-compact">'
                f'<div class="board-symbol">{escape(row["symbol"])}</div>'
                f'<div><div class="board-main">{escape(result.get("bias", "Neutral"))} {escape(result.get("entry_timing", "Wait"))}</div>'
                f'<div class="board-sub">Entry {money(plan_value(plan, "trigger_price", result.get("entry")))} | Stop {money(plan_value(plan, "technical_stop", result.get("stop")))}</div></div>'
                f'<div class="board-number">{escape(str(row["score"]))}</div>'
                '</div>'
            )
        return html or '<div class="board-note">No scored setups yet.</div>'

    risk_html = ""
    for row in risk_rows:
        risk_color = board_color_class(row["Chase Risk"])
        risk_html += (
            '<div class="board-row board-row-compact">'
            f'<div class="board-symbol">{escape(row["Symbol"])}</div>'
            f'<div><div class="board-main {risk_color}">{escape(row["Chase Risk"])} chase</div>'
            f'<div class="board-sub">{escape(row["Exit Label"])} | {escape(row["Action"])}</div></div>'
            f'<div class="board-number">{escape(str(row["Exit Score"]))}</div>'
            '</div>'
        )
    if not risk_html:
        risk_html = '<div class="board-note">No high chase-risk or elevated exit-score warnings.</div>'

    alert_html = ""
    if not alerts.empty:
        for _, alert in alerts.tail(6).iloc[::-1].iterrows():
            alert_html += (
                '<div class="board-row board-row-compact">'
                f'<div class="board-symbol">{escape(str(alert.get("symbol", "")))}</div>'
                f'<div><div class="board-main">{escape(str(alert.get("action", "")))}</div>'
                f'<div class="board-sub">{escape(str(alert.get("live_read", "")))} | {escape(str(alert.get("timestamp", "")))}</div></div>'
                f'<div class="board-number">{escape(str(alert.get("score", "")))}</div>'
                '</div>'
            )
    if not alert_html:
        alert_html = '<div class="board-note">No recent coach alerts logged yet.</div>'

    st.markdown(
        f"""
        <div class="beacon-board">
            <div class="board-panel board-panel-full">
                <div class="board-header"><span>Market Pulse</span><span>{escape(regime["regime"])}</span></div>
                <div class="board-body">
                    <div class="board-strip">{market_tiles}</div>
                    <div class="board-note">{escape(regime["support"])} {escape(regime["best_strategy"])}</div>
                </div>
            </div>
            <div class="board-panel board-panel-wide">
                <div class="board-header"><span>Coach Queue</span><span>What matters now</span></div>
                <div class="board-body">{coach_html}</div>
            </div>
            <div class="board-panel">
                <div class="board-header"><span>Risk Watch</span><span>Exit / chase</span></div>
                <div class="board-body">{risk_html}</div>
            </div>
            <div class="board-panel">
                <div class="board-header"><span>Top Bullish</span><span>Calls</span></div>
                <div class="board-body">{setup_rows(bullish_rows)}</div>
            </div>
            <div class="board-panel">
                <div class="board-header"><span>Top Bearish</span><span>Puts</span></div>
                <div class="board-body">{setup_rows(bearish_rows)}</div>
            </div>
            <div class="board-panel">
                <div class="board-header"><span>Recent Alerts</span><span>In-app</span></div>
                <div class="board-body">{alert_html}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_live_coach_alerts():
    render_section_header(
        "Recent Coach Alerts",
        "Meaningful setup changes logged by the scheduled scanner",
    )
    alerts = load_live_coach_alerts()

    if alerts.empty:
        render_empty_state("No coach alerts logged yet.")
        return

    display = alerts.tail(50).sort_index(ascending=False).rename(
        columns={
            "timestamp": "Time",
            "symbol": "Symbol",
            "bias": "Bias",
            "score": "Score",
            "action": "Action",
            "live_read": "Live Read",
            "exit_score": "Exit Score",
            "exit_label": "Exit Label",
            "chase_risk": "Chase Risk",
            "headline": "Headline",
            "next_step": "Next Step",
            "reason": "Reason",
        }
    )
    st.dataframe(
        display[
            [
                "Time",
                "Symbol",
                "Action",
                "Live Read",
                "Score",
                "Exit Score",
                "Chase Risk",
                "Headline",
                "Next Step",
                "Reason",
            ]
        ],
        use_container_width=True,
        hide_index=True,
    )


def render_coach_timeline():
    render_section_header(
        "Coach Timeline",
        "How a symbol's setup has changed through recent scanner reads",
    )
    alerts = load_live_coach_alerts()

    if alerts.empty:
        render_empty_state("No coach timeline yet.")
        return

    symbols = sorted(alerts["symbol"].dropna().unique())
    if not symbols:
        render_empty_state("No symbols have coach alerts yet.")
        return

    selected_symbol = st.selectbox("Symbol timeline", symbols)
    timeline = symbol_alert_timeline(alerts, symbol=selected_symbol, limit=25)
    summary = timeline_summary(alerts, symbol=selected_symbol)

    c1, c2, c3 = st.columns(3)
    c1.metric("Events", summary["events"])
    c2.metric("Latest Action", summary["latest_action"])
    c3.metric("Latest Read", summary["latest_read"])
    st.markdown(
        f'<div class="notice notice-info"><strong>{escape(summary["headline"])}</strong><br>{escape(summary["detail"])}</div>',
        unsafe_allow_html=True,
    )

    display = timeline.rename(
        columns={
            "timestamp": "Time",
            "symbol": "Symbol",
            "bias": "Bias",
            "score": "Score",
            "action": "Action",
            "live_read": "Live Read",
            "exit_score": "Exit Score",
            "exit_label": "Exit Label",
            "chase_risk": "Chase Risk",
            "next_step": "Next Step",
            "reason": "Reason",
        }
    )
    st.dataframe(
        display[
            [
                "Time",
                "Action",
                "Live Read",
                "Bias",
                "Score",
                "Exit Score",
                "Chase Risk",
                "Next Step",
                "Reason",
            ]
        ].sort_index(ascending=False),
        use_container_width=True,
        hide_index=True,
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
        setup_stage = result.get("setup_stage", "Developing")
        entry_timing = result.get("entry_timing", "Wait")
        what_next = result.get("what_next", "Wait.")
        what_next_reason = result.get("what_next_reason", "No actionable setup yet.")
        trade_plan = result.get("trade_plan", {}) or {}

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
            c3.metric("Stage", setup_stage)
            c4.metric("Timing", entry_timing)

            st.metric("Quality", quality)

            st.markdown(
                f'<div class="notice notice-info"><strong>What should I do next?</strong><br>'
                f'{escape(what_next)} {escape(what_next_reason)}</div>',
                unsafe_allow_html=True,
            )

        if signal in ["BULLISH SETUP", "BEARISH SETUP"]:
            st.success("High-probability setup active")
            p1, p2, p3, p4 = st.columns(4)
            p1.metric("Entry", f"${result['entry']:.2f}")
            p2.metric("Stop", f"${result['stop']:.2f}")
            p3.metric("Target", f"${result['target']:.2f}")
            p4.metric("BE", f"${result['breakeven']:.2f}")

        if trade_plan:
            with st.expander("Trade Plan"):
                t1, t2, t3, t4 = st.columns(4)
                t1.metric("Entry Zone", f"${trade_plan['entry_zone_low']:.2f}-${trade_plan['entry_zone_high']:.2f}")
                t2.metric("Trigger", f"${trade_plan['trigger_price']:.2f}")
                t3.metric("Invalidation", f"${trade_plan['invalidation_level']:.2f}")
                t4.metric("Max Entry", f"${trade_plan['max_entry_price']:.2f}")

                t5, t6, t7, t8 = st.columns(4)
                t5.metric("Target 1", f"${trade_plan['target_1']:.2f}")
                t6.metric("Target 2", f"${trade_plan['target_2']:.2f}")
                t7.metric("Target 3", f"${trade_plan['target_3']:.2f}")
                t8.metric("Risk/Reward", f"{trade_plan['risk_reward']}:1" if trade_plan.get("risk_reward") else "N/A")

                st.write(trade_plan.get("contract_guidance", "Use liquid contracts with tight spreads."))

        coach = coach_live_setup(result)
        if coach["action"] != "Wait":
            st.markdown(
                f'<div class="notice"><strong>Live Coach: {escape(coach["action"])}</strong><br>'
                f'{escape(coach["summary"])}<br>{escape(coach["next_step"])}<br>'
                f'Exit Score: {coach["exit_score"]}/100 - {escape(coach["exit_label"])}</div>',
                unsafe_allow_html=True,
            )

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


def render_active_trades(latest_results):
    render_section_header("Saved Trade Tracker", "Optional saved ideas and coach history")
    positions = load_open_positions()

    if not positions:
        render_empty_state("No saved trades yet. The Live Trade Coach above does not require manual entry.")
        return

    rows = []
    summary_rows = []
    recommendations = {}
    for position in positions:
        scanner_result = latest_results.get(position["symbol"], {})
        recommendation = coach_recommendation(position, scanner_result)
        previous_recommendation = latest_recommendation(position["id"])
        record_recommendation(position["id"], recommendation)
        previous_action = (
            previous_recommendation.get("coach_action")
            if previous_recommendation
            else None
        )
        recommendations[position["id"]] = recommendation
        entry_premium = position.get("entry_premium") or 0
        current_premium = position.get("current_premium") or entry_premium
        peak_premium = position.get("peak_premium") or current_premium
        contracts = position.get("contracts") or 0
        main_reason = recommendation["exit_reasons"][0] if recommendation["exit_reasons"] else ""
        summary = trade_summary(position, recommendation)
        summary_rows.append(
            {
                "Ticker": position["symbol"],
                "Direction": position["direction"],
                "P/L Status": summary["profit_label"],
                "Risk": summary["risk_status"],
                "Runner": summary["runner_status"],
                "Next Action": summary["next_action"],
                "Suggested Stop": recommendation.get("suggested_stop") or "N/A",
            }
        )
        rows.append(
            {
                "ID": position["id"],
                "Entered": position["entered_at"],
                "Ticker": position["symbol"],
                "Direction": position["direction"],
                "Contract": f"{position['option_type']} {position.get('strike') or ''} {position.get('expiration') or ''}",
                "Entry Premium": entry_premium,
                "Current Premium": current_premium,
                "Peak Premium": peak_premium,
                "Current P/L %": recommendation.get("current_profit_percent"),
                "Peak P/L %": recommendation.get("peak_profit_percent"),
                "Giveback %": recommendation.get("profit_giveback_percent"),
                "Partial 1": "Taken" if position.get("partial_1_taken") else "Open",
                "Partial 2": "Taken" if position.get("partial_2_taken") else "Open",
                "Contracts": contracts,
                "Underlying Entry": position.get("entry_underlying_price"),
                "Stop": position.get("current_stop"),
                "Suggested Stop": recommendation.get("suggested_stop"),
                "Target 1": position.get("target_1"),
                "Target 2": position.get("target_2"),
                "Exit Score": recommendation["exit_score"],
                "Coach": recommendation["coach_action"],
                "Main Reason": main_reason,
            }
        )

    st.markdown("**Active Trade Summary**")
    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

    st.markdown("**Active Trade Details**")
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    with st.expander("Trade Coach Details"):
        for position in positions:
            recommendation = recommendations[position["id"]]
            st.markdown(
                f"**#{position['id']} {position['symbol']} - {recommendation['coach_action']}**"
            )
            st.write(
                f"Exit Score: {recommendation['exit_score']}/100 - {recommendation['exit_label']}"
            )
            st.write(
                "Premium: "
                f"current {recommendation.get('current_profit_percent')}%, "
                f"peak {recommendation.get('peak_profit_percent')}%, "
                f"giveback {recommendation.get('profit_giveback_percent')}%"
            )
            if recommendation.get("suggested_stop"):
                st.write(
                    f"Suggested Stop: ${recommendation['suggested_stop']:.2f} - "
                    f"{recommendation.get('suggested_stop_reason')}"
                )
            st.write(recommendation["coach_next_step"])
            for reason in recommendation["exit_reasons"]:
                st.write(f"- {reason}")

    with st.expander("Stop Management"):
        for position in positions:
            recommendation = recommendations[position["id"]]
            suggested_stop = recommendation.get("suggested_stop")
            st.markdown(
                f"**#{position['id']} {position['symbol']} {position['option_type']}**"
            )
            s1, s2, s3 = st.columns(3)
            s1.metric("Current Stop", position.get("current_stop") or "N/A")
            s2.metric("Suggested Stop", suggested_stop if suggested_stop else "N/A")

            if suggested_stop and s3.button(
                "Apply Suggested Stop",
                key=f"apply_stop_{position['id']}",
            ):
                update_position_stop(position["id"], suggested_stop)
                st.success("Stop updated.")
                st.rerun()

    with st.expander("Partial Profit Tracker"):
        for position in positions:
            st.markdown(
                f"**#{position['id']} {position['symbol']} {position['option_type']}**"
            )
            p1, p2, p3, p4 = st.columns(4)
            partial_1_taken = bool(position.get("partial_1_taken"))
            partial_2_taken = bool(position.get("partial_2_taken"))

            p1.metric("First Partial", "Taken" if partial_1_taken else "Open")
            p2.metric("Second Partial", "Taken" if partial_2_taken else "Open")

            if p3.button(
                "Mark First Taken" if not partial_1_taken else "Reset First",
                key=f"partial_1_{position['id']}",
            ):
                mark_partial_profit(position["id"], 1, taken=not partial_1_taken)
                st.rerun()

            if p4.button(
                "Mark Second Taken" if not partial_2_taken else "Reset Second",
                key=f"partial_2_{position['id']}",
            ):
                mark_partial_profit(position["id"], 2, taken=not partial_2_taken)
                st.rerun()

    with st.expander("Trade Coach Timeline"):
        position_options = {
            f"#{position['id']} {position['symbol']} {position['option_type']}": position["id"]
            for position in positions
        }
        selected = st.selectbox(
            "Position",
            list(position_options.keys()),
            key="timeline_position",
        )
        timeline = load_recommendations(position_options[selected])

        if not timeline:
            render_empty_state("No coach changes logged for this trade yet.")
        else:
            timeline_df = pd.DataFrame(recommendation_rows(timeline))
            st.dataframe(timeline_df, use_container_width=True, hide_index=True)

    with st.expander("Update Premium / Peak Profit"):
        position_options = {
            f"#{position['id']} {position['symbol']} {position['option_type']}": position["id"]
            for position in positions
        }
        selected = st.selectbox("Position", list(position_options.keys()), key="premium_position")
        selected_position = next(
            position for position in positions if position["id"] == position_options[selected]
        )
        default_premium = float(
            selected_position.get("current_premium")
            or selected_position.get("entry_premium")
            or 0
        )
        current_premium = st.number_input(
            "Current option premium",
            min_value=0.0,
            value=default_premium,
            step=0.05,
        )

        if st.button("Update Premium"):
            update_position_premium(position_options[selected], current_premium)
            st.success("Premium updated.")
            st.rerun()

    with st.expander("Close Trade"):
        position_options = {
            f"#{position['id']} {position['symbol']} {position['option_type']}": position["id"]
            for position in positions
        }
        selected = st.selectbox("Position", list(position_options.keys()))
        exit_premium = st.number_input("Exit premium", min_value=0.0, value=0.0, step=0.05)
        outcome_tag = st.selectbox(
            "Outcome tag",
            [
                "Unreviewed",
                "Good setup / good management",
                "Good setup / poor management",
                "Bad setup / avoided worse loss",
                "Bad setup / poor management",
                "Breakeven",
                "Rule break",
            ],
        )
        review_1, review_2, review_3 = st.columns(3)
        setup_grade = review_1.selectbox(
            "Setup grade",
            ["Unreviewed", "A", "B", "C", "D", "F"],
        )
        management_grade = review_2.selectbox(
            "Management grade",
            ["Unreviewed", "A", "B", "C", "D", "F"],
        )
        rule_following_score = review_3.slider(
            "Rule-following score",
            min_value=0,
            max_value=10,
            value=5,
        )
        exit_notes = st.text_area("Exit notes", placeholder="Why are you closing this trade?")
        lessons_learned = st.text_area(
            "Lessons learned",
            placeholder="What should you repeat, avoid, or watch for next time?",
        )

        if st.button("Mark Closed"):
            close_position(
                position_options[selected],
                exit_premium=exit_premium or None,
                exit_notes=exit_notes,
                outcome_tag=outcome_tag,
                lessons_learned=lessons_learned,
                setup_grade=setup_grade,
                management_grade=management_grade,
                rule_following_score=rule_following_score,
            )
            st.success("Trade closed.")
            st.rerun()


def position_journal_rows(positions):
    rows = []
    for position in positions:
        entry_premium = position.get("entry_premium") or 0
        exit_premium = position.get("exit_premium") or 0
        contracts = position.get("contracts") or 0
        premium_pnl = None
        pnl_percent = None

        if entry_premium and exit_premium and contracts:
            premium_pnl = round((exit_premium - entry_premium) * contracts * 100, 2)
            pnl_percent = round(((exit_premium - entry_premium) / entry_premium) * 100, 2)

        rows.append(
            {
                "ID": position["id"],
                "Status": position["status"],
                "Entered": position["entered_at"],
                "Closed": position.get("closed_at"),
                "Ticker": position["symbol"],
                "Direction": position["direction"],
                "Contract": f"{position['option_type']} {position.get('strike') or ''} {position.get('expiration') or ''}",
                "Entry Premium": entry_premium,
                "Peak Premium": position.get("peak_premium"),
                "Exit Premium": exit_premium or None,
                "Contracts": contracts,
                "Premium P/L": premium_pnl,
                "P/L %": pnl_percent,
                "Outcome": position.get("outcome_tag"),
                "Setup Grade": position.get("setup_grade"),
                "Management Grade": position.get("management_grade"),
                "Rule Score": position.get("rule_following_score"),
                "Entry Notes": position.get("entry_notes"),
                "Exit Notes": position.get("exit_notes"),
                "Lessons Learned": position.get("lessons_learned"),
            }
        )

    return rows


def recommendation_rows(recommendations):
    rows = []
    for recommendation in recommendations:
        try:
            reasons = ", ".join(json.loads(recommendation["reasons_json"]))
        except (TypeError, ValueError, json.JSONDecodeError):
            reasons = recommendation.get("reasons_json", "")

        rows.append(
            {
                "ID": recommendation["id"],
                "Position ID": recommendation["position_id"],
                "Time": recommendation["timestamp"],
                "Exit Score": recommendation["exit_score"],
                "Exit Label": recommendation["exit_label"],
                "Coach Action": recommendation["coach_action"],
                "Next Step": recommendation["coach_next_step"],
                "Current P/L %": recommendation.get("current_profit_percent"),
                "Peak P/L %": recommendation.get("peak_profit_percent"),
                "Giveback %": recommendation.get("profit_giveback_percent"),
                "Suggested Stop": recommendation.get("suggested_stop"),
                "Stop Reason": recommendation.get("suggested_stop_reason"),
                "Reasons": reasons,
            }
        )

    return rows


def render_trade_journal():
    render_section_header("Trade Journal", "Closed trades and coach history")
    closed_positions = load_closed_positions()
    recommendations = load_recommendations()

    if not closed_positions:
        render_empty_state("No closed trades yet.")
    else:
        journal_df = pd.DataFrame(position_journal_rows(closed_positions))
        journal_records = journal_df.to_dict("records")
        filter_1, filter_2, filter_3, filter_4, filter_5 = st.columns(5)
        tickers = filter_1.multiselect(
            "Ticker",
            sorted(journal_df["Ticker"].dropna().unique()),
        )
        directions = filter_2.multiselect(
            "Direction",
            sorted(journal_df["Direction"].dropna().unique()),
        )
        outcomes = filter_3.multiselect(
            "Outcome",
            sorted(journal_df["Outcome"].fillna("Unreviewed").unique()),
        )
        start_date = filter_4.date_input("From", value=None)
        end_date = filter_5.date_input("To", value=None)

        filtered_records = filter_journal_rows(
            journal_records,
            tickers=tickers,
            directions=directions,
            outcomes=outcomes,
            start_date=start_date,
            end_date=end_date,
        )
        filtered_journal_df = pd.DataFrame(filtered_records)
        review_df = pd.DataFrame(review_dashboard_rows(filtered_records))
        trend_df = pd.DataFrame(review_trend_rows(filtered_records))
        outcome_df = pd.DataFrame(outcome_review_rows(filtered_records))
        lesson_df = pd.DataFrame(lesson_pattern_rows(filtered_records))

        st.caption(f"Showing {len(filtered_records)} of {len(journal_records)} closed trades")

        if not trend_df.empty:
            st.markdown("**Review Trend**")
            st.dataframe(trend_df, use_container_width=True, hide_index=True)
            st.download_button(
                "Download Review Trend CSV",
                trend_df.to_csv(index=False),
                file_name="optionbeacon_review_trend.csv",
                mime="text/csv",
            )

        if not review_df.empty:
            st.markdown("**Trade Review Dashboard**")
            st.dataframe(review_df, use_container_width=True, hide_index=True)
            st.download_button(
                "Download Trade Review Dashboard CSV",
                review_df.to_csv(index=False),
                file_name="optionbeacon_trade_review_dashboard.csv",
                mime="text/csv",
            )

        if not outcome_df.empty:
            st.markdown("**Outcome Review**")
            st.dataframe(outcome_df, use_container_width=True, hide_index=True)
            st.download_button(
                "Download Outcome Review CSV",
                outcome_df.to_csv(index=False),
                file_name="optionbeacon_outcome_review.csv",
                mime="text/csv",
            )

        if not lesson_df.empty:
            st.markdown("**Common Lesson Patterns**")
            st.dataframe(lesson_df, use_container_width=True, hide_index=True)
            st.download_button(
                "Download Lesson Patterns CSV",
                lesson_df.to_csv(index=False),
                file_name="optionbeacon_lesson_patterns.csv",
                mime="text/csv",
            )

        st.markdown("**Closed Trade Journal**")
        st.dataframe(filtered_journal_df, use_container_width=True, hide_index=True)
        st.download_button(
            "Download Trade Journal CSV",
            filtered_journal_df.to_csv(index=False),
            file_name="optionbeacon_trade_journal.csv",
            mime="text/csv",
        )

    with st.expander("Recommendation History"):
        if not recommendations:
            render_empty_state("No trade-coach recommendations logged yet.")
            return

        recommendation_df = pd.DataFrame(recommendation_rows(recommendations))
        st.dataframe(recommendation_df, use_container_width=True, hide_index=True)
        st.download_button(
            "Download Recommendation History CSV",
            recommendation_df.to_csv(index=False),
            file_name="optionbeacon_recommendation_history.csv",
            mime="text/csv",
        )


@st.cache_data(ttl=900, show_spinner=False)
def cached_trade_replay(symbols, period, min_score, max_hold_candles):
    return replay_symbols(
        list(symbols),
        period=period,
        min_score=min_score,
        max_hold_candles=max_hold_candles,
    )


def replay_preset_settings(preset):
    presets = {
        "Balanced test": {
            "period": "60d",
            "min_score": 85,
            "max_hold_candles": DEFAULT_MAX_HOLD_CANDLES,
            "description": "Best first read. Looks for strong setups without being too strict.",
        },
        "Strict quality test": {
            "period": "60d",
            "min_score": 90,
            "max_hold_candles": DEFAULT_MAX_HOLD_CANDLES,
            "description": "Fewer trades, higher setup quality requirement.",
        },
        "More signal test": {
            "period": "30d",
            "min_score": 80,
            "max_hold_candles": 24,
            "description": "More frequent setups. Useful for seeing whether the scanner becomes too loose.",
        },
    }
    return presets[preset]


def replay_symbol_choices(group_name):
    if group_name == "Core watchlist":
        return DEFAULT_REPLAY_SYMBOLS[:8]
    if group_name == "ETFs only":
        return SYMBOL_GROUPS.get("ETF Scanner", DEFAULT_REPLAY_SYMBOLS[:4])
    if group_name == "Single stocks only":
        return SYMBOL_GROUPS.get("Single Stock Scanner", DEFAULT_REPLAY_SYMBOLS[4:])
    return DEFAULT_REPLAY_SYMBOLS


def replay_plain_read(summary, results):
    if not summary["Trades"]:
        return (
            "No trades found.",
            "The scanner did not find enough setups with these settings. Try More signal test or lower the score in Advanced settings.",
        )

    win_rate = float(summary["Win Rate"].replace("%", ""))
    average_pnl = float(summary["Average P/L"].replace("%", ""))
    target_1_rate = float(summary["Target 1 Rate"].replace("%", ""))

    if win_rate >= 50 and average_pnl > 0 and target_1_rate >= 40:
        return (
            "Promising replay.",
            "The setup rules found enough winners and reached first targets often enough to deserve more review.",
        )
    if average_pnl > 0:
        return (
            "Mixed but constructive.",
            "The replay was positive overall, but review the table to see whether results depend on only a few strong trades.",
        )
    return (
        "Needs refinement.",
        "The replay did not show an edge with these settings. Treat this as feedback before using the setup live.",
    )


def render_trade_replay_backtest():
    render_section_header(
        "Trade Replay Backtest",
        "Simple historical check for setup quality and trade management",
    )
    st.markdown(
        '<div class="notice notice-info"><strong>Plain English:</strong> choose a test, click Run, then read whether the scanner looked promising, mixed, or weak. This uses historical stock/ETF candles, not exact option contract premiums.</div>',
        unsafe_allow_html=True,
    )
    with st.expander("How to use this"):
        st.markdown(
            """
            1. Start with **Balanced test** and **Core watchlist**.
            2. Click **Run Balanced test on Core watchlist**.
            3. Read the plain-English verdict first.
            4. Use **Win Rate**, **Average P/L**, and **Target 1 Rate** as the main gut-check.
            5. Open the detailed table only when you want to inspect individual trades.
            """
        )

    setup_1, setup_2 = st.columns([1.2, 1])
    preset = setup_1.selectbox(
        "What do you want to test?",
        ["Balanced test", "Strict quality test", "More signal test"],
    )
    symbol_group = setup_2.selectbox(
        "Which symbols?",
        ["Core watchlist", "ETFs only", "Single stocks only", "All scanner symbols"],
    )

    settings = replay_preset_settings(preset)
    symbols = replay_symbol_choices(symbol_group)
    period = settings["period"]
    min_score = settings["min_score"]
    max_hold_candles = settings["max_hold_candles"]

    st.caption(
        f"{settings['description']} Testing {len(symbols)} symbols, last {period}, score {min_score}+."
    )

    with st.expander("Advanced settings"):
        symbols = st.multiselect("Symbols", DEFAULT_REPLAY_SYMBOLS, default=symbols)
        advanced_1, advanced_2, advanced_3 = st.columns(3)
        period = advanced_1.selectbox(
            "Period",
            ["30d", "60d"],
            index=1 if period == "60d" else 0,
        )
        min_score = advanced_2.slider("Minimum Score", 75, 95, min_score, 5)
        max_hold_candles = advanced_3.selectbox(
            "Max Hold",
            [12, 24, DEFAULT_MAX_HOLD_CANDLES, 78],
            index=[12, 24, DEFAULT_MAX_HOLD_CANDLES, 78].index(max_hold_candles),
            format_func=lambda value: f"{value} candles",
        )

    run_label = f"Run {preset} on {symbol_group}"
    if st.button(run_label, use_container_width=True):
        if not symbols:
            render_empty_state("Choose at least one symbol to replay.")
            return

        with st.spinner("Replaying historical setups..."):
            results, errors = cached_trade_replay(
                tuple(symbols),
                period,
                min_score,
                max_hold_candles,
            )
        st.session_state["trade_replay_results"] = results
        st.session_state["trade_replay_errors"] = errors
        st.session_state["trade_replay_label"] = (
            f"{preset} | {symbol_group} | {period} | score {min_score}+ | {max_hold_candles} candles"
        )

    results = st.session_state.get("trade_replay_results")
    errors = st.session_state.get("trade_replay_errors", {})

    if results is None:
        render_empty_state("No replay has been run yet. Start with Balanced test on Core watchlist.")
        return

    st.caption(f"Last replay: {st.session_state.get('trade_replay_label', 'Custom replay')}")

    if errors:
        st.warning(
            "Some symbols could not be replayed: "
            + ", ".join(f"{symbol}: {message}" for symbol, message in errors.items())
        )

    if results.empty:
        render_empty_state("No replayed trades matched those settings.")
        return

    summary = replay_summary(results)
    verdict_title, verdict_body = replay_plain_read(summary, results)
    st.markdown(
        f'<div class="notice"><strong>{verdict_title}</strong><br>{verdict_body}</div>',
        unsafe_allow_html=True,
    )

    metric_columns = st.columns(4)
    primary_metrics = [
        ("Trades", summary["Trades"]),
        ("Win Rate", summary["Win Rate"]),
        ("Average P/L", summary["Average P/L"]),
        ("Target 1 Rate", summary["Target 1 Rate"]),
    ]
    for column, (label, value) in zip(metric_columns, primary_metrics):
        column.metric(label, value)

    with st.expander("More replay stats"):
        metric_columns = st.columns(3)
        secondary_metrics = [
            ("Total P/L", summary["Total P/L"]),
            ("Average Peak P/L", summary["Average Peak P/L"]),
            ("Breakeven Rate", summary["Breakeven Rate"]),
        ]
        for column, (label, value) in zip(metric_columns, secondary_metrics):
            column.metric(label, value)

    simple_columns = [
        "Symbol",
        "Entry Time",
        "Direction",
        "Score",
        "Entry Price",
        "Exit Reason",
        "P/L %",
        "Peak P/L %",
        "Events",
    ]
    st.markdown("**What Happened**")
    st.dataframe(
        results[simple_columns].tail(25).sort_index(ascending=False),
        use_container_width=True,
        hide_index=True,
    )

    by_symbol = (
        results.groupby("Symbol")
        .agg(
            Trades=("Symbol", "size"),
            Win_Rate=("P/L %", lambda values: round((values.gt(0).mean() * 100), 2)),
            Average_PL=("P/L %", "mean"),
            Target_1_Rate=("Target 1 Hit", lambda values: round((values.eq("Yes").mean() * 100), 2)),
        )
        .reset_index()
    )
    by_symbol["Average_PL"] = by_symbol["Average_PL"].round(3)
    by_symbol = by_symbol.rename(
        columns={
            "Win_Rate": "Win Rate %",
            "Average_PL": "Average P/L %",
            "Target_1_Rate": "Target 1 Rate %",
        }
    )

    st.markdown("**Symbol Read**")
    st.dataframe(by_symbol, use_container_width=True, hide_index=True)

    with st.expander("Detailed replay table"):
        st.dataframe(results, use_container_width=True, hide_index=True)

    st.download_button(
        "Download Trade Replay CSV",
        results.to_csv(index=False),
        file_name="optionbeacon_trade_replay.csv",
        mime="text/csv",
    )


def render_current_scanner(latest_results, symbol_groups):
    st.markdown('<div class="section-title">Scanner</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-kicker">Real-time opportunity groups</div>',
        unsafe_allow_html=True,
    )
    for group_name, symbols in symbol_groups.items():
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
    render_section_header(
        "Recent High Scores", f"Neutral log of scores at {HIGH_SCORE_THRESHOLD} or higher"
    )

    if len(history) == 0:
        render_empty_state("No high-score scanner readings logged yet.")
        return

    display_history = history.copy()
    display_history["score_value"] = pd.to_numeric(
        display_history["score"], errors="coerce"
    ).fillna(0)
    display_history = display_history[
        display_history["score_value"] >= HIGH_SCORE_THRESHOLD
    ].drop(columns=["score_value"])

    if len(display_history) == 0:
        render_empty_state("No high-score scanner readings logged yet.")
        return

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

    latest_results, high_score_history, _, symbol_groups = scan_symbols()

    live_tab, after_hours_tab, opportunities_tab, history_tab, tools_tab = st.tabs(
        ["Live Coach", "After Hours", "Opportunities", "History", "Tools"]
    )

    with live_tab:
        render_beacon_board(latest_results, high_score_history)
        with st.expander("Detailed Live Coach"):
            render_live_trade_coach(latest_results, high_score_history)
        with st.expander("Recent Coach Alert Table"):
            render_live_coach_alerts()

    with after_hours_tab:
        render_after_hours(latest_results)

    with opportunities_tab:
        render_top_opportunities(latest_results, high_score_history)
        st.divider()
        render_sector_strength(latest_results)
        st.divider()
        render_ranked_setup_table(latest_results)
        with st.expander("Full Scanner"):
            render_current_scanner(latest_results, symbol_groups)

    with history_tab:
        render_coach_timeline()
        st.divider()
        render_recent_high_scores(high_score_history)
        st.divider()
        render_trade_journal()

    with tools_tab:
        render_trade_replay_backtest()
        st.divider()
        render_score_guide()
        st.divider()
        render_active_trades(latest_results)

    st.markdown(
        '<div class="notice notice-warning">Decision-support dashboard only. Not financial advice.</div>',
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
