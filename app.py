import base64
import json
import os
from datetime import time
from html import escape
from pathlib import Path
from textwrap import dedent

import pandas as pd
import streamlit as st
from ui.theme import configure_page

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
from live_trade_coach_dashboard import (
    latest_symbol_price,
    live_plan_trade_outcome,
    open_trade_coach_output,
    open_trade_coach_eligible,
    render_live_trade_coach_output,
)
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
from signal_history import load_trade_outcomes
from signal_outcomes import load_signal_outcomes, summarize_outcomes
from tradier_options import tradier_configured
from trade_analytics import (
    CONFIDENCE_BUCKETS,
    analyze_trade_outcomes,
    confidence_bucket,
)
from trade_evidence import (
    UNAVAILABLE as EVIDENCE_UNAVAILABLE,
    actionable_trade_plan,
    format_evidence_metric,
    historical_evidence,
)
from trade_journal_dashboard import (
    STATUS_OPTIONS,
    filter_trade_outcomes,
    format_metric,
    grouped_performance_rows,
    trade_history_rows,
)
from trade_management import coach_recommendation, trade_summary
from trade_planning import trade_plan_view
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
MARKET_CONTEXT_TAPE_SYMBOLS = ["SPY", "QQQ", "IWM", "DIA", "XLK", "XLF"]
LOGO_ASSET_PATH = Path("assets/option-beacon-header-logo.png")
FALLBACK_LOGO_URL = "https://img1.wsimg.com/isteam/ip/3334c900-83eb-4af4-9363-381bdd4d9924/OptionBeaconLLC%20Logo%20V2.png"


@st.cache_data(show_spinner=False)
def image_data_uri(path):
    image_path = Path(path)
    if not image_path.exists():
        return FALLBACK_LOGO_URL

    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def logo_source():
    return image_data_uri(str(LOGO_ASSET_PATH))


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
                "Entry Risk": quality["chase_risk"],
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


def market_snapshot_values(latest_results):
    regime = market_regime(latest_results)
    ranked_rows = ranked_setup_rows(latest_results, min_score=65, limit=1)
    sector_rows = sector_strength_rows(latest_results)

    top_setup = ranked_rows[0] if ranked_rows else None
    top_sector = sector_rows[0] if sector_rows else None

    return {
        "regime": regime,
        "top_setup": top_setup,
        "top_sector": top_sector,
    }


def tape_row_color(value):
    if value in ["Bullish", "Aligned", "Strong", "Entry zone active", "Improving"]:
        return "tape-green"
    if value in ["Bearish", "Against", "Weak", "Avoid chasing", "Weakening"]:
        return "tape-red"
    return "tape-muted"


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


def short_time(value):
    if value in [None, ""]:
        return eastern_now().strftime("%I:%M %p ET").lstrip("0")

    try:
        timestamp = eastern_timestamp_from_value(value)
        return timestamp.strftime("%I:%M %p ET").lstrip("0")
    except Exception:
        return str(value)


def scan_stamp(value):
    if value in [None, ""]:
        return eastern_now().strftime("%m/%d/%Y %I:%M %p ET").lstrip("0")

    try:
        timestamp = eastern_timestamp_from_value(value)
        return timestamp.strftime("%m/%d/%Y %I:%M %p ET").lstrip("0")
    except Exception:
        return str(value)


def eastern_timestamp_from_value(value, naive_timezone="UTC"):
    text = str(value or "").strip()
    if text.endswith(" ET"):
        text = text[:-3]
        timestamp = pd.Timestamp(text)
        return timestamp.tz_localize("America/New_York")

    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize(naive_timezone).tz_convert("America/New_York")
    return timestamp.tz_convert("America/New_York")


def is_today_timestamp(value):
    try:
        return eastern_timestamp_from_value(value).date() == eastern_now().date()
    except Exception:
        return False


def today_alerts(alerts):
    if alerts.empty or "timestamp" not in alerts.columns:
        return alerts
    mask = alerts["timestamp"].apply(is_today_timestamp)
    return alerts[mask].copy()


def today_rows(rows, time_key="Time"):
    return [row for row in rows if is_today_timestamp(row.get(time_key))]


def current_day_guide_rows(rows, latest_results):
    current_rows = []
    for row in rows:
        result = latest_results.get(row.get("Symbol"), {})
        timestamp_value = result.get("last_candle_at") or row.get("Time")
        if is_today_timestamp(timestamp_value):
            current_rows.append(row)
    return current_rows


def current_day_opportunity_rows(rows):
    return [
        row for row in rows
        if is_today_timestamp((row.get("result") or {}).get("last_candle_at") or (row.get("result") or {}).get("timestamp"))
    ]


def current_day_ranked_rows(rows, latest_results):
    return [
        row for row in rows
        if is_today_timestamp(
            (latest_results.get(row.get("Symbol")) or {}).get("last_candle_at")
            or (latest_results.get(row.get("Symbol")) or {}).get("timestamp")
        )
    ]


