from pathlib import Path

from ui_navigation import (
    MAIN_NAVIGATION,
    SIDEBAR_CSS,
    render_sidebar_navigation,
    selected_navigation_page,
    sidebar_brand_markup,
)


EXPECTED_PAGES = (
    "Trade Desk",
    "Positions",
    "Journal",
    "Developer Tools",
)


class Expander:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FakeSidebar:
    calls = []

    @classmethod
    def markdown(cls, value, **_kwargs):
        cls.calls.append(("markdown", value))

    @classmethod
    def radio(cls, _label, options, **kwargs):
        cls.calls.append(("radio", tuple(options)))
        return kwargs["key"] and FakeStreamlit.session_state[kwargs["key"]]

    @classmethod
    def divider(cls):
        cls.calls.append(("divider", None))

    @classmethod
    def button(cls, label, **_kwargs):
        cls.calls.append(("button", label))
        return False

    @classmethod
    def expander(cls, label):
        cls.calls.append(("expander", label))
        return Expander()

    @classmethod
    def caption(cls, value):
        cls.calls.append(("caption", value))


class FakeStreamlit:
    session_state = {}
    sidebar = FakeSidebar
    query_params = {}


def test_sidebar_renders_all_four_primary_items_in_order():
    FakeStreamlit.session_state = {}
    FakeSidebar.calls = []

    selected = render_sidebar_navigation(
        market_open=True,
        environment="Development",
        query_params={},
        st_module=FakeStreamlit,
    )

    assert MAIN_NAVIGATION == EXPECTED_PAGES
    assert selected == "Trade Desk"
    assert ("radio", EXPECTED_PAGES) in FakeSidebar.calls


def test_default_and_existing_navigation_selection_are_preserved():
    assert selected_navigation_page({}) == "Trade Desk"
    assert selected_navigation_page({"page": "positions"}) == "Positions"
    assert selected_navigation_page({"page": ["journal"]}) == "Journal"
    assert selected_navigation_page({"page": "developer-tools"}) == "Developer Tools"
    assert selected_navigation_page({"page": "unknown"}) == "Trade Desk"
    assert (
        selected_navigation_page(
            {"page": "trade-desk"},
            {"ob_primary_page": "Journal"},
        )
        == "Journal"
    )


def test_query_link_can_replace_prior_sidebar_selection():
    FakeStreamlit.session_state = {
        "ob_primary_page": "Trade Desk",
        "_ob_primary_query_slug": "trade-desk",
    }
    FakeSidebar.calls = []

    selected = render_sidebar_navigation(
        query_params={"page": "journal"},
        st_module=FakeStreamlit,
    )

    assert selected == "Journal"
    assert FakeStreamlit.session_state["ob_primary_page"] == "Journal"


def test_active_state_uses_native_checked_radio_treatment():
    compact = SIDEBAR_CSS.replace(" ", "")

    assert "label:has(input:checked)" in compact
    assert "rgba(216,179,90,.12)" in compact


def test_sidebar_is_mobile_safe_and_not_custom_fixed_width():
    lowered = SIDEBAR_CSS.lower()

    assert "position:fixed" not in lowered.replace(" ", "")
    assert "min-width:" not in lowered.replace(" ", "")
    assert "width:" not in lowered.replace(" ", "")
    assert '[data-testid="stsidebar"]' in lowered


def test_brand_status_is_textual_and_environment_is_visible():
    markup = sidebar_brand_markup(True, "Development")

    assert "OptionBeacon" in markup
    assert "Market Open" in markup
    assert "Development" in markup


def test_app_uses_internal_card_navigation_without_page_fallback():
    source = Path("app.py").read_text(encoding="utf-8")
    navigation_source = Path("ui_navigation.py").read_text(encoding="utf-8")

    assert "active_page = render_card_navigation()" in source
    assert "st.tabs(MAIN_NAVIGATION)" not in source
    assert "st.page_link" not in navigation_source
    assert "st.switch_page" not in navigation_source
    assert 'session_state["active_workspace"]' in navigation_source
