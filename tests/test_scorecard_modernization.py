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

    assert "if modern_style_enabled(st.query_params):" in block
    assert "render_modern_scorecard(st, score_fields, scorecard_summary)" in block
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
