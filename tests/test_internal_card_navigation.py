from pathlib import Path

from ui_navigation import (
    CARD_NAVIGATION,
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

    def markdown(self, value, **_kwargs):
        self.markdown_calls.append(value)

    def columns(self, count):
        return [FakeColumn(self) for _ in range(count)]


def test_default_workspace_is_trade_desk():
    state = {}

    assert active_card_workspace(state) == "Trade Desk"
    assert state["active_workspace"] == "Trade Desk"


def test_each_card_updates_active_workspace_and_navigation_remains_visible():
    state = {}
    for workspace in CARD_NAVIGATION:
        fake = FakeStreamlit(clicked=workspace, session_state=state)

        assert render_card_navigation(st_module=fake) == workspace
        assert state["active_workspace"] == workspace
        assert tuple(fake.rendered) == CARD_NAVIGATION


def test_selected_workspace_is_highlighted():
    fake = FakeStreamlit(session_state={"active_workspace": "History"})

    render_card_navigation(st_module=fake)

    css = "\n".join(fake.markdown_calls)
    assert ".st-key-ob_nav_history button" in css
    assert "border: 2px solid #d2ad4f" in css


def test_invalid_workspace_does_not_replace_selection():
    state = {"active_workspace": "Tools"}

    set_active_workspace("Unknown", state)

    assert state["active_workspace"] == "Tools"


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
    navigation_index = main_source.index("active_page = render_card_navigation()")
    route_indexes = [
        main_source.index(f'active_page == "{workspace}"')
        for workspace in (
            "Trade Desk",
            "Opportunities",
            "After Hours",
            "History",
            "Tools",
            "Developer Tools",
        )
    ]

    assert navigation_index < min(route_indexes)
    assert main_source.count("\n    if active_page ==") == 1
    assert main_source.count("\n    elif active_page ==") == 5
    assert main_source.count("scan_symbols()") == 1
