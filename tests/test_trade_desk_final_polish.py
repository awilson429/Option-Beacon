from pathlib import Path

from trade_journal_dashboard import format_signed_return
from ui.shared_layout import SHARED_UI_CSS
from ui_modern_style import SCORECARD_CSS


def function_source(name, next_name):
    source = Path("app.py").read_text(encoding="utf-8")
    start = source.index(f"def {name}(")
    end = source.index(f"def {next_name}(", start)
    return source[start:end]


def test_scanner_banner_renders_only_primary_status_message():
    block = function_source(
        "render_reliability_status",
        "render_historical_edge",
    )

    assert 'renderer(model["summary"])' in block
    assert "Scanner:" not in block
    assert "Storage:" not in block
    assert "Market data:" not in block
    assert "Build:" not in block


def test_average_return_label_and_value_remain_connected():
    source = Path("app.py").read_text(encoding="utf-8")
    scorecard = source[
        source.index("    scorecard = daily_scorecard(records, now.date())"):
        source.index('    st.markdown("### Opened Alerts")')
    ]

    assert '"AVG. RETURN"' in scorecard
    assert '"Average Realized Return"' not in scorecard
    assert 'format_signed_return(scorecard["average_realized_return"])' in scorecard
    assert format_signed_return(0.2) == "+0.20%"


def test_summary_cards_use_shared_geometry_and_value_classes():
    source = Path("app.py").read_text(encoding="utf-8")
    renderer = function_source("render_journal_metric", "scanner_freshness")
    theme = Path("ui/theme.py").read_text(encoding="utf-8")

    for class_name in (
        "journal-summary-card",
        "journal-summary-label",
        "journal-summary-value",
    ):
        assert class_name in renderer
        assert f".{class_name}" in theme
    for rule in (
        "display: flex;",
        "flex-direction: column;",
        "margin-top: auto;",
        "min-height: 1.8rem;",
    ):
        assert rule in theme
    assert "journal-scorecard-summary" in source
    assert ".journal-scorecard-summary" in theme


def test_opt_in_scorecard_uses_equal_height_and_baseline_rules():
    for rule in (
        "min-height: 7rem;",
        "flex-direction: column;",
        "min-height: 2rem;",
        "margin-top: auto;",
    ):
        assert rule in SCORECARD_CSS


def test_compact_badges_and_pills_share_normalized_geometry():
    theme = Path("ui/theme.py").read_text(encoding="utf-8")

    assert ".pill," in theme
    assert ".signal-pill," in theme
    assert ".board-bias-tag," in theme
    assert ".board-callout-chip," in theme
    assert ".factor-pill {" in theme
    for css in (theme, SHARED_UI_CSS):
        assert "border-radius:999px" in css.replace(" ", "")
        assert "min-height:1.8rem" in css.replace(" ", "")
        assert "line-height:1" in css.replace(" ", "")
        assert "vertical-align:middle" in css.replace(" ", "")
