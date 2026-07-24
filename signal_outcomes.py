import hashlib
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
from pandas.errors import EmptyDataError

from live_trade_coach import ACTION_AVOID, ACTION_WAIT, coach_live_setup
from optionbeacon_snapshot import REMOTE_DATA_BASE_URL


OUTCOME_FILE = "signal_outcomes.csv"
REMOTE_OUTCOME_URL = f"{REMOTE_DATA_BASE_URL}/{OUTCOME_FILE}"
TRACK_MIN_SCORE = 60
MAX_ROWS = 750
HORIZONS = (15, 30, 60)

OUTCOME_COLUMNS = [
    "event_id",
    "opened_at",
    "last_checked_at",
    "symbol",
    "bias",
    "action",
    "score",
    "entry_price",
    "target_price",
    "stop_price",
    "price_15m",
    "return_15m",
    "outcome_15m",
    "price_30m",
    "return_30m",
    "outcome_30m",
    "price_60m",
    "return_60m",
    "outcome_60m",
    "max_favorable",
    "max_adverse",
    "status",
]


def eastern_now():
    return datetime.now(ZoneInfo("America/New_York"))


def _empty_outcomes():
    return pd.DataFrame(columns=OUTCOME_COLUMNS)


def load_signal_outcomes(file_name=OUTCOME_FILE):
    if os.path.exists(file_name):
        try:
            history = pd.read_csv(file_name, dtype=str)
            return normalize_outcomes(history)
        except EmptyDataError:
            return _empty_outcomes()

    try:
        history = pd.read_csv(REMOTE_OUTCOME_URL, dtype=str)
        return normalize_outcomes(history)
    except (EmptyDataError, Exception):
        return _empty_outcomes()


def save_signal_outcomes(history, file_name=OUTCOME_FILE):
    history = normalize_outcomes(history)
    history.tail(MAX_ROWS).to_csv(file_name, index=False)


def normalize_outcomes(history):
    if history is None or len(history) == 0:
        return _empty_outcomes()

    history = history.copy()
    for column in OUTCOME_COLUMNS:
        if column not in history.columns:
            history[column] = ""
    return history[OUTCOME_COLUMNS].fillna("")


def record_signal_outcomes(latest_results, history=None, now=None, file_name=OUTCOME_FILE):
    now = now or eastern_now()
    history = normalize_outcomes(history if history is not None else load_signal_outcomes(file_name))

    history = update_open_outcomes(history, latest_results, now)
    new_rows = []
    existing_ids = set(history["event_id"].astype(str)) if len(history) else set()

    for symbol, result in latest_results.items():
        row = build_outcome_row(symbol, result, now)
        if not row or row["event_id"] in existing_ids:
            continue
        new_rows.append(row)
        existing_ids.add(row["event_id"])

    if new_rows:
        history = pd.concat([history, pd.DataFrame(new_rows)], ignore_index=True)

    save_signal_outcomes(history, file_name)
    return history, len(new_rows)


def build_outcome_row(symbol, result, now):
    if not result or result.get("signal") == "DATA UNAVAILABLE":
        return None

    bias = result.get("bias", "Neutral")
    if bias not in ["Bullish", "Bearish"]:
        return None

    score = _number(result.get("confidence"))
    if score < TRACK_MIN_SCORE:
        return None

    guide = coach_live_setup(result)
    if guide["action"] in [ACTION_WAIT, ACTION_AVOID]:
        return None

    price = _number(result.get("price"))
    if price <= 0:
        return None

    opened_at = _result_time(result, now)
    event_id = _event_id(symbol, bias, guide["action"], opened_at)
    plan = result.get("trade_plan") or {}

    return {
        "event_id": event_id,
        "opened_at": opened_at.isoformat(),
        "last_checked_at": now.isoformat(),
        "symbol": symbol,
        "bias": bias,
        "action": guide["action"],
        "score": str(int(score)),
        "entry_price": f"{price:.4f}",
        "target_price": _price_text(plan.get("target_1") or result.get("target")),
        "stop_price": _price_text(plan.get("technical_stop") or result.get("stop")),
        "price_15m": "",
        "return_15m": "",
        "outcome_15m": "",
        "price_30m": "",
        "return_30m": "",
        "outcome_30m": "",
        "price_60m": "",
        "return_60m": "",
        "outcome_60m": "",
        "max_favorable": "0.00",
        "max_adverse": "0.00",
        "status": "OPEN",
    }


