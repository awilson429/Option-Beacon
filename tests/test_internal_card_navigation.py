from pathlib import Path

from ui_navigation import (
    CARD_NAVIGATION,
    CARD_NAVIGATION_CSS,
    DESKTOP_NAVIGATION_COLUMNS,
    _active_card_css,
    active_card_workspace,
    render_card_navigation,
    set_active_workspace,
)


class FakeColumn:
    def __init__(self, app):
        self.app = app

    def button(self, label, **kwargs):
        self.app.rendered.append(label)
        if self.app.clicked == label:
            kwargs["on_click"](*kwargs["args"])
            return True
        return False


class FakeStreamlit:
    def __init__(self, clicked=None, session_state=None):
        self.clicked = clicked
        self.session_state = session_state if session_state is not None else {}
        self.rendered = []
        self.markdown_calls = []
        self.column_counts = []

    def markdown(self, value, **_kwargs):
        self.markdown_calls.append(value)

    def columns(self, count):
        self.column_counts.append(count)
        return [FakeColumn(self) for _ in range(count)]


def test_default_workspace_is_trade_desk():
    state = {}

    assert active_card_workspace(state) == "Command Center"
    assert state["active_workspace"] == "Command Center"


def test_each_card_updates_active_workspace_and_navigation_remains_visible():
    state = {}
    for workspace in CARD_NAVIGATION:
        fake = FakeStreamlit(clicked=workspace, session_state=state)

        assert render_card_navigation(st_module=fake) == workspace
        assert state["active_workspace"] == workspace
        assert tuple(fake.rendered) == CARD_NAVIGATION
        assert fake.column_counts == [DESKTOP_NAVIGATION_COLUMNS]


def test_selected_workspace_is_highlighted():
    fake = FakeStreamlit(session_state={"active_workspace": "Research / Developer Tools"})

    render_card_navigation(st_module=fake)

    css = "\n".join(fake.markdown_calls)
    assert "div.st-key-ob_nav_research_developer_tools button" in css
    assert "border: 1px solid var(--ob-active-border)" in css
    assert "color: var(--ob-accent-gold) !important" in css


def test_desktop_navigation_is_one_row_of_four_columns_in_order():
    fake = FakeStreamlit()

    render_card_navigation(st_module=fake)

    assert DESKTOP_NAVIGATION_COLUMNS == 4
    assert fake.column_counts == [4]
    assert tuple(fake.rendered) == CARD_NAVIGATION


def test_button_css_uses_compact_equal_height_geometry_and_typography():
    compact = CARD_NAVIGATION_CSS.replace(" ", "")

    assert "height:2.75rem" in compact
    assert "min-height:2.75rem" in compact
    assert "border-radius:0.55rem" in compact
    assert "background:var(--ob-bg-control)" in compact
    assert "border:1pxsolidvar(--ob-border-default)" in compact
    assert "gap:0.5rem" in compact
    assert "margin:0.4rem00.7rem" in compact
    assert 'div[class*="st-key-ob_nav_"]buttonp' in compact
    assert "font-weight:650" in compact


def test_desktop_navigation_prevents_overflow_and_responsive_mode_wraps():
    compact = CARD_NAVIGATION_CSS.replace(" ", "").replace("\n", "").lower()

    assert "flex-wrap:nowrap" in compact
    assert "max-width:100%" in compact
    assert "overflow:hidden" in compact
    assert "@media(max-width:760px)" in compact
    assert "flex-wrap:wrap" in compact
    assert "flex:119rem" in compact


def test_hover_focus_and_active_states_preserve_border_and_dimensions():
    compact = CARD_NAVIGATION_CSS.replace(" ", "").replace("\n", "").lower()

    assert "box-sizing:border-box" in compact
    assert "button:hover{background:var(--ob-bg-control-hover);border-color:var(--ob-accent-gold-muted)" in compact
    assert "button:focus-visible{border-color:var(--ob-accent-gold)" in compact
    assert "transform:" not in compact
    assert "button:hover" in compact
    assert "height:2.75rem" in compact

    active = _active_card_css("Command Center").replace(" ", "").replace("\n", "").lower()
    assert "button:hover," in active
    assert "button:focus-visible{" in active
    assert "border:1pxsolidvar(--ob-active-border)" in active


def test_invalid_workspace_does_not_replace_selection():
    state = {"active_workspace": "Research / Developer Tools"}

    set_active_workspace("Unknown", state)

    assert state["active_workspace"] == "Research / Developer Tools"


def test_primary_navigation_has_no_external_page_switching():
    source = Path("ui_navigation.py").read_text(encoding="utf-8")
    card_source = source.split("def render_card_navigation", 1)[1].split(
        "\ndef ",
        1,
    )[0]

    assert "st.page_link" not in card_source
    assert "st.switch_page" not in card_source
    assert "pages/" not in card_source
    assert 'href="' not in card_source
    assert "query_params" not in card_source


def test_app_routes_only_the_selected_workspace_and_keeps_navigation_above_it():
    source = Path("app.py").read_text(encoding="utf-8")
    main_source = source.split("def main():", 1)[1]
    navigation_index = main_source.index("active_page = render_production_navigation()")
    route_indexes = [
        main_source.index(f'active_page == "{workspace}"')
            for workspace in (
                "Command Center",
                "Performance",
                "SPY / QQQ",
                "Research / Developer Tools",
        )
    ]

    assert navigation_index < min(route_indexes)
    assert main_source.count("\n    if active_page ==") == 1
    assert main_source.count("\n    elif active_page ==") == 3
    assert main_source.count("scan_symbols()") == 1
