from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from execution_config import ExecutionConfig
from option_position_tracker import position_from_trade
from option_trade_engine import PaperOptionTrade
from paper_execution import paper_account_summary
from paper_trading_page import (
    closed_paper_trade_rows,
    execution_journal_rows,
    execution_status_model,
    open_paper_position_rows,
)
from ui_navigation import CARD_NAVIGATION, CARD_NAVIGATION_CSS


NOW = datetime(2026, 8, 3, 18, tzinfo=timezone.utc)


def position():
    trade = PaperOptionTrade(
        trade_id="t", source_signal_id="s", created_timestamp=NOW, ticker="SPY",
        direction="Bullish", underlying_entry_price=600, confidence=95,
        historical_grade="A", scanner_score=95, entry_reason="x", expiration="2026-08-07",
        strike=600, option_type="call", option_symbol="SPY-C", delta=.5,
        implied_volatility=.2, bid=.9, ask=1.1, mid=1, spread_percent=20,
        open_interest=100, volume=100,
    )
    return position_from_trade(trade, execution_time=NOW - timedelta(minutes=12), fill_price=1, quantity=2)


def test_paper_trading_is_third_top_level_destination_and_navigation_is_responsive():
    assert CARD_NAVIGATION == (
        "Trade Desk", "Opportunities", "Paper Trading", "After Hours",
        "History", "Tools", "Developer Tools",
    )
    compact = CARD_NAVIGATION_CSS.replace(" ", "").replace("\n", "").lower()
    assert "flex-wrap:nowrap" in compact and "overflow:hidden" in compact
    assert "@media(max-width:760px)" in compact and "flex-wrap:wrap" in compact


def test_zero_account_summary_uses_valid_zero_values():
    summary = paper_account_summary([], config=ExecutionConfig(), now=NOW)
    assert summary["today_pnl"] == 0
    assert summary["open_pnl"] == 0
    assert summary["realized_pnl"] == 0
    assert summary["trades_today"] == 0
    assert summary["wins"] == summary["losses"] == 0
    assert summary["win_rate"] == 0


def test_open_position_has_full_brokerage_fields_and_unchanged_values():
    row = open_paper_position_rows([position()], ExecutionConfig(), NOW)[0]
    for field in (
        "Underlying", "Contract", "Type", "Strike", "Expiration", "Qty",
        "Entry", "Current", "Total Debit", "Current Value", "Unrealized P&L",
        "Return", "MFE", "MAE", "Entered", "Hold", "Stop", "Target", "State",
    ):
        assert field in row
    assert row["Total Debit"] == "$200.00"
    assert row["Unrealized P&L"] == "$+0.00"


def test_closed_history_is_newest_first_and_supports_today_or_all():
    first = replace(position(), status="CLOSED", exit_time=NOW - timedelta(minutes=2),
                    exit_mid=1.5, exit_return_percent=50, exit_reason="PROFIT_TARGET")
    older = replace(position(), trade_id="older", status="CLOSED",
                    entry_time=NOW - timedelta(days=1), exit_time=NOW - timedelta(days=1),
                    exit_mid=.7, exit_return_percent=-30, exit_reason="STOP_LOSS")
    assert [row["Contract"] for row in closed_paper_trade_rows([first, older], now=NOW)] == ["SPY-C"]
    all_rows = closed_paper_trade_rows([older, first], now=NOW, today_only=False)
    assert [row["Exit Reason"] for row in all_rows] == ["PROFIT_TARGET", "STOP_LOSS"]


def test_execution_status_and_journal_are_shared_state_models():
    raw = [{
        "created_at": NOW.isoformat(), "symbol": "SPY", "option_symbol": "SPY-C",
        "accepted": 0, "reason_code": "DUPLICATE_SIGNAL", "allocation_dollars": 200,
        "quantity": 2, "trade_id": "t", "risk_state_json": '{"trades_entered": 1}',
    }]
    assert execution_status_model([], raw)["trading"] == "ENABLED AT LAST DECISION"
    row = execution_journal_rows(raw, [type("Capture", (), {"trade_id": "t", "scanner_score": 95})()])[0]
    assert row["Decision"] == "REJECTED"
    assert row["Duplicate"] == "BLOCKED"
    assert row["Score"] == 95
    assert "trades_entered" in row["Daily Risk"]
    active = execution_status_model([], [], {"last_success_at": NOW.isoformat()})
    assert active["trading"] == "ENABLED — WORKER ACTIVE"


def test_page_is_sql_backed_read_only_and_trade_desk_links_without_duplication():
    source = Path("app.py").read_text(encoding="utf-8")
    page_start = source.index("def render_paper_trading_page(")
    page_end = source.index("def render_developer_tools(", page_start)
    page = source[page_start:page_end]
    desk_start = source.index("def render_outcome_trade_journal(")
    desk_end = source.index("def render_live_session_opportunity(", desk_start)
    desk = source[desk_start:desk_end]
    assert "PaperExecutionRepository" in page
    assert "paper_option_positions.json" not in page
    assert "Open Option Positions" in page
    assert "Closed PAPER Trades" in page
    assert "Execution Journal" in page
    for forbidden in (".save(", ".append(", "close_position(", "update_position("):
        assert forbidden not in page
    assert "View Paper Trading →" in desk
    assert "Open Option Positions" not in desk
    assert "Execution Journal" not in desk
