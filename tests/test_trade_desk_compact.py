from dataclasses import replace
from datetime import datetime, timedelta, timezone
from html import unescape

from option_position_tracker import position_from_trade
from option_trade_engine import PaperOptionTrade
from execution_config import ExecutionConfig
from trade_desk_compact import (
    authoritative_positions_markup,
    dashboard_kpi_model,
    dashboard_shell_markup,
    filtered_activity_rows,
    kpi_row_markup,
    more_stats_markup,
    paper_active_row,
    paper_position_rows,
    positions_table_markup,
    risk_panel_markup,
    risk_status_model,
    status_strip_markup,
    status_strip_model,
    today_summary_model,
)


NOW = datetime(2026, 8, 3, 18, tzinfo=timezone.utc)


def test_healthy_status_is_compact_and_warning_is_semantic():
    healthy = status_strip_model(
        {"scanner_state": "CURRENT", "market_data_state": "AVAILABLE",
         "last_success_at": NOW - timedelta(seconds=18),
         "last_symbols_processed": 68, "current_symbol_count": 68},
        market_open=True, paper_active=True, now=NOW,
    )
    assert healthy["severity"] == "healthy"
    assert "MARKET OPEN" in status_strip_markup(healthy)
    assert "SCANNER CURRENT · 68/68" in status_strip_markup(healthy)
    stale = status_strip_model(
        {"scanner_state": "STALE", "market_data_state": "PARTIAL"},
        market_open=True, paper_active=False,
    )
    assert stale["severity"] == "warning"
    assert "SCANNER STALE" in status_strip_markup(stale)
    assert "ob-desk-status-warning" in status_strip_markup(stale)
    error = status_strip_model(
        {"scanner_state": "ERROR", "market_data_state": "ERROR"},
        market_open=True, paper_active=False, now=NOW,
    )
    assert "SCANNER ERROR" in status_strip_markup(error)
    assert "ob-desk-status-error" in status_strip_markup(error)


def test_scanning_and_waiting_use_only_authoritative_progress():
    state = status_strip_model(
        {"scanner_state": "SCANNING", "market_data_state": "SCANNING",
         "current_symbols_attempted": 30, "current_symbol_count": 68,
         "last_completed_at": NOW - timedelta(minutes=8)},
        market_open=True, paper_active=True, paper_profile="BROAD", now=NOW,
    )
    markup = status_strip_markup(state)
    assert "PAPER BROAD ACTIVE" in markup
    assert "SCANNING · 30/68" in markup
    assert "LAST COMPLETE 8M AGO" in markup
    waiting = status_strip_model(
        {"scanner_state": "WAITING", "market_data_state": "UNKNOWN"},
        market_open=True, paper_active=False, now=NOW,
    )
    assert "SCANNER WAITING" in status_strip_markup(waiting)


def test_today_summary_prioritizes_paper_and_falls_back_authoritatively():
    score = {"opened_alerts": 14, "open_positions": 3, "winners": 10,
             "losers": 4, "win_rate": 71.4}
    paper = {"today_pnl": 84.2, "open_positions": 2, "trades_today": 5,
             "wins": 4, "losses": 1, "win_rate": 80, "deployed_capital": 620}
    preferred = today_summary_model(score, paper, paper_available=True)
    assert preferred["source"] == "PAPER" and preferred["pnl"] == 84.2
    fallback = today_summary_model(score, paper, paper_available=False)
    assert fallback["source"] == "AUTHORITATIVE"
    assert fallback["trades_today"] == 14 and fallback["pnl"] is None


def test_unified_kpis_prioritize_paper_and_fallback_without_fabrication():
    config = ExecutionConfig(max_open_positions=5, max_total_deployed_capital=1250)
    score = {"open_positions": 3, "opened_alerts": 8}
    paper = {"current_equity": 5142.35, "today_pnl": 142.35,
             "open_positions": 2, "daily_loss_remaining": 82.4,
             "deployed_capital": 625}
    preferred = dashboard_kpi_model(score, paper, config, paper_available=True)
    assert preferred["source"] == "PAPER"
    assert preferred["current_equity"] == 5142.35
    assert preferred["open_positions"] == 2
    markup = kpi_row_markup(preferred)
    assert markup.count('class="ob-desk-kpi ') == 5
    assert "CURRENT EQUITY" in markup and "$5,142.35" in markup
    fallback = dashboard_kpi_model(score, paper, config, paper_available=False)
    assert fallback["source"] == "AUTHORITATIVE"
    assert fallback["open_positions"] == 3
    assert fallback["current_equity"] is None
    fallback_markup = kpi_row_markup(fallback)
    rendered = unescape(fallback_markup)
    assert rendered.count("—") == 4
    assert "Ã" not in rendered and "â€”" not in rendered
    assert "&#8212;" in fallback_markup


