from pathlib import Path

from app import signal_class
from ui.design_tokens import TOKENS, css_variables
from ui.shared_layout import SHARED_UI_CSS
from ui_navigation import CARD_NAVIGATION_CSS, _active_card_css


def test_semantic_theme_tokens_are_centralized_and_exported():
    required = {
        "bg_page", "bg_header", "bg_card", "bg_card_elevated",
        "bg_control", "bg_control_hover", "bg_empty_state",
        "border_subtle", "border_default", "border_strong", "divider",
        "text_primary", "text_secondary", "text_muted", "text_disabled",
        "accent_gold", "accent_gold_muted", "positive", "negative",
        "warning", "info", "watch_bg", "watch_border", "wait_bg",
        "wait_border", "active_bg", "active_border",
    }
    variables = css_variables()

    assert required <= TOKENS.keys()
    assert all(f"--ob-{name.replace('_', '-')}:" in variables for name in required)


def test_page_header_cards_borders_and_text_use_semantic_tokens():
    theme = Path("ui/theme.py").read_text(encoding="utf-8")

    assert "var(--ob-bg-page)" in theme
    assert "background: var(--ob-bg-header)" in theme
    assert "background: var(--ob-bg-card)" in theme
    assert "background: var(--ob-bg-card-elevated)" in theme
    assert "var(--ob-border-default)" in theme
    assert "var(--ob-divider)" in theme
    assert "#050505" not in theme


def test_navigation_uses_restrained_semantic_gold_and_stable_hover_geometry():
    navigation = CARD_NAVIGATION_CSS.lower()
    active = _active_card_css("Trade Desk").lower()

    assert "var(--ob-bg-control)" in navigation
    assert "var(--ob-bg-control-hover)" in navigation
    assert "var(--ob-border-default)" in navigation
    assert "var(--ob-accent-gold-muted)" in navigation
    assert "transform:" not in navigation
    assert "var(--ob-active-bg)" in active
    assert "var(--ob-active-border)" in active
    assert "overflow: hidden" in navigation
    assert "@media (max-width: 760px)" in navigation


def test_watch_wait_tables_and_empty_states_keep_semantic_hierarchy():
    theme = Path("ui/theme.py").read_text(encoding="utf-8")

    assert signal_class("WATCHLIST") == "signal-watch"
    assert signal_class("WAIT") == "signal-wait"
    assert ".signal-watch" in theme and "var(--ob-watch-bg)" in theme
    assert ".signal-wait" in theme and "var(--ob-wait-bg)" in theme
    assert "background:var(--ob-bg-empty-state)" in SHARED_UI_CSS
    assert "background:var(--ob-bg-card-elevated)" in SHARED_UI_CSS
    assert "background:var(--ob-bg-card);border-top:1px solid var(--ob-divider)" in SHARED_UI_CSS


def test_core_text_and_accent_contrast_remains_readable():
    for foreground in ("text_primary", "text_secondary", "text_muted", "accent_gold"):
        assert _contrast(TOKENS[foreground], TOKENS["bg_card"]) >= 4.5


def _contrast(first, second):
    lighter, darker = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _luminance(value):
    channels = [int(value[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    converted = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
    return 0.2126 * converted[0] + 0.7152 * converted[1] + 0.0722 * converted[2]