def result_freshness_label(result):
    timestamp_value = (result or {}).get("last_candle_at") or (result or {}).get("timestamp")
    if not timestamp_value:
        return "Freshness unknown"

    try:
        timestamp = eastern_timestamp_from_value(timestamp_value, naive_timezone="America/New_York")
    except Exception:
        return "Freshness unknown"

    if timestamp.date() != eastern_now().date():
        return f"Stale {timestamp.strftime('%m/%d/%Y')}"

    age_minutes = max(
        0,
        int((pd.Timestamp.now(tz="America/New_York") - pd.Timestamp(timestamp)).total_seconds() // 60),
    )
    if age_minutes <= 7:
        return "Live candle"
    return f"{age_minutes}m old"


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




def app_access_configured():
    return bool(st.secrets.get("APP_ACCESS_CODE"))


def require_app_access():
    expected_code = st.secrets.get("APP_ACCESS_CODE")
    header_logo = logo_source()

    if not expected_code:
        return True

    if st.session_state.get("app_access_granted"):
        return True

    st.markdown(
        f"""
        <div class="brand-shell">
            <div class="brand-row">
                <div class="brand-left">
                    <img class="brand-logo" src="{header_logo}" alt="Option Beacon logo" />
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
    header_logo = logo_source()

    st.markdown(
        f"""
        <div class="brand-shell">
            <div class="brand-row">
                <div class="brand-left">
                    <img class="brand-logo" src="{header_logo}" alt="Option Beacon logo" />
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


def secret_configured(name):
    if os.getenv(name):
        return True
    try:
        return bool(st.secrets.get(name))
    except Exception:
        return False


def health_card(label, state, detail, level="warn"):
    return (
        '<div class="health-card">'
        f'<div class="health-label">{escape(label)}</div>'
        f'<div class="health-state health-{escape(level)}">{escape(state)}</div>'
        f'<div class="health-detail">{escape(detail)}</div>'
        '</div>'
    )


def scanner_freshness(latest_results, snapshot_time):
    timestamps = [
        result.get("last_candle_at") or result.get("timestamp")
        for result in latest_results.values()
        if result and (result.get("last_candle_at") or result.get("timestamp"))
    ]
    reference_time = max(timestamps) if timestamps else snapshot_time
    if reference_time in [None, ""]:
        return {
            "is_stale": False,
            "label": "Live fallback",
            "detail": "No scheduled scanner timestamp is loaded yet.",
        }

    try:
        timestamp = eastern_timestamp_from_value(reference_time, naive_timezone="America/New_York")
    except Exception:
        return {
            "is_stale": True,
            "label": "Timestamp unclear",
            "detail": f"Could not read scanner timestamp: {reference_time}",
        }

    now = pd.Timestamp.now(tz="America/New_York")
    age_minutes = max(0, int((now - pd.Timestamp(timestamp)).total_seconds() // 60))
    is_same_day = timestamp.date() == eastern_now().date()
    is_stale = (not is_same_day) or age_minutes > 20
    if is_same_day:
        detail = f"Latest scanner data: {scan_stamp(timestamp)} ({age_minutes} min old)."
    else:
        detail = f"Latest scanner data is from {scan_stamp(timestamp)}, not today."

    return {
        "is_stale": is_stale,
        "label": "Stale scanner data" if is_stale else "Fresh scanner data",
        "detail": detail,
    }


def render_scanner_freshness_notice(latest_results, snapshot_time):
    freshness = scanner_freshness(latest_results, snapshot_time)
    if not freshness["is_stale"]:
        return

    st.markdown(
        f'<div class="notice notice-warning"><strong>{escape(freshness["label"])}</strong><br>'
        f'{escape(freshness["detail"])} Today-only alert panels are hidden until fresh scanner data returns.</div>',
        unsafe_allow_html=True,
    )


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


def load_trade_evidence_history():
    try:
        return load_trade_outcomes()
    except Exception:
        return []


def render_historical_edge(result, trade_history, evidence=None):
    if not actionable_trade_plan(result):
        return None

    if evidence is None:
        try:
            evidence = historical_evidence(result, trade_history)
        except Exception:
            evidence = historical_evidence(result, [])

    match_labels = {
        "LEVEL_1": "Level 1 — Setup, direction, and symbol",
        "LEVEL_2": "Level 2 — Setup and direction",
        "LEVEL_3": "Level 3 — Setup",
        "NO_MATCH": "No match",
    }
    st.markdown(
        '<div class="section-subtitle"><span>Historical Edge</span>'
        '<span class="section-count">Read-only evidence</span></div>',
        unsafe_allow_html=True,
    )
    notice_class = (
        "notice-warning"
        if evidence["display_grade"] in {"WEAK", "INSUFFICIENT DATA", "NO MATCH"}
        else "notice-info"
    )
    st.markdown(
        f'<div class="notice {notice_class}"><strong>'
        f'{escape(evidence["display_grade"])}</strong><br>'
        f'{escape(evidence["summary"])}</div>',
        unsafe_allow_html=True,
    )

    row_1 = st.columns(4)
    row_1[0].metric("Grade", evidence["display_grade"])
    row_1[1].metric(
        "Match Level",
        match_labels.get(evidence["match_level"], evidence["match_level"]),
    )
    row_1[2].metric("Sample Size", evidence["sample_size"])
    row_1[3].metric(
        "Win Rate",
        format_evidence_metric(evidence["win_rate"], percentage=True),
    )

    row_2 = st.columns(4)
    row_2[0].metric(
        "Average Return",
        format_evidence_metric(evidence["average_return"], percentage=True),
    )
    row_2[1].metric(
        "Median Return",
        format_evidence_metric(evidence["median_return"], percentage=True),
    )
    row_2[2].metric(
        "Expectancy",
        format_evidence_metric(evidence["expectancy"], percentage=True),
    )
    row_2[3].metric(
        "Profit Factor",
        format_evidence_metric(evidence["profit_factor"]),
    )

    row_3 = st.columns(3)
    row_3[0].metric(
        "Average Hold Minutes",
        format_evidence_metric(evidence["average_hold_minutes"]),
    )
    row_3[1].metric(
        "Average MFE",
        format_evidence_metric(evidence["average_mfe"], percentage=True),
    )
    row_3[2].metric(
        "Average MAE",
        format_evidence_metric(evidence["average_mae"], percentage=True),
    )

    row_4 = st.columns(5)
    for column, label, key in zip(
        row_4,
        (
            "Target 1 Rate",
            "Target 2 Rate",
            "Target 3 Rate",
            "Stop Rate",
            "Time-exit Rate",
        ),
        (
            "target_1_rate",
            "target_2_rate",
            "target_3_rate",
            "stop_rate",
            "time_exit_rate",
        ),
    ):
        column.metric(
            label,
            format_evidence_metric(evidence[key], percentage=True),
        )

    gap = format_evidence_metric(evidence["confidence_gap"])
    if gap != EVIDENCE_UNAVAILABLE:
        gap = f"{gap} pp"
    row_5 = st.columns(3)
    row_5[0].metric(
        "Current Confidence",
        format_evidence_metric(evidence["current_confidence"], decimals=0),
    )
    row_5[1].metric(
        f'Historical Win Rate ({evidence["confidence_bucket"]})',
        format_evidence_metric(
            evidence["historical_confidence_win_rate"],
            percentage=True,
        ),
    )
    row_5[2].metric("Confidence Gap", gap)
    return evidence


def render_live_plan_trade_coach(result, trade_history, evidence=None):
    """Render coaching for an actionable, entered live plan without persistence."""
    current_price = result.get("price")
    now = eastern_now()
    record = live_plan_trade_outcome(
        result,
        trade_history,
        current_price=current_price,
        current_timestamp=now,
    )
    if record is None:
        return

    if evidence is None:
        try:
            evidence = historical_evidence(result, trade_history)
        except Exception:
            evidence = None
    coach = open_trade_coach_output(
        record,
        current_price,
        now,
        evidence,
    )
    if coach is not None:
        render_live_trade_coach_output(coach)


def render_opportunity_card(
    row,
    latest_results,
    high_score_history=None,
    trade_history=None,
):
    result = row["result"]
    plan_view = trade_plan_view(result)
    score = row["score"]
    direction = result.get("bias", "Neutral")
    last_scan = scan_stamp(result.get("timestamp"))
    coach = coach_live_setup(result)
    chase = chase_risk(result)
    sector = setup_sector_support(result, latest_results)
    quality = setup_quality(result, latest_results)
    liquidity = liquidity_quality(result)
    option_liquidity = result.get("option_liquidity") or {}
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

    reasons = plan_view["reasons"]
    reasons_html = "".join(
        f"<li>{escape(reason)}</li>" for reason in reasons
    )
    exit_reasons_html = "".join(
        f"<li>{escape(reason)}</li>" for reason in exit_reasons[:4]
    )

    entry_zone = plan_view["entry_zone"]
    stop = plan_view["initial_stop"]
    target_1 = plan_view["target_1"]
    target_2 = plan_view["target_2"]
    target_3 = plan_view["target_3"]
    risk_reward_label = plan_view["risk_reward"]
    contract = coach.get("contract", "N/A")
    option_contract = option_liquidity.get("contract") or "N/A"
    option_liquidity_notice = []
    if option_liquidity.get("available"):
        option_liquidity_notice.append(
            f'<div class="notice"><strong>Option Chain: {escape(option_liquidity.get("label", "Available"))}</strong><br>'
            f'{escape(option_liquidity.get("detail", ""))}<br>'
            f'Contract: {escape(option_contract)} | Strike: {money(option_liquidity.get("strike"))} | '
            f'Expiration: {escape(str(option_liquidity.get("expiration", "N/A")))}</div>'
        )

    card_sections = [
        f'<div class="notice notice-info"><strong>Why this is here</strong><br>{escape(quality_note)}</div>',
        f'<div class="notice notice-info"><strong>What should I do next?</strong><br>{escape(coach["summary"])} {escape(coach["next_step"])}</div>',
        f'<div class="notice"><strong>Sector Support: {escape(sector["status"])}</strong><br>{escape(sector["detail"])}</div>',
        f'<div class="notice"><strong>Liquidity: {escape(liquidity["label"])}</strong><br>{escape(liquidity["detail"])}</div>',
        *option_liquidity_notice,
        f'<div class="notice"><strong>Live Read: {escape(momentum["label"])}</strong><br>{escape(momentum["detail"])}</div>',
        f'<div class="notice"><strong>Entry Risk: {escape(chase["label"])}</strong><br>{escape(chase["reason"])}<br>{escape(confidence_note)}</div>',
        '<div class="content-kicker">Why?</div>',
        f'<ul class="why-list">{reasons_html}</ul>',
        '<div class="content-kicker">Exit / Reversal Watch</div>',
        f'<ul class="why-list">{exit_reasons_html}</ul>',
    ]
    card_detail_html = "".join(card_sections)

    st.markdown(
        dedent(f"""
        <div class="coach-card">
            <div class="coach-card-header">
                <div>
                    <div class="coach-symbol security-symbol">{escape(row["symbol"])}</div>
                    <div class="content-kicker">{escape(plan_view["setup_name"])} | {escape(direction)} {escape(contract)} idea | Last scan {escape(last_scan)}</div>
                </div>
                <div class="coach-grade">
                    Quality: {escape(quality["grade"])}<br>
                    <span class="content-kicker">Quality {quality["score"]}/100 | Setup {score}%</span>
                </div>
            </div>
            <div class="factor-list">{factor_html}</div>
            <div class="coach-grid">
                <div class="coach-metric"><div class="coach-label">Entry Zone</div><div class="coach-value">{escape(entry_zone)}</div></div>
                <div class="coach-metric"><div class="coach-label">Trigger</div><div class="coach-value">{escape(plan_view["trigger_price"])}</div></div>
                <div class="coach-metric"><div class="coach-label">Stop</div><div class="coach-value">{stop}</div></div>
                <div class="coach-metric"><div class="coach-label">Target 1</div><div class="coach-value">{target_1}</div></div>
                <div class="coach-metric"><div class="coach-label">Risk/Reward</div><div class="coach-value">{risk_reward_label}</div></div>
                <div class="coach-metric"><div class="coach-label">Target 2</div><div class="coach-value">{target_2}</div></div>
                <div class="coach-metric"><div class="coach-label">Target 3</div><div class="coach-value">{target_3}</div></div>
                <div class="coach-metric"><div class="coach-label">Expected Hold</div><div class="coach-value">{escape(plan_view["expected_hold"])}</div></div>
                <div class="coach-metric"><div class="coach-label">Maximum Chase</div><div class="coach-value">{escape(plan_view["maximum_chase_price"])}</div></div>
                <div class="coach-metric"><div class="coach-label">Timing</div><div class="coach-value">{escape(plan_view["timing_label"])}</div></div>
                <div class="coach-metric"><div class="coach-label">Confidence</div><div class="coach-value">{escape(plan_view["confidence"])}</div></div>
                <div class="coach-metric"><div class="coach-label">Guide Action</div><div class="coach-value">{escape(coach["action"])}</div></div>
                <div class="coach-metric"><div class="coach-label">Exit Score</div><div class="coach-value">{coach["exit_score"]}/100</div></div>
                <div class="coach-metric"><div class="coach-label">Stock Liquidity</div><div class="coach-value">{escape(liquidity["label"])}</div></div>
                <div class="coach-metric"><div class="coach-label">Sector</div><div class="coach-value">{escape(sector["status"])}</div></div>
                <div class="coach-metric"><div class="coach-label">Option Chain</div><div class="coach-value">{escape(option_liquidity.get("label", "N/A"))}</div></div>
            </div>
            <div class="notice"><strong>Invalidation</strong><br>{escape(plan_view["invalidation_condition"])}</div>
            {card_detail_html}
        </div>
        """).strip(),
        unsafe_allow_html=True,
    )
    evidence = render_historical_edge(result, trade_history or [])
    render_live_plan_trade_coach(
        result,
        trade_history or [],
        evidence=evidence,
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


def render_opportunity_list(
    title,
    rows,
    latest_results,
    high_score_history=None,
    trade_history=None,
):
    title_class = "signal-call" if "Bullish" in title else "signal-put" if "Bearish" in title else ""
    st.markdown(
        f'<div class="opportunity-heading {title_class}">{title}</div>',
        unsafe_allow_html=True,
    )

    if not rows:
        render_empty_state("No scored opportunities yet.")
        return

    for row in rows:
        render_opportunity_card(
            row,
            latest_results,
            high_score_history,
            trade_history,
        )


def render_top_opportunities(
    latest_results,
    high_score_history=None,
    trade_history=None,
):
    render_section_header("Top Opportunities", "Highest-scoring bullish and bearish setups")
    bullish_rows = opportunity_rows(latest_results, "Bullish")
    bearish_rows = opportunity_rows(latest_results, "Bearish")
    bullish_column, bearish_column = st.columns(2)

    with bullish_column:
        render_opportunity_list(
            "Top Bullish",
            bullish_rows,
            latest_results,
            high_score_history,
            trade_history,
        )

    with bearish_column:
        render_opportunity_list(
            "Top Bearish",
            bearish_rows,
            latest_results,
            high_score_history,
            trade_history,
        )


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
        "Live Trade Guide",
        "Current scanner ideas with entry, wait, and risk guidance",
    )
    rows = current_day_guide_rows(
        coach_rows(latest_results, min_score=60, history=high_score_history),
        latest_results,
    )

    if not rows:
        render_empty_state("No current-day guide ideas are ready yet.")
        return

    active_rows = [
        row for row in rows
        if row["Action"] in ["Entry zone active", "Watch for trigger", "Avoid chasing", "Monitor setup"]
    ]
    display_rows = active_rows or rows[:8]
    display_df = pd.DataFrame(display_rows)
    display_df["Price"] = pd.to_numeric(display_df["Price"], errors="coerce").round(2)
    display_df["Time"] = display_df["Time"].apply(short_time)
    display_df = display_df.rename(columns={"Coach Summary": "Guide Summary"})

    with st.expander("Guide Key"):
        key_rows = [
            {
                "Field": "Guide Action",
                "What it means": "The next practical step: enter, watch, monitor, wait, manage, or avoid.",
            },
            {
                "Field": "Entry Risk",
                "What it means": "How risky the current entry location is. High means the idea may be valid, but price is too extended to chase.",
            },
            {
                "Field": "Exit Score",
                "What it means": "Reversal/weakness risk after an idea is active. Higher means more caution.",
            },
            {
                "Field": "Live Read",
                "What it means": "Whether momentum is improving, fading, or holding based on recent scanner reads.",
            },
        ]
        st.dataframe(pd.DataFrame(key_rows), use_container_width=True, hide_index=True)

    st.dataframe(
        display_df[
            [
                "Symbol",
                "Time",
                "Action",
                "Bias",
                "Score",
                "Contract",
                "Price",
                "Stage",
                "Timing",
                "Guide Summary",
                "Next Step",
                "10m Edge",
                "10m Edge Label",
                "Exit Score",
                "Exit Label",
                "Entry Risk",
                "Live Read",
                "Missing",
                "Risk Note",
            ]
        ],
        use_container_width=True,
        hide_index=True,
    )

    with st.expander("Guide Details"):
        for row in display_rows[:6]:
            st.markdown(f"**{row['Symbol']} - {row['Action']} ({row['Score']}/100, last scan {scan_stamp(row.get('Time'))})**")
            st.write(f"Exit Score: {row['Exit Score']}/100 - {row['Exit Label']}")
            st.write(f"Entry Risk: {row['Entry Risk']}")
            st.write(f"Live Read: {row['Live Read']} - {row['Live Detail']}")
            st.write(f"Missing: {row['Missing']}")
            st.write(row["Coach Summary"])
            st.write(row["Next Step"])
            st.write(f"10-Minute Edge: {row['10m Edge']}% - {row['10m Edge Label']}")
            st.write(row["Risk Note"])


def render_market_snapshot(latest_results):
    snapshot = market_snapshot_values(latest_results)
    regime = snapshot["regime"]
    top_setup = snapshot["top_setup"]
    top_sector = snapshot["top_sector"]

    setup_value = "No clean setup"
    setup_detail = "Waiting for a higher-quality setup to separate from the list."
    if top_setup:
        setup_value = f'{top_setup["Symbol"]} {top_setup["Grade"]}'
        setup_detail = (
            f'{top_setup["Bias"]} | Quality {top_setup["Quality Score"]}/100 | '
            f'Entry risk: {top_setup["Entry Risk"]}'
        )

    sector_value = "Sector data pending"
    sector_detail = "Sector context appears after the scheduled scan includes sector ETFs."
    if top_sector:
        sector_value = f'{top_sector["ETF"]} {top_sector["Bias"]}'
        sector_detail = f'{top_sector["Sector"]} | Score {top_sector["Score"]}/100 | RVol {top_sector["RVol"]}'

    st.markdown(
        f"""
        <div class="snapshot-strip">
            <div class="snapshot-tile">
                <div class="snapshot-label">Market Read</div>
                <div class="snapshot-value">{escape(regime["regime"])}</div>
                <div class="snapshot-detail">{escape(regime["support"])}</div>
            </div>
            <div class="snapshot-tile">
                <div class="snapshot-label">Top Quality Setup</div>
                <div class="snapshot-value">{escape(setup_value)}</div>
                <div class="snapshot-detail">{escape(setup_detail)}</div>
            </div>
            <div class="snapshot-tile">
                <div class="snapshot-label">Sector Pulse</div>
                <div class="snapshot-value">{escape(sector_value)}</div>
                <div class="snapshot-detail">{escape(sector_detail)}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_beacon_tape(latest_results):
    ranked_rows = current_day_ranked_rows(
        ranked_setup_rows(latest_results, min_score=65, limit=7),
        latest_results,
    )
    sector_rows = sector_strength_rows(latest_results)[:7]
    alerts = today_alerts(load_live_coach_alerts())

    def market_rows():
        html = ""
        for symbol in MARKET_CONTEXT_TAPE_SYMBOLS:
            result = latest_results.get(symbol, {})
            if not result:
                continue
            bias = result.get("bias", "N/A")
            price = money(result.get("price"))
            score = result.get("confidence", 0)
            freshness = result_freshness_label(result)
            html += (
                '<div class="tape-row">'
                f'<div class="tape-symbol security-symbol">{escape(symbol)}</div>'
                f'<div class="tape-main {tape_row_color(bias)}">{escape(str(bias))}</div>'
                f'<div class="tape-sub">{escape(price)}<br>{escape(str(score))} | {escape(freshness)}</div>'
                '</div>'
            )
        return html or '<div class="tape-empty">Core market ETFs are waiting on fresh scanner data.</div>'

    def setup_rows():
        html = ""
        for row in ranked_rows:
            color = tape_row_color(row["Bias"])
            html += (
                '<div class="tape-row">'
                f'<div class="tape-symbol security-symbol">{escape(row["Symbol"])}</div>'
                f'<div class="tape-main {color}">{escape(row["Bias"])}</div>'
                f'<div class="tape-sub">Q {escape(str(row["Quality Score"]))}<br>{escape(row["Grade"])}</div>'
                '</div>'
            )
        return html or '<div class="tape-empty">No quality setups are separated yet.</div>'

    def sector_tape_rows():
        html = ""
        for row in sector_rows:
            color = tape_row_color(row["Bias"])
            html += (
                '<div class="tape-row">'
                f'<div class="tape-symbol security-symbol">{escape(row["ETF"])}</div>'
                f'<div class="tape-main {color}">{escape(row["Bias"])}</div>'
                f'<div class="tape-sub">{escape(str(row["Score"]))}<br>{escape(row["Sector"][:6])}</div>'
                '</div>'
            )
        return html or '<div class="tape-empty">Sector reads appear after sector ETFs are scanned.</div>'

    def alert_rows():
        html = ""
        if not alerts.empty:
            for _, alert in alerts.tail(6).iloc[::-1].iterrows():
                action = str(alert.get("action", ""))
                html += (
                    '<div class="tape-row">'
                    f'<div class="tape-symbol security-symbol">{escape(str(alert.get("symbol", "")))}</div>'
                    f'<div class="tape-main {tape_row_color(action)}">{escape(action)}</div>'
                    f'<div class="tape-sub">{escape(str(alert.get("score", "")))}<br>{escape(str(alert.get("live_read", ""))[:8])}</div>'
                    '</div>'
                )
        return html or '<div class="tape-empty">No guide alerts logged today.</div>'

    bull_count = sum(1 for row in ranked_rows if row["Bias"] == "Bullish")
    bear_count = sum(1 for row in ranked_rows if row["Bias"] == "Bearish")
    sentiment_label = f"{bull_count}:{bear_count}"

    st.markdown(
        f"""
        <div class="beacon-tape">
            <div class="tape-panel">
                <div class="tape-header"><span>Market Context</span><span>ETFs</span></div>
                {market_rows()}
            </div>
            <div class="tape-panel">
                <div class="tape-header"><span>Setup Bias</span><span>{escape(sentiment_label)}</span></div>
                {setup_rows()}
            </div>
            <div class="tape-panel">
                <div class="tape-header"><span>Sectors</span><span>Leaders</span></div>
                {sector_tape_rows()}
            </div>
            <div class="tape-panel">
                <div class="tape-header"><span>Alerts</span><span>Guide</span></div>
                {alert_rows()}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_beacon_board(latest_results, high_score_history=None):
    regime = market_regime(latest_results)
    coach_queue = current_day_guide_rows(
        coach_rows(latest_results, min_score=60, history=high_score_history),
        latest_results,
    )
    alerts = today_alerts(load_live_coach_alerts())
    bullish_rows = current_day_opportunity_rows(
        opportunity_rows(latest_results, "Bullish", limit=5)
    )
    bearish_rows = current_day_opportunity_rows(
        opportunity_rows(latest_results, "Bearish", limit=5)
    )
    risk_rows = [
        row for row in coach_queue
        if row["Entry Risk"] == "High" or int(row.get("Exit Score") or 0) >= 55
    ][:6]

    market_tiles = ""
    for symbol in ["SPY", "QQQ", "IWM", "DIA"]:
        result = latest_results.get(symbol, {})
        bias = result.get("bias", "N/A")
        score = result.get("confidence", 0)
        color = board_color_class(bias)
        freshness = result_freshness_label(result)
        market_tiles += (
            f'<div class="board-tile">'
            f'<div class="board-tile-label security-symbol">{escape(symbol)}</div>'
            f'<div class="board-tile-value {color}">{escape(str(bias))}</div>'
            f'<div class="board-sub">Score {escape(str(score))}/100 | {escape(freshness)}</div>'
            f'</div>'
        )

    coach_html = ""
    for row in coach_queue[:7]:
        action_color = board_color_class(row["Action"])
        bias = row.get("Bias", "Neutral")
        bias_color = board_color_class(bias)
        coach_html += (
            '<div class="board-row">'
            f'<div class="board-symbol security-symbol">{escape(row["Symbol"])}</div>'
            f'<div><div class="board-titleline"><span class="board-bias-tag {bias_color}">{escape(bias)}</span>'
            f'<span class="board-main {action_color}">{escape(row["Action"])}</span></div>'
            f'<div class="board-meta"><span>{escape(row["Live Read"])}</span><span>{escape(row["Timing"])}</span>'
            f'<span>{escape(scan_stamp(row.get("Time")))}</span></div>'
            f'<div class="board-sub">10m edge: {escape(str(row["10m Edge"]))}% {escape(row["10m Edge Label"])} | Entry risk: {escape(row["Entry Risk"])} | Exit {escape(str(row["Exit Score"]))}</div></div>'
            f'<div class="board-score"><div class="board-number">{escape(str(row["Score"]))}</div><div class="board-score-label">Score</div></div>'
            '</div>'
        )
    if not coach_html:
        coach_html = '<div class="board-note">No current-day guide ideas are active yet.</div>'

    def setup_rows(rows):
        html = ""
        for row in rows:
            result = row["result"]
            plan = result.get("trade_plan") or {}
            bias_label = str(result.get("bias", "Neutral")).upper()
            timing_label = str(result.get("entry_timing", "Wait")).upper()
            html += (
                '<div class="board-row board-row-compact">'
                f'<div class="board-symbol security-symbol">{escape(row["symbol"])}</div>'
                f'<div><div class="board-callout"><span class="board-callout-chip">{escape(bias_label)}</span>'
                f'<span class="board-callout-muted">{escape(timing_label)}</span></div>'
                f'<div class="board-sub">Entry {money(plan_value(plan, "trigger_price", result.get("entry")))} | Stop {money(plan_value(plan, "technical_stop", result.get("stop")))} | {escape(result_freshness_label(result))}</div></div>'
                f'<div class="board-score"><div class="board-number">{escape(str(row["score"]))}</div><div class="board-score-label">Score</div></div>'
                '</div>'
            )
        return html or '<div class="board-note">No scored setups yet.</div>'

    risk_html = ""
    for row in risk_rows:
        risk_color = board_color_class(row["Entry Risk"])
        risk_html += (
            '<div class="board-row board-row-compact">'
            f'<div class="board-symbol security-symbol">{escape(row["Symbol"])}</div>'
            f'<div><div class="board-main {risk_color}">Entry risk: {escape(row["Entry Risk"])}</div>'
            f'<div class="board-meta"><span>{escape(row["Exit Label"])}</span><span>{escape(row["Action"])}</span>'
            f'<span>{escape(scan_stamp(row.get("Time")))}</span></div></div>'
            f'<div class="board-score"><div class="board-number">{escape(str(row["Exit Score"]))}</div><div class="board-score-label">Exit</div></div>'
            '</div>'
        )
    if not risk_html:
        risk_html = '<div class="board-note">No high entry-risk or elevated exit-score warnings.</div>'

    alert_html = ""
    if not alerts.empty:
        for _, alert in alerts.tail(6).iloc[::-1].iterrows():
            alert_html += (
                '<div class="board-row board-row-compact">'
                f'<div class="board-symbol security-symbol">{escape(str(alert.get("symbol", "")))}</div>'
                f'<div><div class="board-main">{escape(str(alert.get("action", "")))}</div>'
                f'<div class="board-meta"><span>{escape(str(alert.get("live_read", "")))}</span>'
                f'<span>{escape(str(alert.get("timestamp", "")))}</span></div></div>'
                f'<div class="board-score"><div class="board-number">{escape(str(alert.get("score", "")))}</div><div class="board-score-label">Score</div></div>'
                '</div>'
            )
    if not alert_html:
        alert_html = '<div class="board-note">No guide alerts logged today.</div>'

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
                <div class="board-header"><span>Guide Queue</span><span>What matters now</span></div>
                <div class="board-body">{coach_html}</div>
            </div>
            <div class="board-panel">
                <div class="board-header"><span>Risk Watch</span><span>Entry / Exit</span></div>
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
        "Recent Guide Alerts",
        "Meaningful setup changes logged by the scheduled scanner",
    )
    alerts = today_alerts(load_live_coach_alerts())

    if alerts.empty:
        render_empty_state("No guide alerts logged today.")
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
            "chase_risk": "Entry Risk",
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
                "Entry Risk",
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
        "Guide Timeline",
        "How a symbol's setup has changed through recent scanner reads",
    )
    alerts = load_live_coach_alerts()

    if alerts.empty:
        render_empty_state("No guide timeline yet.")
        return

    symbols = sorted(alerts["symbol"].dropna().unique())
    if not symbols:
        render_empty_state("No symbols have guide alerts yet.")
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
            "chase_risk": "Entry Risk",
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
                "Entry Risk",
                "Next Step",
                "Reason",
            ]
        ].sort_index(ascending=False),
        use_container_width=True,
        hide_index=True,
    )


