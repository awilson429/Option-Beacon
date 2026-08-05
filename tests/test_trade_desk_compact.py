from dataclasses import replace
from datetime import datetime, timedelta, timezone

from option_position_tracker import position_from_trade
from option_trade_engine import PaperOptionTrade
from execution_config import ExecutionConfig
from trade_desk_compact import (
    dashboard_kpi_model,
    filtered_activity_rows,
    kpi_row_markup,
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
         "last_success_at": NOW - timedelta(seconds=18), "last_symbols_processed": 8},
        market_open=True, paper_active=True, configured_symbols=8, now=NOW,
    )
    assert healthy["severity"] == "healthy"
    assert "MARKET OPEN" in status_strip_markup(healthy)
    assert "8/8 SYMBOLS" in status_strip_markup(healthy)
    stale = status_strip_model(
        {"scanner_state": "STALE", "market_data_state": "PARTIAL"},
        market_open=True, paper_active=False,
    )
    assert stale["severity"] == "warning"
    assert "ob-desk-status-warning" in status_strip_markup(stale)


def test_profile_status_and_zero_processed_never_claim_scanner_healthy():
    state = status_strip_model(
        {"scanner_state": "CURRENT", "market_data_state": "AVAILABLE",
         "last_symbols_processed": 0}, market_open=True, paper_active=True,
        paper_profile="BROAD", configured_symbols=8, now=NOW,
    )
    markup = status_strip_markup(state)
    assert "PAPER BROAD ACTIVE" in markup
    assert "SCANNER CURRENT" not in markup
    assert "SCANNER AWAITING DATA" in markup


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
    assert "Daily Loss" in markup and "$15.00 remaining" in markup
    assert "ob-risk-warning" in markup


def test_activity_orders_filters_limits_and_expands_without_duplicates():
    events = [
        {"trade_id": "a", "event_type": "WATCH_CREATED", "event_timestamp": NOW,
         "symbol": "SPY", "description": "watch"},
        {"trade_id": "b", "event_type": "TRADE_ENTERED", "event_timestamp": NOW + timedelta(seconds=2),
         "symbol": "QQQ", "description": "enter"},
        {"trade_id": "c", "event_type": "TRADE_CLOSED", "event_timestamp": NOW + timedelta(seconds=4),
         "symbol": "NVDA", "description": "exit", "realized_return": 1},
    ]
    assert [row["Event"] for row in filtered_activity_rows(events, now=NOW, limit=2)] == ["EXIT", "ENTER"]
    assert [row["Event"] for row in filtered_activity_rows(events, selected="ENTRIES", now=NOW)] == ["ENTER"]
    assert len(filtered_activity_rows(events, now=NOW, view_all=True, limit=2)) == 3
    duplicate_exit = {**events[2], "trade_id": "paper-c", "event_type": "TARGET_REACHED"}
    assert len(filtered_activity_rows([events[2], duplicate_exit], now=NOW)) == 1


def test_recent_activity_production_default_is_six_and_controls_are_integrated():
    from pathlib import Path
    source = Path("app.py").read_text(encoding="utf-8")
    start = source.index("def render_outcome_trade_journal(")
    end = source.index("def render_live_session_opportunity(", start)
    desk = source[start:end]
    assert "limit=6" in desk
    assert "st.toggle(" not in desk
    assert 'activity_title.markdown("### Recent Activity")' in desk
    assert 'key="trade_desk_activity_all"' in desk
    assert "activity_panel_markup(activity, show_title=False)" in desk


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


def test_compact_trade_desk_uses_progressive_disclosure_and_responsive_css():
    from pathlib import Path
    source = Path("app.py").read_text(encoding="utf-8")
    theme = Path("ui/theme.py").read_text(encoding="utf-8")
    start = source.index("def render_outcome_trade_journal(")
    end = source.index("def render_live_session_opportunity(", start)
    compact = source[start:end]
    assert "dashboard_kpi_model(" in compact
    assert "st.columns([0.64, 0.36]" in compact
    assert "positions_table_markup(" in compact
    assert "risk_status_model(" in compact
    assert "activity_panel_markup(" in compact
    assert "render_recently_closed(repository)" not in compact
    assert "### Opened Alerts" not in compact
    assert "@media (max-width: 700px)" in theme
    css = theme.replace(" ", "")
    assert "grid-template-columns:repeat(5,minmax(0,1fr))" in css
    mobile = css.split("@media(max-width:700px)", 1)[1]
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
    assert ".ob-best-trade-empty" in theme
    assert ".st-key-trade_desk_activity_filter" in theme
    assert '[role="radiogroup"]' in theme
    assert ".ob-disclaimer" in theme
    assert "notice notice-warning\">Decision-support" not in source
    assert "compact_panel=True" in desk
    assert "No setup currently meets entry requirements." in desk
    assert "Â·" not in desk
    assert "Ã" not in desk


def test_healthy_status_uses_strip_without_redundant_message_banner():
    from pathlib import Path
    source = Path("app.py").read_text(encoding="utf-8")
    start = source.index("def render_outcome_trade_journal(")
    end = source.index("def render_live_session_opportunity(", start)
    desk = source[start:end]
    assert 'if status["severity"] != "healthy"' not in desk
    assert "scanner_alert or provider_alert" in desk
