import inspect
from datetime import datetime, timezone

import app
from trade_repository import (
    REQUIRED_EVENT_READ_API,
    TradeRepository,
    projected_trade_event_summaries,
    repository_event_api_status,
)


NOW = datetime(2026, 8, 10, 14, tzinfo=timezone.utc)


def populated_repository(tmp_path):
    repository = TradeRepository(tmp_path / "state.db", database_url="")
    repository.create_opportunity(
        opportunity_id="opp", idempotency_key="opp", symbol="SPY",
        direction="Bullish", playbook="Breakout", signal_timestamp=NOW,
        source_version="contract-test",
    )
    repository.record_trade_event(
        dedup_key="event", opportunity_id="opp", symbol="SPY",
        event_type="TRADE_ENTERED", event_timestamp=NOW, description="entered",
        metadata={"unused_large_field": "x" * 1000},
    )
    return repository


def test_real_production_repository_exposes_required_event_api(tmp_path):
    repository = populated_repository(tmp_path)
    assert type(repository) is TradeRepository
    assert REQUIRED_EVENT_READ_API == (
        "list_trade_event_summaries", "count_trade_events"
    )
    assert all(hasattr(repository, name) for name in REQUIRED_EVENT_READ_API)
    assert repository_event_api_status(repository) == {
        "available": True, "missing": [], "repository_class": "TradeRepository"
    }
    assert repository.count_trade_events(event_type="TRADE_ENTERED") == 1
    assert repository.list_trade_event_summaries(limit=500)[0]["opportunity_id"] == "opp"


def test_trade_desk_smoke_reaches_real_projected_repository_path(tmp_path):
    repository = populated_repository(tmp_path)
    rows = projected_trade_event_summaries(repository, limit=500)
    assert len(rows) == 1 and rows[0]["event_type"] == "TRADE_ENTERED"
    assert "metadata" not in rows[0] and "metadata_json" not in rows[0]
    source = inspect.getsource(app.render_outcome_trade_journal)
    assert "projected_trade_event_summaries(" in source
    assert "list_trade_events(limit=5000)" not in source


def test_mixed_runtime_fallback_remains_bounded_projected_and_parameterized(tmp_path):
    real = populated_repository(tmp_path)
    class OlderRuntimeRepository:
        connection = real.connection
        _fetchall = real._fetchall
        _decode_trade_event = real._decode_trade_event
    older = OlderRuntimeRepository()
    assert repository_event_api_status(older)["missing"] == list(REQUIRED_EVENT_READ_API)
    rows = projected_trade_event_summaries(
        older, limit=1, event_type="TRADE_ENTERED", start_at=NOW, end_at=NOW
    )
    assert len(rows) == 1 and rows[0]["opportunity_id"] == "opp"
    source = inspect.getsource(projected_trade_event_summaries)
    assert "SELECT *" not in source
    assert "event_type=?" in source and "event_timestamp>=?" in source
    assert "ORDER BY event_timestamp DESC,id DESC LIMIT ?" in source
