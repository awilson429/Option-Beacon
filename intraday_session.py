"""Regular-session timing rules for authoritative intraday trade outcomes."""

from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

import pandas_market_calendars as market_calendars


MARKET_TIMEZONE = ZoneInfo("America/New_York")
DEFAULT_EOD_EXIT_TIME_ET = "15:55"
MINIMUM_EOD_EXIT_TIME_ET = time(9, 30)
REGULAR_CLOSE_ET = time(16, 0)
EOD_COACH_WARNING_MINUTES = 15


class EndOfDayConfigurationError(ValueError):
    pass


def configured_eod_exit_time(value=None) -> str:
    raw = (
        os.getenv("OPTIONBEACON_EOD_EXIT_TIME_ET", DEFAULT_EOD_EXIT_TIME_ET)
        if value is None
        else value
    )
    text = str(raw or "").strip()
    try:
        parsed = time.fromisoformat(text)
    except ValueError as exc:
        raise EndOfDayConfigurationError(
            "OPTIONBEACON_EOD_EXIT_TIME_ET must use 24-hour HH:MM format."
        ) from exc
    if len(text) != 5 or parsed.second or parsed.microsecond:
        raise EndOfDayConfigurationError(
            "OPTIONBEACON_EOD_EXIT_TIME_ET must use 24-hour HH:MM format."
        )
    if not MINIMUM_EOD_EXIT_TIME_ET <= parsed < REGULAR_CLOSE_ET:
        raise EndOfDayConfigurationError(
            "OPTIONBEACON_EOD_EXIT_TIME_ET must be between 09:30 and 15:59 ET."
        )
    return text


def eastern_timestamp(value) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(MARKET_TIMEZONE)


@lru_cache(maxsize=64)
def regular_session_bounds(session_date: date) -> tuple[datetime, datetime] | None:
    schedule = market_calendars.get_calendar("NYSE").schedule(
        start_date=session_date,
        end_date=session_date,
    )
    if schedule.empty:
        return None
    row = schedule.iloc[0]
    return (
        row["market_open"].to_pydatetime().astimezone(MARKET_TIMEZONE),
        row["market_close"].to_pydatetime().astimezone(MARKET_TIMEZONE),
    )


def end_of_day_cutoff(current_timestamp, cutoff=None) -> datetime | None:
    current_et = eastern_timestamp(current_timestamp)
    bounds = regular_session_bounds(current_et.date())
    if bounds is None:
        return None
    _, session_close = bounds
    configured = time.fromisoformat(configured_eod_exit_time(cutoff))
    normal_close = datetime.combine(
        current_et.date(), REGULAR_CLOSE_ET, tzinfo=MARKET_TIMEZONE
    )
    configured_cutoff = datetime.combine(
        current_et.date(), configured, tzinfo=MARKET_TIMEZONE
    )
    lead_time = normal_close - configured_cutoff
    return session_close - lead_time


def end_of_day_exit_due(current_timestamp, cutoff=None) -> bool:
    current_et = eastern_timestamp(current_timestamp)
    cutoff_at = end_of_day_cutoff(current_et, cutoff)
    return cutoff_at is not None and current_et >= cutoff_at


def intraday_trade_exit_due(entry_timestamp, current_timestamp, cutoff=None) -> bool:
    """Return whether an entered trade has reached its session cutoff."""
    current_et = eastern_timestamp(current_timestamp)
    entry_et = eastern_timestamp(entry_timestamp)
    if regular_session_bounds(current_et.date()) is None:
        return False
    if current_et.date() > entry_et.date():
        return regular_session_bounds(entry_et.date()) is not None
    if current_et.date() < entry_et.date():
        return False
    return end_of_day_exit_due(current_et, cutoff)


def intraday_entry_allowed(current_timestamp, cutoff=None) -> bool:
    current_et = eastern_timestamp(current_timestamp)
    bounds = regular_session_bounds(current_et.date())
    cutoff_at = end_of_day_cutoff(current_et, cutoff)
    if bounds is None or cutoff_at is None:
        return False
    session_open, _ = bounds
    return session_open <= current_et < cutoff_at


def eod_coach_warning_due(current_timestamp, cutoff=None) -> bool:
    current_et = eastern_timestamp(current_timestamp)
    cutoff_at = end_of_day_cutoff(current_et, cutoff)
    if cutoff_at is None:
        return False
    return current_et >= cutoff_at - timedelta(minutes=EOD_COACH_WARNING_MINUTES)
