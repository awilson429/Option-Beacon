"""Typed, deterministic sample content for the local Trade Desk preview."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum
from zoneinfo import ZoneInfo


EASTERN = ZoneInfo("America/New_York")


class SessionMode(str, Enum):
    PREMARKET = "Premarket"
    MARKET_OPEN = "Market Open"
    AFTER_HOURS = "After Hours"


@dataclass(frozen=True)
class ConfidenceFactor:
    label: str
    positive: bool


ReadinessFactor = ConfidenceFactor


@dataclass(frozen=True)
class OpeningChecklistItem:
    label: str


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
    confidence_factors: tuple[ConfidenceFactor, ...]


@dataclass(frozen=True)
class PremarketSetup:
    symbol: str
    direction: str
    option_type: str
    setup: str
    status: str
    premarket_price: float
    prior_close: float
    gap_percent: float
    premarket_high: float
    premarket_low: float
    premarket_volume: int
    relative_activity: float
    key_support: float
    key_resistance: float
    opening_trigger: str
    confirmation: str
    maximum_chase: float
    invalidation: float
    target_1: float
    target_2: float
    readiness_score: int
    risk_reward: str
    expected_open: str
    readiness_factors: tuple[ReadinessFactor, ...]
    opening_checklist: tuple[OpeningChecklistItem, ...]


@dataclass(frozen=True)
class RecentSignal:
    symbol: str
    status: str
    direction: str
    option_type: str
    confidence: int
    time_label: str


@dataclass(frozen=True)
class PremarketWatchlistItem:
    symbol: str
    direction: str
    option_type: str
    gap_percent: float
    volume_label: str
    readiness: str
    trigger: str
    updated_time: str


@dataclass(frozen=True)
class AfterHoursSummary:
    strongest_setup: str
    closed_trade_result: float
    missed_setup: str
    next_session_watch: str
    journal_reminder: str


@dataclass(frozen=True)
class TradeDeskPreview:
    session_mode: SessionMode
    market_status: str
    eastern_time: str
    setup: DevelopingSetup
    recent_signals: tuple[RecentSignal, ...]
    signal_count: int
    focus_tip: str
    premarket_setup: PremarketSetup
    premarket_watchlist: tuple[PremarketWatchlistItem, ...]
    after_hours: AfterHoursSummary


def eastern_time(value: datetime) -> datetime:
    """Normalize aware or naive timestamps to America/New_York."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=EASTERN)
    return value.astimezone(EASTERN)


def classify_session(value: datetime) -> SessionMode:
    """Classify a timestamp using regular-session Eastern boundaries."""
    local = eastern_time(value).time().replace(tzinfo=None)
    if local < time(9, 30):
        return SessionMode.PREMARKET
    if local < time(16, 0):
        return SessionMode.MARKET_OPEN
    return SessionMode.AFTER_HOURS


def resolve_session_mode(
    value: datetime,
    manual_override: SessionMode | str | None = None,
) -> SessionMode:
    """Apply a browser-session override when supplied, otherwise classify time."""
    if manual_override is not None:
        try:
            return SessionMode(manual_override)
        except (TypeError, ValueError):
            pass
    return classify_session(value)


def eastern_time_label(value: datetime) -> str:
    """Format one timestamp as the compact Eastern header time."""
    return eastern_time(value).strftime("%I:%M:%S %p ET").lstrip("0")


def format_gap(value: float) -> str:
    """Format a synthetic premarket gap with an explicit sign."""
    return f"{float(value):+.1f}%" if value else "0.0%"


def format_relative_activity(value: float) -> str:
    """Format premarket activity as a compact relative-volume multiple."""
    return f"{float(value):.1f}x"


def readiness_explanation(status: str) -> str:
    """Return the reusable preview-only meaning of a readiness status."""
    meanings = {
        "EARLY": "Interesting movement, but insufficient structure.",
        "DEVELOPING": "Bias is forming, but confirmation is incomplete.",
        "NEAR CONFIRMATION": "Most conditions align and price is approaching the trigger.",
        "READY FOR OPEN": "The plan is defined; regular-session confirmation remains.",
        "INVALIDATED": "The premarket thesis has broken.",
    }
    return meanings.get(str(status).strip().upper(), "Readiness is unavailable.")


