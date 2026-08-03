from dataclasses import replace
from datetime import datetime, timedelta, timezone

from option_position_tracker import position_from_trade
from option_trade_engine import PaperOptionTrade
from trade_desk_compact import (
    filtered_activity_rows,
    paper_active_row,
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


def test_compact_trade_desk_uses_progressive_disclosure_and_responsive_css():
    from pathlib import Path
    source = Path("app.py").read_text(encoding="utf-8")
    theme = Path("ui/theme.py").read_text(encoding="utf-8")
    start = source.index("def render_outcome_trade_journal(")
    end = source.index("def render_live_session_opportunity(", start)
    compact = source[start:end]
    assert 'st.expander("More stats", expanded=False)' in compact
    assert 'expanded=False' in compact
    assert "No active positions · best opportunity is prioritized below." in compact
    assert "render_recently_closed(repository)" not in compact
    assert "### Opened Alerts" not in compact
    assert "@media (max-width: 700px)" in theme
    assert "overflow:hidden" in theme.replace(" ", "")