def render_signal_card(symbol, result, trade_history=None):
    with st.container(border=True):
        st.markdown(f'<div class="ticker-title security-symbol">{symbol}</div>', unsafe_allow_html=True)

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
        option_liquidity = result.get("option_liquidity") or {}

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
            plan_view = trade_plan_view(result)
            with st.expander("Trade Plan"):
                st.markdown(
                    f"**{plan_view['ticker']} | {plan_view['direction']} | "
                    f"{plan_view['setup_name']}**"
                )
                t1, t2, t3, t4 = st.columns(4)
                t1.metric("Confidence", plan_view["confidence"])
                t2.metric("Entry Zone", plan_view["entry_zone"])
                t3.metric("Trigger", plan_view["trigger_price"])
                t4.metric("Initial Stop", plan_view["initial_stop"])

                t5, t6, t7, t8 = st.columns(4)
                t5.metric("Target 1", plan_view["target_1"])
                t6.metric("Target 2", plan_view["target_2"])
                t7.metric("Target 3", plan_view["target_3"])
                t8.metric("Risk/Reward", plan_view["risk_reward"])

                t9, t10, t11 = st.columns(3)
                t9.metric("Expected Hold", plan_view["expected_hold"])
                t10.metric("Maximum Chase", plan_view["maximum_chase_price"])
                t11.metric("Timing", plan_view["timing_label"])

                st.markdown(
                    f"**Invalidation:** {plan_view['invalidation_condition']}"
                )
                st.markdown("**Why this trade:**")
                for reason in plan_view["reasons"]:
                    st.write(f"- {reason}")

                st.write(trade_plan.get("contract_guidance", "Use liquid contracts with tight spreads."))

                if option_liquidity.get("available"):
                    st.markdown("**Option Chain Quality**")
                    o1, o2, o3, o4 = st.columns(4)
                    o1.metric("Quality", option_liquidity.get("label", "N/A"))
                    o2.metric("Volume", f"{option_liquidity.get('volume', 0):,}")
                    o3.metric("Open Interest", f"{option_liquidity.get('open_interest', 0):,}")
                    o4.metric("Spread", f"{option_liquidity.get('spread_pct', 0)}%")
                    st.write(
                        f"{option_liquidity.get('contract', 'N/A')} | "
                        f"{option_liquidity.get('expiration', 'N/A')} | "
                        f"{money(option_liquidity.get('strike'))} strike"
                    )

                evidence = render_historical_edge(result, trade_history or [])
                render_live_plan_trade_coach(
                    result,
                    trade_history or [],
                    evidence=evidence,
                )

        coach = coach_live_setup(result)
        if coach["action"] != "Wait":
            st.markdown(
                f'<div class="notice"><strong>Guide Action: {escape(coach["action"])} | Last scan {escape(scan_stamp(result.get("timestamp")))}</strong><br>'
                f'{escape(coach["summary"])}<br>{escape(coach["next_step"])}<br>'
                f'Entry Risk: {escape(coach["chase_risk"])} | Exit Score: {coach["exit_score"]}/100 - {escape(coach["exit_label"])}</div>',
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
    render_section_header("Saved Trade Tracker", "Optional saved ideas and guide history")
    positions = load_open_positions()

    if not positions:
        render_empty_state("No saved trades yet. The Live Trade Guide above does not require manual entry.")
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
                "Guide": recommendation["coach_action"],
                "Main Reason": main_reason,
            }
        )

    st.markdown("**Active Trade Summary**")
    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

    st.markdown("**Active Trade Details**")
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    with st.expander("Trade Guide Details"):
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

    with st.expander("Trade Guide Timeline"):
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
            render_empty_state("No guide changes logged for this trade yet.")
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
                "Guide Action": recommendation["coach_action"],
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
    render_section_header("Trade Journal", "Closed trades and guide history")
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
            render_empty_state("No trade guide recommendations logged yet.")
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


