import hashlib
import inspect
from datetime import datetime, timedelta, timezone

from trade_repository import TradeRepository


NOW = datetime(2026, 8, 10, 14, tzinfo=timezone.utc)


def test_production_fingerprint_is_mapped_and_removed_from_unconditional_caller():
    query = "SELECT * FROM authoritative_trade_events ORDER BY event_timestamp DESC,created_at DESC,id DESC LIMIT ?"
    assert hashlib.sha256(" ".join(query.split()).encode()).hexdigest()[:12] == "5894ef394a34"
    app = open("app.py", encoding="utf-8").read()
    desk = app[app.index("def render_outcome_trade_journal("):app.index("def render_live_session_opportunity(")]
    assert "list_trade_events(limit=5000)" not in desk
    assert "projected_trade_event_summaries(" in desk
    assert "limit=trade_desk_event_limit" in desk
    assert "Trade Desk event history" in desk


def test_projected_event_query_bounds_rows_width_and_preserves_large_request(tmp_path):
    repository = TradeRepository(tmp_path / "state.db", database_url="")
    for index in range(12):
        repository.create_opportunity(
            opportunity_id=f"opp-{index}", idempotency_key=f"opp-{index}",
            symbol="SPY", direction="Bullish", playbook="Breakout",
            signal_timestamp=NOW + timedelta(minutes=index), source_version="test",
        )
        repository.record_trade_event(
            dedup_key=f"event-{index}", opportunity_id=f"opp-{index}", symbol="SPY",
            event_type="TRADE_ENTERED" if index % 2 else "TRADE_CLOSED",
            event_timestamp=NOW + timedelta(minutes=index), description="test",
            metadata={"large_unused_payload": "x" * 1000},
        )
    default = repository.list_trade_event_summaries(limit=5)
    explicit = repository.list_trade_event_summaries(limit=5000)
    entered = repository.list_trade_event_summaries(limit=5000, event_type="TRADE_ENTERED")
    assert len(default) == 5 and len(explicit) == 12 and len(entered) == 6
    assert "metadata_json" not in default[0] and "metadata" not in default[0]
    assert repository.count_trade_events(event_type="TRADE_ENTERED") == 6


def test_server_side_time_filter_matches_previous_python_filter(tmp_path):
    repository = TradeRepository(tmp_path / "state.db", database_url="")
    for index in range(4):
        repository.create_opportunity(
            opportunity_id=f"opp-{index}", idempotency_key=f"opp-{index}",
            symbol="QQQ", direction="Bullish", playbook="Breakout",
            signal_timestamp=NOW + timedelta(minutes=index), source_version="test",
        )
        repository.record_trade_event(
            dedup_key=f"time-{index}", opportunity_id=f"opp-{index}", symbol="QQQ",
            event_type="TRADE_ENTERED", event_timestamp=NOW + timedelta(minutes=index),
            description="test",
        )
    raw = repository.list_trade_events(limit=100)
    expected = [row for row in raw if row["event_type"] == "TRADE_ENTERED"
                and row["event_timestamp"] >= (NOW + timedelta(minutes=2)).isoformat()]
    bounded = repository.list_trade_event_summaries(
        limit=100, event_type="TRADE_ENTERED", start_at=NOW + timedelta(minutes=2))
    assert [row["opportunity_id"] for row in bounded] == [row["opportunity_id"] for row in expected]


def test_worker_and_mirror_use_server_side_filters_without_provider_or_writes():
    worker = open("optionbeacon/worker/scan_once.py", encoding="utf-8").read()
    mirror = open("mirror_execution.py", encoding="utf-8").read()
    paper = open("paper_execution.py", encoding="utf-8").read()
    method = inspect.getsource(TradeRepository.list_trade_event_summaries)
    assert "event_type=?" in method and "event_timestamp>=?" in method and "SELECT *" not in method
    assert "list_trade_events(limit=5000)" not in worker
    assert "list_trade_event_summaries" in worker and "count_trade_events" in worker
    assert "list_trade_events(limit=5000)" not in mirror
    assert "list_trade_events(limit=limit)" not in paper
    assert 'event_type="TRADE_ENTERED"' in paper
