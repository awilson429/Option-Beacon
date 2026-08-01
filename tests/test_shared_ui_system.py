from pathlib import Path

from ui.design_tokens import TOKENS
from ui.shared_layout import (
    SHARED_UI_CSS,
    badge_markup,
    compact_table_markup,
    empty_state_markup,
    metric_strip_markup,
    page_header_markup,
    status_rows_markup,
    tabs_markup,
)


def test_design_tokens_cover_shared_visual_language():
    required = {
        "bg_page",
        "bg_header",
        "bg_card",
        "bg_card_elevated",
        "bg_control",
        "bg_empty_state",
        "border_subtle",
        "border_default",
        "border_strong",
        "text_primary",
        "text_secondary",
        "text_muted",
        "accent_gold",
        "positive",
        "negative",
        "warning",
        "info",
        "card_radius",
        "button_radius",
        "space_standard",
        "font_heading",
    }
    assert required <= TOKENS.keys()


def test_default_app_preserves_approved_legacy_card_shell():
    source = Path("app.py").read_text(encoding="utf-8")
    assert "active_page = render_card_navigation()" in source
    assert "active_page = render_sidebar_navigation(" not in source
    assert "render_header()" in source
    assert "max-width:1024px" in SHARED_UI_CSS


def test_shared_components_emit_common_card_badge_and_empty_classes():
    assert "ob-card" in metric_strip_markup((("Open", 1, "neutral"),))
    assert "ob-badge" in badge_markup("PASS")
    assert "ob-empty" in empty_state_markup("No records", "Nothing is available.")
    assert "ob-status-row" in status_rows_markup((("Tradier", "PASS", "Ready"),))
    table = compact_table_markup(({"Symbol": "SPY", "Status": "OPEN"},))
    assert "ob-table" in table
    assert "SPY" in table


def test_daily_alert_and_diagnostics_controls_use_stable_keys():
    source = Path("app.py").read_text(encoding="utf-8")
    journal = source.split("def render_outcome_trade_journal", 1)[1].split("\ndef ", 1)[0]
    developer = source.split("def render_developer_tools", 1)[1].split("\ndef ", 1)[0]
    removed_keys = (
        "outcome_journal_symbol",
        "outcome_journal_setup",
        "outcome_journal_direction",
        "outcome_journal_exit_reason",
        "outcome_journal_confidence",
        "outcome_journal_status",
    )
    assert all(f'key="{key}"' not in journal for key in removed_keys)
    assert 'key="opened_alert_date"' in journal
    assert 'key="entered_alert_detail"' in journal
    for key in (
        "developer_verify_tradier",
        "developer_verify_finnhub",
        "developer_verify_option_engine",
        "developer_verify_position_tracking",
    ):
        assert f'"{key}"' in developer


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


def test_approved_default_uses_legacy_header_and_compact_scorecard_metrics():
    source = Path("app.py").read_text(encoding="utf-8")
    journal = source.split("def render_outcome_trade_journal", 1)[1].split("\ndef ", 1)[0]
    main = source.split("def main", 1)[1]
    assert main.count("render_header()") == 1
    assert "render_journal_metric(" in journal
    assert "st.metric(" not in journal


def test_primary_content_isolation_remains_explicit():
    source = Path("app.py").read_text(encoding="utf-8")
    journal = source.split("def render_outcome_trade_journal", 1)[1].split("\ndef ", 1)[0]
    developer = source.split("def render_developer_tools", 1)[1].split("\ndef ", 1)[0]
    assert "scan_symbols(" not in developer
    assert "verify_tradier_connection" not in journal
    assert "save_diagnostic_result" not in journal
