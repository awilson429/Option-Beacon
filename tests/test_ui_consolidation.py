from pathlib import Path

from ui_navigation import CARD_NAVIGATION


APP_SOURCE = Path("app.py").read_text(encoding="utf-8")


def function_source(name, next_name):
    return APP_SOURCE.split(f"def {name}", 1)[1].split(f"def {next_name}", 1)[0]


def test_primary_navigation_is_consolidated_to_six_destinations():
    assert CARD_NAVIGATION == (
        "Trade Desk", "SPY / QQQ", "Opportunities", "Paper Trading",
        "Strategy Lab", "Advanced",
    )
    main = APP_SOURCE.split("def main():", 1)[1]
    for removed in ("After Hours", "History", "Tools", "Developer Tools"):
        assert f'active_page == "{removed}"' not in main


def test_strategy_lab_collects_research_and_forward_status():
    source = function_source("render_strategy_lab", "render_advanced")
    for call in (
        "render_experiment_status(repository)",
        "render_winner_dna(st, repository)",
        "render_option_translation_autopsy(st, repository)",
        "render_selectivity_analysis(st, repository)",
        "Open BROAD Filter Effectiveness",
        "Load After Hours Briefing",
    ):
        assert call in source
    status = function_source("render_experiment_status", "render_strategy_lab")
    assert "COLLECTING FORWARD DATA" in status
    assert "authoritative winners rejected" in status
    assert "SELECT *" not in status


def test_advanced_collects_deferred_history_events_and_diagnostics():
    source = function_source("render_advanced", "main")
    for label in ("Trade History / Legacy", "Event History", "Diagnostics"):
        assert label in source
    assert source.index("Load Trade History") < source.index("render_coach_timeline()")
    assert source.index("Load Event History") < source.index("projected_trade_event_summaries(")
    assert source.index("Load Scanner Health") < source.index("render_scanner_health(")


def test_trade_desk_no_longer_owns_extended_event_history_controls():
    source = function_source("render_outcome_trade_journal", "render_paper_trading_page")
    assert "Load extended Trade Desk event history" not in source
    assert "Trade Desk event history" not in source


def test_heavy_research_actions_are_button_triggered():
    for filename, label in (
        ("winner_dna_dashboard.py", "Load Winner DNA analytics"),
        ("selectivity_dashboard.py", "Load Selectivity analytics"),
        ("option_translation_autopsy_dashboard.py", "Run Option Translation Autopsy"),
    ):
        source = Path(filename).read_text(encoding="utf-8")
        assert "st.button(" in source
        assert label in source


def test_navigation_module_is_not_imported_by_worker_hot_paths():
    for path in Path("optionbeacon/worker").glob("*.py"):
        assert "ui_navigation" not in path.read_text(encoding="utf-8")