def preview_data(
    now: datetime | None = None,
    mode: SessionMode | str | None = None,
) -> TradeDeskPreview:
    """Return local sample data without reading providers or persistence."""
    now = now or datetime.now(EASTERN)
    session_mode = resolve_session_mode(now, mode)
    status = {
        SessionMode.PREMARKET: "PREMARKET",
        SessionMode.MARKET_OPEN: "MARKET OPEN",
        SessionMode.AFTER_HOURS: "AFTER HOURS",
    }[session_mode]
    return TradeDeskPreview(
        session_mode=session_mode,
        market_status=status,
        eastern_time=eastern_time_label(now),
        setup=DevelopingSetup(
            symbol="TSLA", direction="Bearish", option_type="PUT",
            setup="Bearish breakdown", status="WATCH", status_detail="Too early",
            entry_zone_low=301.58, entry_zone_high=301.88,
            confirmation="Below $301.73", maximum_entry=301.35, stop=305.85,
            target_1=297.20, target_2=292.30, confidence=46,
            risk_reward="1.00 : 1 / 2.05 : 1", timing="Too early",
            reason="Price is below key support with weak momentum.",
            missing_confirmation="Breakdown confirmation and increased selling volume.",
            invalidation="Price above $302.90.",
            confidence_factors=(
                ConfidenceFactor("Trend alignment", True),
                ConfidenceFactor("Price below support", True),
                ConfidenceFactor("Momentum weakening", True),
                ConfidenceFactor("Breakdown not confirmed", False),
                ConfidenceFactor("Selling volume still weak", False),
                ConfidenceFactor("Broader market not aligned", False),
            ),
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
        premarket_setup=PremarketSetup(
            symbol="NVDA", direction="Bullish", option_type="CALL",
            setup="Premarket continuation", status="NEAR CONFIRMATION",
            premarket_price=128.42, prior_close=126.15, gap_percent=1.8,
            premarket_high=128.76, premarket_low=127.38, premarket_volume=2_840_000,
            relative_activity=2.3, key_support=127.65, key_resistance=128.76,
            opening_trigger="Break above $128.76", confirmation="5-min close with volume",
            maximum_chase=129.20, invalidation=127.65, target_1=130.15,
            target_2=131.80, readiness_score=78, risk_reward="1.45 : 1 / 2.65 : 1",
            expected_open="Firm open with an early test of premarket resistance.",
            readiness_factors=(
                ReadinessFactor("Gap holding above prior close", True),
                ReadinessFactor("Premarket trend aligned", True),
                ReadinessFactor("Price holding above premarket VWAP", True),
                ReadinessFactor("Strong relative premarket activity", True),
                ReadinessFactor("Clear opening trigger", True),
                ReadinessFactor("Regular-session volume not available", False),
                ReadinessFactor("Opening range not established", False),
                ReadinessFactor("Broader market confirmation incomplete", False),
                ReadinessFactor("Premarket high not yet broken", False),
                ReadinessFactor("Spread risk elevated at the open", False),
            ),
            opening_checklist=tuple(OpeningChecklistItem(label) for label in (
                "Hold above premarket VWAP", "Break and close above premarket high",
                "Opening volume expands", "SPY and QQQ remain aligned",
                "Avoid chasing beyond the maximum entry",
                "Invalidate if price loses key support",
            )),
        ),
        premarket_watchlist=(
            PremarketWatchlistItem("NVDA", "Bullish", "CALL", 1.8, "Strong", "NEAR CONFIRMATION", "$128.76", "8:42 AM"),
            PremarketWatchlistItem("TSLA", "Bearish", "PUT", -1.2, "Elevated", "DEVELOPING", "$300.90", "8:40 AM"),
            PremarketWatchlistItem("SPY", "Bullish", "CALL", .4, "Normal", "EARLY", "$638.15", "8:39 AM"),
            PremarketWatchlistItem("QQQ", "Bullish", "CALL", .6, "Strong", "DEVELOPING", "$570.40", "8:38 AM"),
            PremarketWatchlistItem("AMD", "Bearish", "PUT", -.9, "Elevated", "NEAR CONFIRMATION", "$176.20", "8:36 AM"),
        ),
        after_hours=AfterHoursSummary(
            strongest_setup="SPY bullish continuation — 84% confidence",
            closed_trade_result=.58,
            missed_setup="QQQ breakout held above the second trigger without entry.",
            next_session_watch="NVDA near $128.76 premarket resistance.",
            journal_reminder="Review execution notes before tomorrow's opening scan.",
        ),
    )