def test_risk_status_uses_authoritative_limits_and_semantic_thresholds():
    config = ExecutionConfig(
        max_daily_loss_dollars=100, max_total_deployed_capital=1250,
        max_trades_per_day=20, max_open_positions=5,
    )
    paper = {"realized_pnl": -85, "daily_loss_remaining": 15,
             "deployed_capital": 625, "trades_today": 8,
             "open_positions": 3}
    model = risk_status_model(paper, config, paper_available=True)
    assert [item["percent"] for item in model["items"]] == [85, 50, 40, 60]
    assert model["items"][0]["treatment"] == "warning"
    markup = risk_panel_markup(model)
    assert "Daily Loss" in markup and "85%" in markup
    assert "$15.00 remaining" not in markup
    assert "ob-risk-warning" in markup


def test_activity_orders_filters_limits_and_expands_without_duplicates():
    events = [
        {"trade_id": "a", "event_type": "WATCH_CREATED", "event_timestamp": NOW,
         "symbol": "SPY", "description": "watch"},
        {"trade_id": "b", "event_type": "TRADE_ENTERED", "event_timestamp": NOW + timedelta(seconds=2),
         "symbol": "QQQ", "description": "enter"},
        {"trade_id": "c", "event_type": "TRADE_CLOSED", "event_timestamp": NOW + timedelta(seconds=4),
         "symbol": "NVDA", "description": "exit", "realized_return": 1},
        {"trade_id": "d", "event_type": "INVALIDATED", "event_timestamp": NOW + timedelta(seconds=6),
         "symbol": "TSLA", "description": "invalid"},
    ]
    assert [row["Event"] for row in filtered_activity_rows(events, now=NOW, limit=2)] == ["EXIT", "ENTER"]
    assert [row["Event"] for row in filtered_activity_rows(events, selected="ENTRIES", now=NOW)] == ["ENTER"]
    assert len(filtered_activity_rows(events, now=NOW, view_all=True, limit=2)) == 3
    duplicate_exit = {**events[2], "trade_id": "paper-c", "event_type": "TARGET_REACHED"}
    assert len(filtered_activity_rows([events[2], duplicate_exit], now=NOW)) == 1


def test_recent_activity_production_default_is_five_and_controls_are_integrated():
    from pathlib import Path
    source = Path("app.py").read_text(encoding="utf-8")
    start = source.index("def render_outcome_trade_journal(")
    end = source.index("def render_live_session_opportunity(", start)
    desk = source[start:end]
    assert "limit=5" in desk
    assert "st.toggle(" not in desk
    assert 'st.query_params.get(' in desk
    assert '"trade_desk_activity_filter"' in desk
    assert '"trade_desk_activity_expanded"' in desk
    assert "activity_rows_markup(activity)" in desk


def test_collapsed_paper_position_row_preserves_current_calculations():
    trade = PaperOptionTrade(
        trade_id="t", source_signal_id="s", created_timestamp=NOW, ticker="SPY",
        direction="Bullish", underlying_entry_price=600, confidence=95,
        historical_grade="A", scanner_score=95, entry_reason="x", expiration="2026-08-07",
        strike=600, option_type="call", option_symbol="SPY-C", delta=.5,
        implied_volatility=.2, bid=.9, ask=1.1, mid=1, spread_percent=20,
        open_interest=100, volume=100,
    )
    position = position_from_trade(trade, execution_time=NOW - timedelta(minutes=12), fill_price=1, quantity=2)
    position = replace(position, current_mid=1.1, current_return_percent=10)
    row = paper_active_row(position, NOW)
    assert row["state"] == "ACTIVE"
    assert row["pnl_dollars"] == 20
    assert row["duration"] == "12m 00s"


def test_unified_position_table_is_newest_first_and_details_are_collapsed():
    trade = PaperOptionTrade(
        trade_id="new", source_signal_id="s", created_timestamp=NOW,
        ticker="SPY", direction="Bullish", underlying_entry_price=600,
        confidence=95, historical_grade="A", scanner_score=95,
        entry_reason="x", expiration="2026-08-07", strike=600,
        option_type="call", option_symbol="SPY-C", delta=.5,
        implied_volatility=.2, bid=.9, ask=1.1, mid=1,
        spread_percent=20, open_interest=100, volume=100,
    )
    first = position_from_trade(
        trade, execution_time=NOW - timedelta(minutes=2), fill_price=1, quantity=1
    )
    older = replace(first, trade_id="old", ticker="QQQ", option_symbol="QQQ-C",
                    entry_time=NOW - timedelta(minutes=8))
    rows = paper_position_rows([older, first], ExecutionConfig(), NOW)
    assert [row["identity"] for row in rows] == ["new", "old"]
    markup = positions_table_markup(rows)
    assert markup.index("SPY") < markup.index("QQQ")
    assert "<details>" in markup and "MFE" in markup and "MAE" in markup


