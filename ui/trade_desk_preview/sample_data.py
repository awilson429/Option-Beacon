"""Typed, deterministic sample content for the local Trade Desk preview."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo


EASTERN = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class DevelopingSetup:
    symbol: str
    direction: str
    option_type: str
    setup: str
    status: str
    status_detail: str
    entry_zone_low: float
    entry_zone_high: float
    confirmation: str
    maximum_entry: float
    stop: float
    target_1: float
    target_2: float
    confidence: int
    risk_reward: str
    timing: str
    reason: str
    missing_confirmation: str
    invalidation: str


@dataclass(frozen=True)
class RecentSignal:
    symbol: str
    status: str
    direction: str
    option_type: str
    confidence: int
    time_label: str


@dataclass(frozen=True)
class TradeDeskPreview:
    market_status: str
    eastern_time: str
    setup: DevelopingSetup
    recent_signals: tuple[RecentSignal, ...]
    signal_count: int
    focus_tip: str


def eastern_time_label(value: datetime) -> str:
    """Format one timestamp as the compact Eastern header time."""
    localized = value
    if localized.tzinfo is None:
        localized = localized.replace(tzinfo=EASTERN)
    localized = localized.astimezone(EASTERN)
    return localized.strftime("%I:%M:%S %p ET").lstrip("0")


def preview_data(now: datetime | None = None) -> TradeDeskPreview:
    """Return local sample data without reading providers or persistence."""
    now = now or datetime.now(EASTERN)
    return TradeDeskPreview(
        market_status="MARKET OPEN",
        eastern_time=eastern_time_label(now),
        setup=DevelopingSetup(
            symbol="TSLA",
            direction="Bearish",
            option_type="PUT",
            setup="Bearish breakdown",
            status="WATCH",
            status_detail="Too early",
            entry_zone_low=301.58,
            entry_zone_high=301.88,
            confirmation="Below $301.73",
            maximum_entry=301.35,
            stop=305.85,
            target_1=297.20,
            target_2=292.30,
            confidence=46,
            risk_reward="1.00 : 1 / 2.05 : 1",
            timing="Too early",
            reason="Price is below key support with weak momentum.",
            missing_confirmation=(
                "Breakdown confirmation and increased selling volume."
            ),
            invalidation="Price above $302.90.",
        ),
        recent_signals=(
            RecentSignal("TSLA", "WATCH", "Bearish", "PUT", 46, "10:41 AM"),
            RecentSignal("SPY", "WATCH", "Bullish", "CALL", 58, "10:39 AM"),
            RecentSignal("QQQ", "WATCH", "Bullish", "CALL", 62, "10:38 AM"),
            RecentSignal("SPY", "WAIT", "Bearish", "PUT", 32, "10:37 AM"),
            RecentSignal("QQQ", "WAIT", "Bearish", "PUT", 28, "10:36 AM"),
        ),
        signal_count=85,
        focus_tip="Wait for confirmation, respect your plan, and manage risk.",
    )
