import inspect
from datetime import datetime, timedelta, timezone

from app import render_outcome_trade_journal
from live_trade_activity import (
    activity_rows,
    format_eastern_seconds,
    format_hold_duration,
    meaningful_events,
    notification_markup,
    notification_model,
    persist_outcome_transition,
    priority_notification,
    recently_closed_rows,
    relative_age,
)
from signal_history import create_trade_record
from trade_desk_view_models import daily_scorecard
from trade_repository import TradeRepository
from trade_state_service import sync_trade_outcome


NOW = datetime(2026, 8, 3, 14, 0, tzinfo=timezone.utc)


def candidate(symbol="NVDA", trade_id="trade-1"):
    record = create_trade_record(
        trade_id=trade_id, symbol=symbol, direction="Bullish", setup="Breakout",
        confidence=91, entry=183.42, stop=182, target_1=184.12,
        target_2=185, timestamp=NOW,
    )
    record.entry_time = None
    return record


def test_authoritative_events_are_chronological_deduplicated_and_restart_safe(tmp_path):
    path = tmp_path / "state.db"
    repo = TradeRepository(path, database_url="")
    record = candidate()
    sync_trade_outcome(repo, record, source_version="test", underlying_price=183, rule_score=91)
    sync_trade_outcome(repo, record, source_version="test", underlying_price=183, rule_score=91)
    record.entry_time = NOW + timedelta(seconds=30)
    sync_trade_outcome(repo, record, source_version="test", underlying_price=183.42, rule_score=91)
    record.exit_time = NOW + timedelta(minutes=2, seconds=44)
    record.exit_reason = "TARGET_1"
    record.realized_return = .38
    record.hold_minutes = 134 / 60
    sync_trade_outcome(repo, record, source_version="test", underlying_price=184.12, rule_score=91)

    events = repo.list_trade_events(limit=20)
    types = [event["event_type"] for event in events]
    assert types.count("WATCH_CREATED") == 1
    assert types.count("TRADE_ENTERED") == 1
    assert types.count("TRADE_CLOSED") == 1
    assert "TARGET_REACHED" in types and "EXIT_SIGNAL" in types
    assert events[0]["eastern_timestamp"].endswith("-04:00")
    assert [event["event_timestamp"] for event in events] == sorted(
        [event["event_timestamp"] for event in events], reverse=True
    )
    assert len(repo.list_recent_trades()) == 1
    assert len(TradeRepository(path, database_url="").list_trade_events()) == len(events)


def test_short_trade_remains_visible_when_entry_and_exit_are_already_over(tmp_path):
    repo = TradeRepository(tmp_path / "state.db", database_url="")
    record = candidate()
    record.entry_time = NOW
    sync_trade_outcome(repo, record, underlying_price=183.42)
    record.exit_time = NOW + timedelta(minutes=2, seconds=14)
    record.exit_reason = "TARGET_1"
    record.realized_return = .38
    record.hold_minutes = 134 / 60
    sync_trade_outcome(repo, record, underlying_price=184.12)
    events = repo.list_trade_events(limit=20)
    rows = activity_rows(events, now=NOW + timedelta(minutes=3))
    assert {row["Event"] for row in rows} >= {"ENTER", "EXIT"}
    notice = notification_model(
        priority_notification(events, now=NOW + timedelta(minutes=3)),
        now=NOW + timedelta(minutes=3),
    )
    assert notice["title"] == "TRADE CLOSED — WINNER"
    assert "+0.38%" in notification_markup(notice)


def test_losing_and_eod_notifications_have_text_not_color_only():
    base = {
        "symbol": "GME", "direction": "Bearish", "event_timestamp": NOW,
        "entry_price": 100, "exit_price": 100.25, "rule_score": 80,
        "description": "GME trade closed",
    }
    loser = notification_model({**base, "event_type": "TRADE_CLOSED", "realized_return": -.25, "exit_reason": "STOP"}, now=NOW)
    assert loser["title"] == "TRADE CLOSED — LOSER"
    assert "STOP" in notification_markup(loser)
    rows = activity_rows([{**base, "event_type": "END_OF_DAY_EXIT", "exit_reason": "END_OF_DAY"}], now=NOW)
    assert rows[0]["Event"] == "EOD EXIT"


def test_time_formatting_seconds_eastern_age_and_hold_duration():
    assert format_eastern_seconds(NOW) == "10:00:00 AM ET"
    assert relative_age(NOW, NOW + timedelta(seconds=43)) == "43 sec ago"
    assert relative_age(NOW, NOW + timedelta(minutes=2)) == "2m ago"
    assert format_hold_duration(NOW, NOW + timedelta(minutes=2, seconds=14)) == "2m 14s"


def test_recently_closed_order_and_scorecard_consistency(tmp_path):
    repo = TradeRepository(tmp_path / "state.db", database_url="")
    records = []
    for index, result in enumerate((.38, -.25)):
        record = candidate(symbol=f"T{index}", trade_id=f"trade-{index}")
        record.entry_time = NOW + timedelta(minutes=index)
        record.exit_time = NOW + timedelta(minutes=index + 2)
        record.exit_reason = "TARGET_1" if result > 0 else "STOP"
        record.realized_return = result
        record.hold_minutes = 2
        sync_trade_outcome(repo, record, underlying_price=184)
        records.append(record)
    rows = recently_closed_rows(repo.list_recent_trades(), now=NOW + timedelta(minutes=5))
    assert [row["Symbol"] for row in rows] == ["T1", "T0"]
    score = daily_scorecard(records, NOW.astimezone().date())
    assert score["closed_trades"] == len(rows) == 2
    assert score["winners"] == score["losers"] == 1


def test_notification_expires_after_five_minutes_but_feed_persists():
    event = {"event_type": "TRADE_ENTERED", "event_timestamp": NOW, "trade_id": "t"}
    assert priority_notification([event], now=NOW + timedelta(minutes=4, seconds=59)) == event
    assert priority_notification([event], now=NOW + timedelta(minutes=5, seconds=1)) is None
    assert meaningful_events([event]) == [event]


def test_trade_desk_active_position_is_never_labeled_watch_and_refresh_is_lightweight():
    source = inspect.getsource(render_outcome_trade_journal)
    assert '"State": "ACTIVE"' in source
    assert "filtered_activity_rows(" in source
    assert "render_live_activity_tape(repository)" not in source
    app_source = inspect.getsource(__import__("app").render_live_activity_tape)
    assert 'run_every="10s"' in app_source
    assert "scan_symbols" not in app_source