def test_empty_positions_are_compact_and_populated_positions_expand():
    empty = positions_table_markup([])
    assert 'class="ob-compact-empty ob-open-positions-empty"' in empty
    assert "Open Positions" in empty and ">0<" in empty
    assert "ob-position-table" not in empty
    assert "No open positions" not in empty
    assert 'class="ob-compact-empty ob-open-positions-empty"' in authoritative_positions_markup([])

    trade = PaperOptionTrade(
        trade_id="one", source_signal_id="opp-one", created_timestamp=NOW,
        ticker="SPY", direction="Bullish", underlying_entry_price=600,
        confidence=95, historical_grade="A", scanner_score=95, entry_reason="x",
        expiration="2026-08-07", strike=600, option_type="call",
        option_symbol="SPY-C", delta=.5, implied_volatility=.2,
        bid=.9, ask=1.1, mid=1, spread_percent=20,
        open_interest=100, volume=100,
    )
    position = position_from_trade(
        trade, execution_time=NOW, fill_price=1, quantity=1
    )
    one = positions_table_markup(
        paper_position_rows([position], ExecutionConfig(), NOW)
    )
    assert "ob-position-table" in one
    assert "SPY-C" in one and "View" in one
    assert "ob-open-positions-empty" not in one


def test_empty_positions_switch_shell_to_content_driven_layout():
    common = dict(
        status="STATUS", kpis="KPIS", risk="RISK", best_trade="BEST",
        comparison="COMPARISON", authoritative_trades="AUTHORITATIVE",
        activity_rows="ACTIVITY", activity_filter="ALL", view_all=False,
        more_stats="MORE",
    )
    empty = dashboard_shell_markup(
        positions=positions_table_markup([]), positions_collapsed=True, **common
    )
    populated = dashboard_shell_markup(
        positions="FULL POSITIONS", positions_collapsed=False, **common
    )
    assert 'class="ob-trade-dashboard ob-positions-empty"' in empty
    assert 'class="ob-trade-dashboard"' in populated
    assert "ob-positions-empty" not in populated

    from pathlib import Path
    css = Path("ui/theme.py").read_text(encoding="utf-8").replace(" ", "").replace("\n", "")
    assert ".ob-open-positions-empty{box-sizing:border-box;min-height:3.25rem" in css
    assert '"positionspositions""riskrisk""comparisoncomparison"' in css
    mobile = css.split("@media(max-width:759px)", 1)[1]
    assert ".ob-open-positions-empty{min-height:3.25rem;width:100%}" in mobile
    assert "overflow-x:visible" not in css


def test_best_trade_empty_is_compact_and_populated_is_expanded(monkeypatch):
    import app

    monkeypatch.setattr(app, "opportunity_rows", lambda *args, **kwargs: [])
    empty = app.trade_desk_best_trade_markup({}, [])
    assert 'class="ob-compact-empty ob-best-trade-panel"' in empty
    assert "No qualifying setup" in empty

    candidate = {"score": 95, "result": {"trade_plan": {"entry": 100}}}
    monkeypatch.setattr(
        app, "opportunity_rows",
        lambda _results, direction, **kwargs: [candidate] if direction == "Bullish" else [],
    )
    monkeypatch.setattr(app, "actionable_trade_plan", lambda result: True)
    monkeypatch.setattr(app, "historical_evidence", lambda *args: {})
    monkeypatch.setattr(app, "matching_open_trade", lambda *args: None)
    monkeypatch.setattr(app, "opportunity_summary", lambda *args: {
        "confidence": "95", "entry": "$100", "stop": "$97",
        "target_1": "$105", "symbol": "SPY", "direction": "Bullish",
    })
    monkeypatch.setattr(
        app, "opportunity_entry_presentation",
        lambda *args, **kwargs: {"entry_status": "READY"},
    )
    monkeypatch.setattr(app, "historical_edge_summary", lambda evidence: "Supported")
    populated = app.trade_desk_best_trade_markup({}, [])
    assert 'class="ob-desk-panel ob-best-trade-panel"' in populated
    assert "ob-best-grid" in populated and "SPY" in populated
    assert "ob-compact-empty" not in populated


