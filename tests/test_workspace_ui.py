from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from workspace_ui import (
    WORKSPACE_CSS,
    market_status_markup,
    quick_actions_markup,
    recent_signal_records,
    recent_signals_markup,
)


def record(symbol, minute, **values):
    defaults = {
        "symbol": symbol,
        "direction": "Bullish",
        "confidence": 70,
        "timestamp": datetime(2026, 7, 29, 14, minute, tzinfo=timezone.utc),
        "entry_time": None,
        "exit_time": None,
        "exit_reason": None,
    }
    defaults.update(values)
    return SimpleNamespace(**defaults)


def test_market_status_and_quick_actions_render_without_clipping():
    status = market_status_markup(
        True,
        datetime(2026, 7, 29, 14, 0, tzinfo=timezone.utc),
    )
    actions = quick_actions_markup()

    assert "Market Open" in status
    for label in (
        "New Scan",
        "Watchlist",
        "Market Overview",
        "Open Positions",
        "Journal",
        "Developer Tools",
    ):
        assert label in actions
    assert "text-overflow" not in WORKSPACE_CSS.lower()
    assert "overflow:hidden" not in WORKSPACE_CSS.lower().replace(" ", "")


def test_recent_signals_are_newest_first_and_limited_to_five():
    records = [record(f"S{minute}", minute) for minute in range(7)]

    selected = recent_signal_records(records)

    assert [item.symbol for item in selected] == ["S6", "S5", "S4", "S3", "S2"]


def test_recent_signal_rows_include_complete_decision_fields():
    markup = recent_signals_markup(
        [
            record(
                "TSLA",
                1,
                direction="Bearish",
                confidence=46,
            )
        ]
    )

    assert "TSLA" in markup
    assert "WATCH" in markup
    assert "Bearish PUT" in markup
    assert "46%" in markup


def test_workspace_routing_isolated_by_selected_page():
    source = Path("app.py").read_text(encoding="utf-8")

    for page, renderer in (
        ("Trade Desk", "render_trade_desk_workspace("),
        ("Positions", "render_positions_workspace("),
        ("Journal", "render_journal_workspace("),
        ("Developer Tools", "render_developer_tools()"),
    ):
        assert f'active_page == "{page}"' in source
        assert renderer in source


def test_journal_filters_have_stable_session_keys():
    source = Path("app.py").read_text(encoding="utf-8")

    for key in (
        "journal_symbol",
        "journal_setup",
        "journal_direction",
        "journal_exit_reason",
        "journal_confidence",
        "journal_status",
        "journal_search",
    ):
        assert f'key="{key}"' in source


def test_navigation_does_not_create_trade_or_journal_records():
    source = Path("ui_navigation.py").read_text(encoding="utf-8")

    for forbidden in (
        "save_trade_plan",
        "create_trade_record",
        "capture_qualified_signals",
        "signal_history.jsonl",
        "paper_option_trades.jsonl",
    ):
        assert forbidden not in source
