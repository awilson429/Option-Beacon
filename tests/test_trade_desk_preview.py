from datetime import datetime, timezone

from ui.trade_desk_preview.components import (
    after_hours_markup,
    confidence_factor_markup,
    format_entry_zone,
    format_price,
    icon_markup,
    logo_markup,
    opening_checklist_markup,
    premarket_setup_markup,
    premarket_watchlist_row_markup,
    readiness_badge_markup,
    readiness_class,
    render_session_selector,
    signal_row_markup,
    status_class,
    trade_desk_markup,
)
from ui.trade_desk_preview.sample_data import (
    ConfidenceFactor,
    OpeningChecklistItem,
    SessionMode,
    classify_session,
    eastern_time_label,
    format_gap,
    format_relative_activity,
    preview_data,
    resolve_session_mode,
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
    assert data.session_mode is SessionMode.MARKET_OPEN


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
    assert "preview-logo-spark" in logo
    assert "preview-logo-orbit" in logo
    assert "<svg" in icon
    assert "http" not in logo + icon


def test_unknown_preview_icon_fails_clearly():
    try:
        icon_markup("not-a-real-icon")
    except ValueError as exc:
        assert "Unknown preview icon" in str(exc)
    else:
        raise AssertionError("Unknown preview icon should fail")


def test_eastern_session_classification_boundaries():
    assert classify_session(datetime(2026, 7, 30, 13, 29, tzinfo=timezone.utc)) is SessionMode.PREMARKET
    assert classify_session(datetime(2026, 7, 30, 13, 30, tzinfo=timezone.utc)) is SessionMode.MARKET_OPEN
    assert classify_session(datetime(2026, 7, 30, 20, 0, tzinfo=timezone.utc)) is SessionMode.AFTER_HOURS


def test_manual_session_override_wins_for_browser_session():
    during_market = datetime(2026, 7, 30, 15, 0, tzinfo=timezone.utc)
    assert resolve_session_mode(during_market, "Premarket") is SessionMode.PREMARKET
    assert resolve_session_mode(during_market, SessionMode.AFTER_HOURS) is SessionMode.AFTER_HOURS


def test_session_selector_uses_manual_selection():
    class FakeStreamlit:
        def segmented_control(self, label, **kwargs):
            assert label == "Local preview session"
            assert kwargs["key"] == "trade_desk_preview_session"
            return "After Hours"

    selected = render_session_selector(
        FakeStreamlit(), datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
    )
    assert selected is SessionMode.AFTER_HOURS


def test_premarket_formatters_and_readiness_statuses():
    assert format_gap(1.8) == "+1.8%"
    assert format_gap(-.9) == "-0.9%"
    assert format_gap(0) == "0.0%"
    assert format_relative_activity(2.34) == "2.3x"
    assert readiness_class("NEAR CONFIRMATION") == "preview-readiness-near"
    assert readiness_class("INVALIDATED") == "preview-readiness-invalid"
    assert "Most conditions align" in readiness_badge_markup("NEAR CONFIRMATION")


def test_premarket_sample_and_rendering_are_complete():
    data = preview_data(
        datetime(2026, 7, 30, 12, 42, tzinfo=timezone.utc), SessionMode.PREMARKET
    )
    setup = data.premarket_setup
    markup = premarket_setup_markup(setup)
    row = premarket_watchlist_row_markup(data.premarket_watchlist[0])

    assert data.market_status == "PREMARKET"
    assert setup.symbol == "NVDA"
    assert setup.status == "NEAR CONFIRMATION"
    assert len(setup.readiness_factors) == 10
    assert len(setup.opening_checklist) == 6
    assert "BEST PREMARKET SETUP" in markup
    assert "PREMARKET READINESS" in markup
    assert "WHAT TO WATCH AT THE OPEN" in markup
    assert "NVDA" in row and "+1.8%" in row


def test_opening_checklist_and_after_hours_helpers():
    checklist = opening_checklist_markup(OpeningChecklistItem("Opening volume expands"))
    data = preview_data(mode=SessionMode.AFTER_HOURS)
    review = after_hours_markup(data)

    assert "Opening volume expands" in checklist
    assert "AFTER-HOURS REVIEW" in review
    assert "+0.58%" in review
    assert "NEXT-SESSION WATCH" in review


def test_full_preview_markup_contains_reference_sections_and_notice():
    markup = trade_desk_markup(preview_data(mode=SessionMode.MARKET_OPEN))

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

    assert "<h1>Trade Desk</h1>" not in markup
    assert "Focus on the best setups. Trade with a plan." not in markup


def test_preview_navigation_uses_requested_order_and_active_trade_desk():
    markup = trade_desk_markup(preview_data())
    labels = ("Trade Desk", "Signals", "Positions", "Journal", "Analytics", "Settings")

    offsets = [markup.index(f">{label}</span>") for label in labels]
    assert offsets == sorted(offsets)
    assert '<span class="preview-tab preview-tab-active">Trade Desk</span>' in markup
    assert ">Overview</span>" not in markup


def test_each_session_renders_only_its_preview_surface():
    premarket = trade_desk_markup(preview_data(mode=SessionMode.PREMARKET))
    market = trade_desk_markup(preview_data(mode=SessionMode.MARKET_OPEN))
    after = trade_desk_markup(preview_data(mode=SessionMode.AFTER_HOURS))

    assert "BEST PREMARKET SETUP" in premarket
    assert "PREMARKET WATCHLIST" in premarket
    assert "BEST DEVELOPING SETUP" not in premarket
    assert "BEST DEVELOPING SETUP" in market
    assert "RECENT SIGNALS" in market
    assert "AFTER-HOURS REVIEW" in after
    assert "BEST PREMARKET SETUP" not in after


def test_preview_entrypoint_remains_isolated_from_production():
    source = open("trade_desk_preview.py", encoding="utf-8").read()
    for forbidden in ("app", "optionbeacon_live", "trade_repository", "psycopg", "scanner"):
        assert forbidden not in source


def test_preview_css_is_scoped_and_responsive():
    assert ".preview-shell" in PREVIEW_CSS
    assert "@media (max-width: 1100px)" in PREVIEW_CSS
    assert "@media (max-width: 800px)" in PREVIEW_CSS
    assert "@media (prefers-reduced-motion: reduce)" in PREVIEW_CSS
    assert "max-width: 1280px" in PREVIEW_CSS
    assert "--ob-yellow:" in PREVIEW_CSS
    assert "--ob-shadow-card:" in PREVIEW_CSS