def test_compact_trade_desk_uses_progressive_disclosure_and_responsive_css():
    from pathlib import Path
    source = Path("app.py").read_text(encoding="utf-8")
    theme = Path("ui/theme.py").read_text(encoding="utf-8")
    start = source.index("def render_outcome_trade_journal(")
    end = source.index("def render_live_session_opportunity(", start)
    compact = source[start:end]
    assert "dashboard_kpi_model(" in compact
    assert "st.columns(" not in compact
    assert "positions_table_markup(" in compact
    assert "risk_status_model(" in compact
    assert "activity_rows_markup(" in compact
    assert "render_recently_closed(repository)" not in compact
    assert "### Opened Alerts" not in compact
    assert "@media (max-width: 759px)" in theme
    css = theme.replace(" ", "")
    assert "grid-template-columns:repeat(5,minmax(0,1fr))" in css
    mobile = css.split("@media(max-width:759px)", 1)[1]
    assert "grid-template-columns:repeat(2,minmax(0,1fr))" in mobile
    assert ".ob-position-scroll{overscroll-behavior-inline:contain}" in mobile


def test_polish_geometry_empty_states_encoding_and_segmented_controls():
    from pathlib import Path
    theme = Path("ui/theme.py").read_text(encoding="utf-8")
    source = Path("app.py").read_text(encoding="utf-8")
    start = source.index("def render_outcome_trade_journal(")
    end = source.index("def render_paper_trading_page(", start)
    desk = source[start:end]
    assert "height:4.1rem" in theme.replace(" ", "")
    assert ".ob-compact-empty" in theme
    assert ".ob-activity-filters" in theme
    assert ".ob-activity-filter.is-active" in theme
    assert ".ob-disclaimer" in theme
    assert "notice notice-warning\">Decision-support" not in source
    assert "qqq_command_card_markup(" in desk
    assert "No qualifying setup" in source
    assert "Â·" not in desk
    assert "Ã" not in desk


def test_approved_dashboard_shell_and_exact_grid_geometry_exist():
    from pathlib import Path
    source = Path("app.py").read_text(encoding="utf-8")
    theme = Path("ui/theme.py").read_text(encoding="utf-8")
    start = source.index("def render_outcome_trade_journal(")
    end = source.index("def render_live_session_opportunity(", start)
    desk = source[start:end]
    assert "dashboard_shell_markup(" in desk
    assert "st.columns(" not in desk
    assert ".ob-trade-dashboard" in theme
    compact_css = theme.replace(" ", "").replace("\n", "")
    assert "grid-template-columns:minmax(0,7fr)minmax(280px,3fr)" in compact_css
    for area in ("header", "kpis", "positions", "risk", "comparison", "authoritative", "activity", "more"):
        assert f"ob-grid-{area}" in theme or f'"{area}' in theme
    assert '"positionsrisk""comparisoncomparison""authoritativeauthoritative""activityactivity""moremore"' in compact_css
    assert "ob-grid-summary" not in theme and "ob-grid-stats" not in theme
    assert "qqq_command_card_markup(" in desk
    assert "max-width:100%" in theme.replace(" ", "")
    assert "min-height:13.2rem" not in theme
    assert "min-height:12.5rem" not in theme


def test_semantic_shell_contains_all_panels_and_inline_activity_controls():
    markup = dashboard_shell_markup(
        status="STATUS", kpis="KPIS",
        risk="RISK", best_trade="BEST", positions="POSITIONS",
        comparison="COMPARISON", authoritative_trades="AUTHORITATIVE",
        activity_rows="ACTIVITY ROWS", activity_filter="ENTRIES",
        view_all=False, more_stats="MORE",
    )
    assert markup.count('class="ob-trade-dashboard"') == 1
    for css_class in (
        "ob-grid-header", "ob-grid-kpis", "ob-grid-comparison", "ob-grid-authoritative",
        "ob-grid-risk", "ob-grid-positions", "ob-grid-activity",
        "ob-grid-more",
    ):
        assert css_class in markup
    assert markup.index("POSITIONS") < markup.index("COMPARISON")
    assert markup.index("RISK") < markup.index("COMPARISON")
    assert markup.index("COMPARISON") < markup.index("AUTHORITATIVE")
    assert "ob-grid-summary" not in markup and "ob-grid-stats" not in markup
    assert 'class="ob-activity-filter is-active"' in markup
    assert markup.index("Recent Activity") < markup.index("ACTIVITY ROWS")


