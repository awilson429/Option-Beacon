from pathlib import Path


def test_developer_tools_renders_shadow_selectivity_section():
    app = Path("app.py").read_text(encoding="utf-8")
    dashboard = Path("selectivity_dashboard.py").read_text(encoding="utf-8")
    developer = app[
        app.index("def render_developer_tools("):
        app.index("def main():")
    ]
    assert "render_selectivity_analysis(" in developer
    assert "Selectivity Analysis · Shadow Only" in dashboard
    assert "Tier Comparison · Newer Validation Trades" in dashboard
    assert "Entry vs Exit Diagnosis" in dashboard
    assert "Exploratory only" in dashboard


def test_selectivity_dashboard_is_read_only_and_not_on_trade_desk():
    app = Path("app.py").read_text(encoding="utf-8")
    dashboard = Path("selectivity_dashboard.py").read_text(encoding="utf-8")
    desk = app[
        app.index("def render_outcome_trade_journal("):
        app.index("def render_live_session_opportunity(")
    ]
    for forbidden in (".save(", ".append(", ".update_", ".create_", ".record_"):
        assert forbidden not in dashboard
    assert "Selectivity Analysis" not in desk
    assert "list_intelligence_snapshots" in dashboard
    assert "list_intelligence_outcomes" in dashboard
