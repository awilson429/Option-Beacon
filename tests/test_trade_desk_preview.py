from datetime import datetime, timezone

from ui.trade_desk_preview.components import (
    format_entry_zone,
    format_price,
    signal_row_markup,
    status_class,
    trade_desk_markup,
)
from ui.trade_desk_preview.sample_data import (
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


def test_full_preview_markup_contains_reference_sections_and_notice():
    markup = trade_desk_markup(preview_data())

    for text in (
        "LOCAL UI PREVIEW",
        "Trade Desk",
        "BEST DEVELOPING SETUP",
        "QUICK ACTIONS",
        "OPEN POSITIONS",
        "RECENT SIGNALS",
        "Focus Tip:",
        "No open positions",
    ):
        assert text in markup


def test_preview_css_is_scoped_and_responsive():
    assert ".preview-shell" in PREVIEW_CSS
    assert "@media (max-width: 1050px)" in PREVIEW_CSS
    assert "@media (max-width: 760px)" in PREVIEW_CSS
    assert "max-width: 1240px" in PREVIEW_CSS