def test_trade_desk_sources_contain_no_malformed_utf8_artifacts():
    from pathlib import Path
    source = (
        Path("app.py").read_text(encoding="utf-8")
        + Path("trade_desk_compact.py").read_text(encoding="utf-8")
        + Path("trade_desk_comparison.py").read_text(encoding="utf-8")
    )
    assert "Ã¢â‚¬â€" not in source
    assert "Ã‚" not in source
    assert "â€”" not in source
    assert "âˆž" not in source
    assert "Â" not in source


def test_production_sources_contain_no_known_mojibake_patterns():
    from pathlib import Path
    suspicious = (
        "\u00c3", "\u00c2", "\u00e2\u20ac", "\ufffd",
    )
    offenders = []
    for path in Path(".").rglob("*"):
        if not path.is_file() or path.suffix not in {".py", ".html", ".css", ".js"}:
            continue
        if "tests" in path.parts or ".codex-test-deps" in path.parts or ".git" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="strict")
        if any(pattern in text for pattern in suspicious):
            offenders.append(str(path))
    assert offenders == []


def test_trade_desk_paper_failures_are_observable_and_session_reads_are_independent():
    from pathlib import Path
    source = Path("app.py").read_text(encoding="utf-8")
    start = source.index("def render_outcome_trade_journal(")
    end = source.index("def render_live_session_opportunity(", start)
    desk = source[start:end]
    assert '"event": "trade_desk_paper_state_loaded"' in desk
    assert '"event": "trade_desk_paper_state_failed"' in desk
    assert '"event": "trade_desk_session_reconciliation"' in desk
    assert "exc_info=True" in desk
    assert "if paper_repository is not None and authoritative_events" in desk
    assert "if paper_available and authoritative_events" not in desk
    for field in (
        "failure_stage", "exception_class", "repository", "query_fingerprint",
        "account_positions_loaded", "session_paper_positions",
        "authoritative_session_trades", "broad_opened", "broad_closed",
        "mirror_opened", "mirror_closed", "session_date_et",
    ):
        assert field in desk


def test_more_stats_collapses_secondary_metrics_without_redundancy():
    paper = {
        "realized_pnl": 40.0, "open_pnl": -10.0, "today_pnl": 30.0,
        "trades_today": 3, "win_rate": 50.0, "average_winner": 25.0,
        "average_loser": -15.0,
    }
    score = {
        "opened_alerts": 3, "win_rate": 50.0, "best_trade": 4.0,
        "worst_trade": -2.0, "average_hold_minutes": 18.0,
    }
    stats_markup = more_stats_markup(score, paper, paper_available=True)
    assert '<details class="ob-more-stats">' in stats_markup
    assert "More Stats" in stats_markup
    assert "Total Trades" not in stats_markup and "Win Rate" not in stats_markup
    for label in ("Best Trade", "Worst Trade", "Average Win", "Average Loss", "Average Hold"):
        assert label in stats_markup
    assert "+4.00%" in stats_markup and "-2.00%" in stats_markup


def test_activity_all_hides_invalidations_and_labels_numeric_context():
    events = [
        {"trade_id": "invalid", "event_type": "INVALIDATED", "event_timestamp": NOW + timedelta(seconds=4),
         "symbol": "IWM", "underlying_price": 220},
        {"trade_id": "ready", "event_type": "ENTRY_READY", "event_timestamp": NOW + timedelta(seconds=3),
         "symbol": "SPY", "underlying_price": 610},
        {"trade_id": "entry", "event_type": "TRADE_ENTERED", "event_timestamp": NOW + timedelta(seconds=2),
         "symbol": "QQQ", "option_symbol": "QQQ-C", "underlying_price": 480, "entry_price": 1.25},
        {"trade_id": "exit", "event_type": "TRADE_CLOSED", "event_timestamp": NOW + timedelta(seconds=1),
         "symbol": "NVDA", "realized_return": 12.5},
    ]
    rows = filtered_activity_rows(events, now=NOW, view_all=True)
    assert [row["Event"] for row in rows] == ["READY", "ENTER", "EXIT"]
    assert rows[0]["Display Result"].endswith(" underlying")
    assert rows[1]["Display Result"].endswith(" entry")
    assert rows[2]["Display Result"] == "+12.50%"


def test_healthy_status_uses_strip_without_redundant_message_banner():
    from pathlib import Path
    source = Path("app.py").read_text(encoding="utf-8")
    start = source.index("def render_outcome_trade_journal(")
    end = source.index("def render_live_session_opportunity(", start)
    desk = source[start:end]
    assert 'if status["severity"] != "healthy"' not in desk
    assert "scanner_alert or provider_alert" in desk
    assert "configured_symbols=len(latest_results)" not in desk
    assert "View Paper Trading" not in Path("trade_desk_compact.py").read_text(encoding="utf-8")