def render_current_scanner(latest_results, symbol_groups, trade_history=None):
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
                    render_signal_card(
                        symbol,
                        latest_results.get(symbol),
                        trade_history,
                    )


def render_scanner_health(latest_results, snapshot_time, symbol_groups):
    render_section_header(
        "Scanner Health",
        "Quick check of data freshness and connected services",
    )

    total_symbols = len(latest_results)
    unavailable_count = sum(
        1 for result in latest_results.values()
        if (result or {}).get("signal") == "DATA UNAVAILABLE"
    )
    available_count = max(0, total_symbols - unavailable_count)
    price_level = "good" if available_count else "bad"
    price_state = "Working" if available_count else "No scanner data"
    price_detail = (
        f"{available_count} of {total_symbols} symbols have current scanner reads."
        if total_symbols
        else "No symbols are loaded yet."
    )

    freshness = scanner_freshness(latest_results, snapshot_time)
    scan_level = "warn" if freshness["is_stale"] else "good"
    scan_state = "Stale" if freshness["is_stale"] else "Fresh"
    scan_detail = freshness["detail"]

    finnhub_configured = secret_configured("FINNHUB_API_KEY")
    finnhub_state = "Configured" if finnhub_configured else "Missing"
    finnhub_detail = (
        f"Universe groups loaded: {len(symbol_groups)}."
        if finnhub_configured
        else "Add FINNHUB_API_KEY to expand movers, news, and after-hours context."
    )

    tradier_ready = tradier_configured()
    tradier_state = "Configured" if tradier_ready else "Optional"
    tradier_detail = (
        "Options liquidity can enrich setup quality when Tradier returns chain data."
        if tradier_ready
        else "Tradier is not required; the scanner will keep using stock/ETF data."
    )

    database_configured = secret_configured("DATABASE_URL")
    database_state = "Configured" if database_configured else "Local only"
    database_detail = (
        "Saved trade storage is pointed at the external database."
        if database_configured
        else "Saved trade data uses local app storage unless DATABASE_URL is added."
    )

    cards = [
        health_card("Price Data", price_state, price_detail, price_level),
        health_card("Scheduled Scan", scan_state, scan_detail, scan_level),
        health_card(
            "Finnhub",
            finnhub_state,
            finnhub_detail,
            "good" if finnhub_configured else "warn",
        ),
        health_card(
            "Tradier Options",
            tradier_state,
            tradier_detail,
            "good" if tradier_ready else "warn",
        ),
        health_card(
            "Database",
            database_state,
            database_detail,
            "good" if database_configured else "warn",
        ),
    ]
    st.markdown(
        f'<div class="health-grid">{"".join(cards)}</div>',
        unsafe_allow_html=True,
    )


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


