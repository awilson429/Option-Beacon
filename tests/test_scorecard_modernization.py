from pathlib import Path


def _scorecard_source():
    source = Path("app.py").read_text(encoding="utf-8")
    start = source.index("    scorecard = daily_scorecard(filtered_records, now.date())")
    end = source.index('    st.markdown("### Opened Alerts")', start)
    return source[start:end]


def test_scorecard_calculation_and_fields_are_unchanged():
    block = _scorecard_source()

    assert block.count("daily_scorecard(filtered_records, now.date())") == 1
    for label in (
        "Opened Alerts",
        "Closed Trades",
        "Winners",
        "Losers",
        "Win Rate",
        "Average Realized Return",
        "Best trade",
        "Worst trade",
        "Average hold",
    ):
        assert label in block


def test_modern_scorecard_is_opt_in_and_legacy_path_remains():
    block = _scorecard_source()

    assert "if modern_scorecard:" in block
    assert "show_indicator=True" in block
    assert "if demo_scorecard:" in block
    assert "demo_scorecard_presentation()" in block
    assert "else:" in block
    assert 'st.markdown("### Today\'s Scorecard")' in block
    assert "render_journal_metric(column, label, value, treatment)" in block


def test_opened_alerts_rendering_is_outside_scorecard_change():
    source = Path("app.py").read_text(encoding="utf-8")
    scorecard_end = source.index('    st.markdown("### Opened Alerts")')
    opened_alerts = source[scorecard_end:]

    assert 'st.markdown("### Opened Alerts")' in opened_alerts
    assert 'key="entered_alert_detail"' in opened_alerts
    assert "pd.DataFrame(opened_alerts[\"rows\"])[primary_columns]" in opened_alerts


def test_empty_history_checks_develop_style_before_returning():
    source = Path("app.py").read_text(encoding="utf-8")
    start = source.index("def render_outcome_trade_journal(")
    end = source.index("    symbols =", start)
    empty_branch = source[start:end]

    assert "modern_style_active(st.query_params, build_branch)" in empty_branch
    assert "demo_scorecard_enabled(st.query_params, build_branch)" in empty_branch
    assert "render_modern_scorecard(" in empty_branch
    assert "show_indicator=True" in empty_branch
    assert empty_branch.index("modern_style_active(") < empty_branch.index("if not records:")


def test_demo_fixture_is_presentation_only():
    source = Path("ui_modern_style.py").read_text(encoding="utf-8")

    for forbidden in (
        "signal_history",
        "paper_option",
        "write_text",
        "open(",
        "requests.",
        "scanner",
    ):
        assert forbidden not in source
