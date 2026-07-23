import json
import os
from datetime import datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


FINNHUB_BASE_URL = "https://finnhub.io/api/v1"
EASTERN = ZoneInfo("America/New_York")


def eastern_now():
    return datetime.now(EASTERN)


def finnhub_api_key():
    env_key = os.getenv("FINNHUB_API_KEY", "").strip()
    if env_key:
        return env_key

    try:
        import streamlit as st

        return str(st.secrets.get("FINNHUB_API_KEY", "")).strip()
    except Exception:
        return ""


def _request_json(path, params, api_key=None, timeout=8):
    token = (api_key or finnhub_api_key()).strip()
    if not token:
        raise RuntimeError("FINNHUB_API_KEY is not configured.")

    query = urlencode({**params, "token": token})
    request = Request(
        f"{FINNHUB_BASE_URL}{path}?{query}",
        headers={"User-Agent": "OptionBeacon/1.0"},
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def after_hours_date_window(days=2, now=None):
    current = now or eastern_now()
    start = current.date()
    end = start + timedelta(days=days)
    return start.isoformat(), end.isoformat()


def normalize_earnings(payload, limit=25):
    entries = []
    if isinstance(payload, dict):
        entries = payload.get("earningsCalendar") or []
    elif isinstance(payload, list):
        entries = payload

    rows = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue

        symbol = str(entry.get("symbol") or "").upper().strip()
        if not symbol:
            continue

        rows.append(
            {
                "Date": entry.get("date") or "",
                "Symbol": symbol,
                "Report Time": normalize_report_time(entry.get("hour")),
                "EPS Est": entry.get("epsEstimate"),
                "Revenue Est": entry.get("revenueEstimate"),
            }
        )

    return rows[:limit]


def normalize_report_time(value):
    value = str(value or "").strip().lower()
    if value in ["bmo", "before market open"]:
        return "Before Open"
    if value in ["amc", "after market close"]:
        return "After Close"
    if value in ["dmh", "during market hours"]:
        return "During Session"
    if value:
        return value.upper()
    return "TBD"


def normalize_news(items, limit=12, now=None):
    if not isinstance(items, list):
        return []

    rows = []
    for item in items:
        if not isinstance(item, dict):
            continue

        headline = str(item.get("headline") or "").strip()
        if not headline:
            continue

        rows.append(
            {
                "Time": format_news_time(item.get("datetime"), now=now),
                "Source": item.get("source") or "Market news",
                "Headline": headline,
                "Summary": compact_summary(item.get("summary")),
                "URL": item.get("url") or "",
            }
        )

    return rows[:limit]


def format_news_time(timestamp, now=None):
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return ""

    current = now or eastern_now()
    published = datetime.fromtimestamp(ts, EASTERN)
    if published.date() == current.date():
        return published.strftime("%I:%M %p ET").lstrip("0")
    return f"{published.strftime('%b')} {published.day}, {published.strftime('%I:%M %p ET').lstrip('0')}"


def compact_summary(value, max_chars=150):
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def fetch_earnings_calendar(days=2, api_key=None):
    start, end = after_hours_date_window(days=days)
    payload = _request_json("/calendar/earnings", {"from": start, "to": end}, api_key=api_key)
    return normalize_earnings(payload)


def fetch_market_news(api_key=None):
    payload = _request_json("/news", {"category": "general"}, api_key=api_key)
    return normalize_news(payload)


def fetch_after_hours_briefing(days=2, api_key=None):
    errors = []
    earnings = []
    news = []

    try:
        earnings = fetch_earnings_calendar(days=days, api_key=api_key)
    except (RuntimeError, OSError, HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        errors.append(f"Earnings unavailable: {exc}")

    try:
        news = fetch_market_news(api_key=api_key)
    except (RuntimeError, OSError, HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        errors.append(f"News unavailable: {exc}")

    return {
        "updated_at": eastern_now().strftime("%Y-%m-%d %I:%M:%S %p ET"),
        "earnings": earnings,
        "news": news,
        "errors": errors,
    }


def after_hours_focus_rows(latest_results, min_score=80, limit=10):
    rows = []
    for symbol, result in latest_results.items():
        if not result or result.get("signal") == "DATA UNAVAILABLE":
            continue

        bias = result.get("bias", "Neutral")
        score = int(result.get("confidence") or 0)
        if score < min_score or bias not in ["Bullish", "Bearish"]:
            continue

        plan = result.get("trade_plan") or {}
        rows.append(
            {
                "Symbol": symbol,
                "Bias": bias,
                "Score": score,
                "Setup": result.get("entry_timing") or result.get("signal") or "Watch",
                "Entry Zone": format_entry_zone(plan, result),
                "Stop": format_money(plan.get("technical_stop") or result.get("stop")),
                "Next Session Read": next_session_read(result),
            }
        )

    rows.sort(key=lambda row: row["Score"], reverse=True)
    return rows[:limit]


def format_money(value):
    try:
        return f"${float(value):.2f}"
    except (TypeError, ValueError):
        return "N/A"


def format_entry_zone(plan, result):
    low = plan.get("entry_zone_low")
    high = plan.get("entry_zone_high")
    if low is not None and high is not None:
        return f"{format_money(low)}-{format_money(high)}"

    entry = result.get("entry")
    return format_money(entry)


def next_session_read(result):
    bias = result.get("bias", "Neutral")
    timing = result.get("entry_timing") or "Waiting"
    quality = result.get("quality") or result.get("signal") or "Setup forming"

    if timing == "Entry zone active":
        return f"{bias} setup is active. Recheck opening volume and VWAP before acting."
    if timing == "Avoid chasing":
        return f"{bias} setup is extended. Wait for a pullback or fresh confirmation."
    return f"{bias} setup is developing. Wait for confirmation after the next regular-session candle."
