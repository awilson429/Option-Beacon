from datetime import datetime, timezone

from ui.trade_desk_preview.components import (
    confidence_factor_markup,
    format_entry_zone,
    format_price,
    icon_markup,
    logo_markup,
    signal_row_markup,
    status_class,
    trade_desk_markup,
)
from ui.trade_desk_preview.sample_data import (
    ConfidenceFactor,
    eastern_time_label,
    preview_data,
)
from ui.trade_desk_preview.theme import PREVIEW_CSS


def test_sample_preview_contains_requested_trade_content():
    data = preview_data(datetime(2026, 7, 30, 14, 42, 18, tzinfo=timezone.utc))

    assert data.setup.symbol == "TSLA"
    assert data.setup.direction == "Bearish"
    assert data.setup.option_type == "PUT"
    assert data.setup.status == "WATCH"
    assert {signal.symbol for signal in data.recent_signals} == {
        "SPY",
        "QQQ",
        "TSLA",
    }
    assert data.signal_count == 85
    assert len(data.setup.confidence_factors) == 6
    assert sum(item.positive for item in data.setup.confidence_factors) == 3


def test_preview_formatters_are_deterministic():
    data = preview_data(datetime(2026, 7, 30, 14, 42, 18, tzinfo=timezone.utc))

    assert format_price(301.58) == "$301.58"
    assert format_entry_zone(data.setup) == "$301.58–$301.88"
    assert eastern_time_label(
        datetime(2026, 7, 30, 14, 42, 18, tzinfo=timezone.utc)
    ) == "10:42:18 AM ET"
    assert status_class("WATCH") == "preview-watch"
    assert status_class("WAIT") == "preview-negative"


def test_signal_markup_preserves_status_semantics():
    signal = preview_data().recent_signals[0]
    markup = signal_row_markup(signal)

    assert "TSLA" in markup
    assert "WATCH" in markup
    assert "preview-watch" in markup
    assert "46%" in markup


def test_confidence_factor_markup_distinguishes_positive_and_missing():
    positive = confidence_factor_markup(ConfidenceFactor("Trend alignment", True))
    missing = confidence_factor_markup(
        ConfidenceFactor("Breakdown not confirmed", False)
    )

    assert "preview-factor-positive" in positive
    assert "Trend alignment" in positive
    assert "preview-factor-missing" in missing
    assert "Breakdown not confirmed" in missing


def test_branding_and_local_icons_are_dependency_free():
    logo = logo_markup()
    icon = icon_markup("scan")

    assert "<svg" in logo
    assert "preview-logo-light" in logo
    assert "<svg" in icon
    assert "http" not in logo + icon


def test_unknown_preview_icon_fails_clearly():
    try:
        icon_markup("not-a-real-icon")
    except ValueError as exc:
        assert "Unknown preview icon" in str(exc)
    else:
        raise AssertionError("Unknown preview icon should fail")


def test_full_preview_markup_contains_reference_sections_and_notice():
    markup = trade_desk_markup(preview_data())

    for text in (
        "LOCAL UI PREVIEW",
        "OptionBeacon",
        "Trade Desk",
        "BEST DEVELOPING SETUP",
        "CONFIDENCE BREAKDOWN",
        "QUICK ACTIONS",
        "OPEN POSITIONS",
        "RECENT SIGNALS",
        "Focus Tip:",
        "No open positions",
    ):
        assert text in markup


def test_preview_css_is_scoped_and_responsive():
    assert ".preview-shell" in PREVIEW_CSS
    assert "@media (max-width: 1100px)" in PREVIEW_CSS
    assert "@media (max-width: 800px)" in PREVIEW_CSS
    assert "@media (prefers-reduced-motion: reduce)" in PREVIEW_CSS
    assert "max-width: 1280px" in PREVIEW_CSS
    assert "--ob-yellow:" in PREVIEW_CSS
    assert "--ob-shadow-card:" in PREVIEW_CSS