def update_open_outcomes(history, latest_results, now):
    if len(history) == 0:
        return history

    updated = history.copy()
    for index, row in updated.iterrows():
        if row.get("status") == "COMPLETE":
            continue

        symbol = row.get("symbol")
        result = latest_results.get(symbol) or {}
        current_price = _number(result.get("price"))
        entry_price = _number(row.get("entry_price"))
        if current_price <= 0 or entry_price <= 0:
            continue

        opened_at = _parse_time(row.get("opened_at"))
        if opened_at is None:
            continue

        minutes_open = (pd.Timestamp(now) - pd.Timestamp(opened_at)).total_seconds() / 60
        current_return = directional_return(row.get("bias"), entry_price, current_price)
        favorable = max(_number(row.get("max_favorable")), current_return)
        adverse = min(_number(row.get("max_adverse")), current_return)

        updated.at[index, "last_checked_at"] = now.isoformat()
        updated.at[index, "max_favorable"] = f"{favorable:.2f}"
        updated.at[index, "max_adverse"] = f"{adverse:.2f}"

        for horizon in HORIZONS:
            outcome_column = f"outcome_{horizon}m"
            if minutes_open >= horizon and not str(row.get(outcome_column, "")).strip():
                updated.at[index, f"price_{horizon}m"] = f"{current_price:.4f}"
                updated.at[index, f"return_{horizon}m"] = f"{current_return:.2f}"
                updated.at[index, outcome_column] = outcome_label(current_return)

        if all(str(updated.at[index, f"outcome_{horizon}m"]).strip() for horizon in HORIZONS):
            updated.at[index, "status"] = "COMPLETE"

    return updated


def summarize_outcomes(history):
    history = normalize_outcomes(history)
    completed_30m = history[history["outcome_30m"].astype(str).str.len() > 0].copy()
    if completed_30m.empty:
        return {
            "tracked": len(history),
            "completed": 0,
            "win_rate": None,
            "avg_return": None,
            "by_symbol": pd.DataFrame(),
            "by_action": pd.DataFrame(),
        }

    completed_30m["return_value"] = pd.to_numeric(
        completed_30m["return_30m"], errors="coerce"
    ).fillna(0)
    completed_30m["win"] = completed_30m["return_value"] > 0
    by_symbol = (
        completed_30m.groupby(["symbol", "bias"])
        .agg(
            Setups=("event_id", "count"),
            Win_Rate=("win", lambda values: round(values.mean() * 100, 1)),
            Avg_30m_Move=("return_value", lambda values: round(values.mean(), 2)),
        )
        .reset_index()
        .sort_values(["Setups", "Win_Rate"], ascending=[False, False])
    )
    by_action = (
        completed_30m.groupby("action")
        .agg(
            Setups=("event_id", "count"),
            Win_Rate=("win", lambda values: round(values.mean() * 100, 1)),
            Avg_30m_Move=("return_value", lambda values: round(values.mean(), 2)),
        )
        .reset_index()
        .sort_values(["Setups", "Win_Rate"], ascending=[False, False])
    )

    return {
        "tracked": len(history),
        "completed": len(completed_30m),
        "win_rate": round(completed_30m["win"].mean() * 100, 1),
        "avg_return": round(completed_30m["return_value"].mean(), 2),
        "by_symbol": by_symbol,
        "by_action": by_action,
    }


def directional_return(bias, entry_price, current_price):
    raw_return = ((current_price - entry_price) / entry_price) * 100
    return raw_return if bias == "Bullish" else -raw_return


def outcome_label(return_value):
    if return_value >= 0.75:
        return "Strong follow-through"
    if return_value > 0:
        return "Follow-through"
    if return_value <= -0.75:
        return "Failed hard"
    return "Stalled"


def _event_id(symbol, bias, action, opened_at):
    bucket_minute = (opened_at.minute // 5) * 5
    bucket = opened_at.replace(minute=bucket_minute, second=0, microsecond=0)
    raw_id = f"{symbol}|{bias}|{action}|{bucket.isoformat()}"
    return hashlib.sha1(raw_id.encode("utf-8")).hexdigest()[:16]


def _result_time(result, fallback):
    parsed = _parse_time(result.get("timestamp"))
    return parsed or fallback


def _parse_time(value):
    if not value:
        return None
    try:
        timestamp = pd.Timestamp(value)
    except Exception:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    return timestamp.tz_convert("America/New_York").to_pydatetime()


def _number(value, default=0):
    try:
        return float(value) if value not in [None, ""] else default
    except (TypeError, ValueError):
        return default


def _price_text(value):
    value = _number(value)
    return f"{value:.4f}" if value else ""
