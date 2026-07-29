from pathlib import Path

from ui.design_tokens import TOKENS
from ui.shared_layout import (
    SHARED_UI_CSS,
    badge_markup,
    empty_state_markup,
    metric_strip_markup,
    page_header_markup,
    status_rows_markup,
    tabs_markup,
)


def test_design_tokens_cover_shared_visual_language():
    required = {
        "page_background",
        "panel_background",
        "panel_elevated",
        "border",
        "text_primary",
        "text_secondary",
        "amber",
        "green",
        "red",
        "blue",
        "card_radius",
        "button_radius",
        "space_standard",
        "font_heading",
    }
    assert required <= TOKENS.keys()


def test_primary_pages_use_shared_page_shell_and_container():
    source = Path("app.py").read_text(encoding="utf-8")
    for renderer in (
        "render_positions_workspace",
        "render_journal_workspace",
        "render_developer_tools",
    ):
        block = source.split(f"def {renderer}", 1)[1].split("\ndef ", 1)[0]
        assert "SHARED_UI_CSS" in block
        assert "page_header_markup(" in block
    assert "max-width:1024px" in SHARED_UI_CSS


def test_shared_components_emit_common_card_badge_and_empty_classes():
    assert "ob-card" in metric_strip_markup((("Open", 1, "neutral"),))
    assert "ob-badge" in badge_markup("PASS")
    assert "ob-empty" in empty_state_markup("No records", "Nothing is available.")
    assert "ob-status-row" in status_rows_markup((("Tradier", "PASS", "Ready"),))


def test_journal_filters_and_diagnostics_are_collapsed_by_default():
    source = Path("app.py").read_text(encoding="utf-8")
    journal = source.split("def render_journal_workspace", 1)[1].split("\ndef ", 1)[0]
    developer = source.split("def render_developer_tools", 1)[1].split("\ndef ", 1)[0]
    assert 'st.expander("Filters", expanded=False)' in journal
    for label in (
        "Tradier connection",
        "Finnhub connection",
        "Option Engine verification",
        "Position tracking verification",
        "Trade Plan Engine verification",
    ):
        assert f'st.expander("{label}")' in developer


def test_page_tabs_and_headers_preserve_complete_values():
    header = page_header_markup("Positions", "Manage active paper trades.")
    tabs = tabs_markup(
        (("Trades", "#trades"), ("Signals", "#signals"), ("Analytics", "#analytics")),
        "Trades",
    )
    assert "Positions" in header
    assert "ob-page-tab-active" in tabs
    assert "text-overflow" not in SHARED_UI_CSS
    assert "ellipsis" not in SHARED_UI_CSS


def test_primary_workspaces_do_not_use_oversized_metrics_or_legacy_header():
    source = Path("app.py").read_text(encoding="utf-8")
    primary = source.split("def render_developer_tools", 1)[1].split("\ndef main", 1)[0]
    assert "st.metric(" not in primary
    main = source.split("def main", 1)[1]
    assert "render_header()" not in main


def test_workspace_content_isolation_remains_explicit():
    source = Path("app.py").read_text(encoding="utf-8")
    positions = source.split("def render_positions_workspace", 1)[1].split("\ndef ", 1)[0]
    journal = source.split("def render_journal_workspace", 1)[1].split("\ndef ", 1)[0]
    developer = source.split("def render_developer_tools", 1)[1].split("\ndef ", 1)[0]
    assert "render_live_session_opportunity" not in positions
    assert "render_live_session_opportunity" not in journal
    assert "scan_symbols(" not in developer
