from pathlib import Path

from ui_navigation import (
    CARD_NAVIGATION_CSS,
    MAIN_NAVIGATION,
    navigation_markup,
    selected_navigation_page,
)


EXPECTED_PAGES = (
    "Trade Desk",
    "Opportunities",
    "After Hours",
    "History",
    "Tools",
    "Developer Tools",
)


def test_all_navigation_labels_render_in_order():
    markup = navigation_markup("Trade Desk")

    assert MAIN_NAVIGATION == EXPECTED_PAGES
    assert all(label in markup for label in EXPECTED_PAGES)
    assert [markup.index(label) for label in EXPECTED_PAGES] == sorted(
        markup.index(label) for label in EXPECTED_PAGES
    )


def test_active_and_inactive_card_styles_are_applied():
    markup = navigation_markup("Developer Tools")

    assert (
        'class="ob-nav-card ob-nav-card-active" href="?page=developer-tools"'
        in markup
    )
    assert 'class="ob-nav-card" href="?page=trade-desk"' in markup
    assert markup.count("ob-nav-card-active") == 1


def test_developer_tools_uses_the_same_navigation_renderer():
    markup = navigation_markup("Developer Tools")

    assert markup.count('class="ob-nav-card') == len(MAIN_NAVIGATION)
    assert "Developer Tools" in markup


def test_default_page_and_existing_selection_behavior():
    assert selected_navigation_page({}) == "Trade Desk"
    assert selected_navigation_page({"page": "history"}) == "History"
    assert selected_navigation_page({"page": ["developer-tools"]}) == "Developer Tools"
    assert selected_navigation_page({"page": "unknown"}) == "Trade Desk"


def test_responsive_wrapping_preserves_card_classes():
    assert ".ob-nav-grid" in CARD_NAVIGATION_CSS
    assert "grid-template-columns: repeat(5" in CARD_NAVIGATION_CSS
    assert "@media (max-width: 900px)" in CARD_NAVIGATION_CSS
    assert "@media (max-width: 600px)" in CARD_NAVIGATION_CSS
    assert ".ob-nav-card" in CARD_NAVIGATION_CSS


def test_navigation_does_not_depend_on_generated_streamlit_classes():
    forbidden = (".stTabs", ".st-", ".css-", "emotion-cache", "[class^=")
    assert not any(selector in CARD_NAVIGATION_CSS for selector in forbidden)


def test_hosted_execution_has_no_native_tab_fallback():
    app_source = Path("app.py").read_text(encoding="utf-8")

    assert "render_card_navigation()" in app_source
    assert "st.tabs(MAIN_NAVIGATION)" not in app_source