def render_signal_outcomes():
    render_section_header(
        "Accuracy Tracker",
        "How recent guide ideas performed after the callout",
    )

    outcomes = load_signal_outcomes()
    if len(outcomes) == 0:
        st.markdown(
            """
            <div class="notice notice-info">
                <strong>Waiting on the first tracked setups.</strong><br>
                During market hours, Option Beacon will log qualifying guide ideas, then check whether price followed through after 5, 10, 15, 30, and 60 minutes.
                This section will become the app's feedback loop: which tickers worked, which guide states were reliable, and which reads stalled.
            </div>
            <div class="health-grid">
                <div class="health-card">
                    <div class="health-label">5 Minute Read</div>
                    <div class="health-state health-warn">Immediate reaction</div>
                    <div class="health-detail">Shows whether the setup reacted right away or faded almost immediately.</div>
                </div>
                <div class="health-card">
                    <div class="health-label">10 Minute Read</div>
                    <div class="health-state health-warn">Primary scorecard</div>
                    <div class="health-detail">Used for the short-window edge read because it matches the fast option-decision window.</div>
                </div>
                <div class="health-card">
                    <div class="health-label">30/60 Minute Reads</div>
                    <div class="health-state health-warn">Follow-through</div>
                    <div class="health-detail">Shows whether the idea kept working or started reversing after the first push.</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    summary = summarize_outcomes(outcomes)
    metric_columns = st.columns(4)
    metric_columns[0].metric("Tracked Setups", summary["tracked"])
    metric_columns[1].metric("10m Reads", summary["completed_10m"])
    metric_columns[2].metric(
        "10m Edge Rate",
        f'{summary["win_rate_10m"]:.1f}%' if summary["win_rate_10m"] is not None else "Pending",
    )
    metric_columns[3].metric(
        "Avg 10m Move",
        f'{summary["avg_return_10m"]:.2f}%' if summary["avg_return_10m"] is not None else "Pending",
    )

    if summary["completed_10m"] == 0:
        st.markdown(
            '<div class="notice notice-info"><strong>Tracking is active.</strong><br>'
            'Rows are being collected, but none are old enough for a 10-minute read yet. '
            'Once a setup has aged past 10 minutes, the short-window edge metrics will populate.</div>',
            unsafe_allow_html=True,
        )
    elif summary["win_rate_10m"] is not None:
        edge_label = "Positive short-window edge" if summary["win_rate_10m"] >= 55 else "Short-window edge still unproven"
        st.markdown(
            f'<div class="notice notice-info"><strong>{escape(edge_label)}</strong><br>'
            f'Based on tracked outcomes so far, qualifying setups followed through after 10 minutes '
            f'{summary["win_rate_10m"]:.1f}% of the time with an average 10-minute move of '
            f'{summary["avg_return_10m"]:.2f}%.</div>',
            unsafe_allow_html=True,
        )

    recent = outcomes.copy().tail(75).sort_index(ascending=False)
    recent = recent.rename(
        columns={
            "opened_at": "Opened",
            "symbol": "Symbol",
            "bias": "Bias",
            "action": "Guide State",
            "score": "Score",
            "entry_price": "Entry",
            "return_5m": "5m Move %",
            "outcome_5m": "5m Result",
            "return_10m": "10m Move %",
            "outcome_10m": "10m Result",
            "return_15m": "15m Move %",
            "outcome_15m": "15m Result",
            "return_30m": "30m Move %",
            "outcome_30m": "30m Result",
            "return_60m": "60m Move %",
            "outcome_60m": "60m Result",
            "max_favorable": "Best Move %",
            "max_adverse": "Worst Move %",
            "status": "Status",
        }
    )
    display_columns = [
        "Opened",
        "Symbol",
        "Bias",
        "Guide State",
        "Score",
        "Entry",
        "5m Move %",
        "5m Result",
        "10m Move %",
        "10m Result",
        "15m Move %",
        "15m Result",
        "30m Move %",
        "30m Result",
        "60m Move %",
        "60m Result",
        "Best Move %",
        "Worst Move %",
        "Status",
    ]
    recent = recent[[column for column in display_columns if column in recent.columns]]
    recent["Opened"] = recent["Opened"].apply(scan_stamp)

    st.dataframe(recent, use_container_width=True, hide_index=True)

    symbol_summary = summary["by_symbol"]
    if len(symbol_summary) > 0:
        st.markdown("**Best Read By Symbol**")
        symbol_summary = symbol_summary.rename(
            columns={
                "symbol": "Symbol",
                "bias": "Bias",
                "Win_Rate": "Win Rate %",
                "Avg_10m_Move": "Avg 10m Move %",
            }
        )
        st.dataframe(
            symbol_summary.head(25),
            use_container_width=True,
            hide_index=True,
        )


def render_outcome_trade_journal(records=None, latest_results=None):
    render_section_header(
        "Trade Journal",
        "Read-only performance history for generated OptionBeacon signals",
    )
    records = list(records) if records is not None else load_trade_outcomes()
    if not records:
        render_empty_state("No trade history has been recorded yet.")
        return

    symbols = ["All", *sorted({record.symbol for record in records if record.symbol})]
    setups = ["All", *sorted({record.setup for record in records if record.setup})]
    directions = [
        "All",
        *sorted({record.direction for record in records if record.direction}),
    ]
    exit_reasons = [
        "All",
        *sorted({record.exit_reason for record in records if record.exit_reason}),
    ]
    present_confidence_buckets = {
        confidence_bucket(record.confidence) for record in records
    }
    confidence_buckets = [
        "All",
        *[
            label
            for label, _lower, _upper in CONFIDENCE_BUCKETS
            if label in present_confidence_buckets
        ],
    ]

    filter_1, filter_2, filter_3 = st.columns(3)
    selected_symbol = filter_1.selectbox(
        "Symbol",
        symbols,
        key="outcome_journal_symbol",
    )
    selected_setup = filter_2.selectbox(
        "Setup",
        setups,
        key="outcome_journal_setup",
    )
    selected_direction = filter_3.selectbox(
        "Direction",
        directions,
        key="outcome_journal_direction",
    )
    filter_4, filter_5, filter_6 = st.columns(3)
    selected_exit_reason = filter_4.selectbox(
        "Exit reason",
        exit_reasons,
        key="outcome_journal_exit_reason",
    )
    selected_confidence = filter_5.selectbox(
        "Confidence bucket",
        confidence_buckets,
        key="outcome_journal_confidence",
    )
    selected_status = filter_6.selectbox(
        "Status",
        STATUS_OPTIONS,
        key="outcome_journal_status",
    )

    filtered_records = filter_trade_outcomes(
        records,
        symbol=selected_symbol,
        setup=selected_setup,
        direction=selected_direction,
        exit_reason=selected_exit_reason,
        confidence=selected_confidence,
        status=selected_status,
    )
    st.caption(f"Showing {len(filtered_records)} of {len(records)} recorded signals")

    analytics = analyze_trade_outcomes(filtered_records)
    overall = analytics["overall"]
    metric_rows = (
        (
            ("Total Signals", str(overall["total_signals"])),
            ("Entered Trades", str(overall["entered_trades"])),
            ("Closed Trades", str(overall["closed_trades"])),
            ("Never Triggered", str(overall["never_triggered"])),
            (
                "Win Rate",
                format_metric(overall["win_rate"], percentage=True),
            ),
        ),
        (
            (
                "Average Return",
                format_metric(overall["average_return"], percentage=True),
            ),
            ("Profit Factor", format_metric(overall["profit_factor"])),
            (
                "Expectancy",
                format_metric(overall["expectancy"], percentage=True),
            ),
            (
                "Average Hold Minutes",
                format_metric(overall["average_hold_minutes"]),
            ),
        ),
    )
    for metric_row in metric_rows:
        columns = st.columns(len(metric_row))
        for column, (label, value) in zip(columns, metric_row):
            column.metric(label, value)

    st.markdown("**Grouped Performance**")
    group_tabs = st.tabs(["Symbol", "Setup", "Direction", "Confidence Bucket"])
    grouped_sets = (
        analytics["by_symbol"],
        analytics["by_setup"],
        analytics["by_direction"],
        analytics["by_confidence_bucket"],
    )
    for tab, grouped_rows in zip(group_tabs, grouped_sets):
        with tab:
            display_rows = grouped_performance_rows(grouped_rows)
            if display_rows:
                st.dataframe(
                    pd.DataFrame(display_rows),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                render_empty_state("No closed trade performance is available.")

    st.markdown("**Trade History**")
    history_rows = trade_history_rows(filtered_records)
    if history_rows:
        st.dataframe(
            pd.DataFrame(history_rows),
            use_container_width=True,
            hide_index=True,
        )
    else:
        render_empty_state("No trade history matches the selected filters.")

    open_records = [
        record for record in filtered_records if open_trade_coach_eligible(record)
    ]
    if open_records:
        st.markdown("**Live Trade Coach — Open Trades**")
        now = eastern_now()
        for record in sorted(
            open_records,
            key=lambda item: item.timestamp,
            reverse=True,
        ):
            current_price = latest_symbol_price(
                latest_results or {},
                record.symbol,
            )
            try:
                evidence = historical_evidence(
                    {
                        "symbol": record.symbol,
                        "bias": record.direction,
                        "setup": record.setup,
                        "confidence": record.confidence,
                    },
                    records,
                )
            except Exception:
                evidence = None
            coach = open_trade_coach_output(
                record,
                current_price,
                now,
                evidence,
            )
            with st.expander(
                f"{record.symbol} · {record.direction} · {record.setup}",
            ):
                if coach is not None:
                    render_live_trade_coach_output(coach)


def main():
    configure_page()
    require_app_access()
    render_header()

    latest_results, high_score_history, snapshot_time, symbol_groups = scan_symbols()
    trade_evidence_history = load_trade_evidence_history()
    render_scanner_freshness_notice(latest_results, snapshot_time)

    (
        live_tab,
        after_hours_tab,
        opportunities_tab,
        journal_tab,
        history_tab,
        tools_tab,
    ) = st.tabs(
        [
            "Live Guide",
            "After Hours",
            "Opportunities",
            "Trade Journal",
            "History",
            "Tools",
        ]
    )

    with live_tab:
        render_market_snapshot(latest_results)
        render_beacon_tape(latest_results)
        render_beacon_board(latest_results, high_score_history)
        st.divider()
        render_live_trade_coach(latest_results, high_score_history)
        st.divider()
        render_live_coach_alerts()

    with after_hours_tab:
        render_after_hours(latest_results)

    with opportunities_tab:
        render_top_opportunities(
            latest_results,
            high_score_history,
            trade_evidence_history,
        )
        st.divider()
        render_sector_strength(latest_results)
        st.divider()
        render_ranked_setup_table(latest_results)
        with st.expander("Full Scanner"):
            render_current_scanner(
                latest_results,
                symbol_groups,
                trade_evidence_history,
            )

    with journal_tab:
        render_outcome_trade_journal(
            trade_evidence_history,
            latest_results,
        )

    with history_tab:
        render_coach_timeline()
        st.divider()
        render_recent_high_scores(high_score_history)
        st.divider()
        render_signal_outcomes()
        st.divider()
        render_trade_journal()

    with tools_tab:
        render_scanner_health(latest_results, snapshot_time, symbol_groups)
        st.divider()
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
