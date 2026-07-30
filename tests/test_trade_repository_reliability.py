import threading
from datetime import datetime, timedelta, timezone

import pytest

from reliability_dashboard import reliability_status_model
from signal_history import TradeOutcome
from trade_desk_view_models import daily_scorecard
from trade_journal_dashboard import opened_alerts_analytics
from trade_repository import (
    RepositoryUnavailable,
    TradeRepository,
    opportunity_idempotency_key,
    parse_utc,
)
from trade_state_service import (
    authoritative_trade_state,
    list_trade_outcomes,
    scanner_health_state,
    sync_trade_outcome,
)


UTC = timezone.utc
NOW = datetime(2026, 7, 30, 15, 0, tzinfo=UTC)


def outcome(**overrides):
    values = {
        "trade_id": "trade-1",
        "timestamp": NOW - timedelta(minutes=20),
        "symbol": "SPY",
        "direction": "Bullish",
        "setup": "Breakout",
        "confidence": 80,
        "entry": 500.0,
        "stop": 495.0,
        "target_1": 505.0,
        "target_2": 510.0,
        "target_3": 515.0,
        "entry_time": NOW - timedelta(minutes=10),
        "exit_time": None,
        "exit_reason": None,
        "max_favorable_excursion": 1.0,
        "max_adverse_excursion": -0.2,
        "realized_return": None,
        "hold_minutes": 10.0,
    }
    values.update(overrides)
    return TradeOutcome(**values)


def repository(tmp_path):
    return TradeRepository(tmp_path / "state.db", database_url="")


def test_open_trade_survives_repository_reinitialization(tmp_path):
    first = repository(tmp_path)
    sync_trade_outcome(first, outcome())
    second = repository(tmp_path)

    assert [row["id"] for row in second.list_open_trades()] == ["trade-1"]
    assert list_trade_outcomes(second)[0].symbol == "SPY"


def test_session_state_reset_does_not_remove_stored_trade(tmp_path):
    repo = repository(tmp_path)
    sync_trade_outcome(repo, outcome())
    fake_session_state = {"selected": "Trade Desk"}
    fake_session_state.clear()

    assert len(repository(tmp_path).list_open_trades()) == 1


def test_duplicate_signal_processing_is_idempotent(tmp_path):
    repo = repository(tmp_path)
    record = outcome()
    sync_trade_outcome(repo, record)
    sync_trade_outcome(repo, record)

    assert len(repo.list_opportunities()) == 1
    assert len(repo.list_open_trades()) == 1


def test_repeated_concurrent_signal_processing_keeps_one_trade(tmp_path):
    db_path = tmp_path / "state.db"
    TradeRepository(db_path, database_url="")
    errors = []

    def process():
        try:
            sync_trade_outcome(
                TradeRepository(db_path, database_url=""),
                outcome(),
            )
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=process) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    repo = TradeRepository(db_path, database_url="")
    assert errors == []
    assert len(repo.list_opportunities()) == 1
    assert len(repo.list_open_trades()) == 1


def test_timezone_aware_storage(tmp_path):
    repo = repository(tmp_path)
    sync_trade_outcome(repo, outcome())
    opportunity = repo.list_opportunities()[0]
    trade = repo.list_open_trades()[0]

    assert parse_utc(opportunity["signal_timestamp"]).tzinfo is not None
    assert parse_utc(trade["opened_at"]).tzinfo is not None


def test_scanner_failure_is_error_not_empty_state(tmp_path):
    repo = repository(tmp_path)
    repo.record_scan_error("provider unavailable", at=NOW)
    state = authoritative_trade_state(
        db_file=tmp_path / "state.db",
        database_url="",
        now=NOW,
    )

    assert state["records"] == []
    assert state["scanner_state"] == "ERROR"
    assert "failed" in state["message"].lower()


def test_stale_heartbeat_is_reported_stale():
    state = scanner_health_state(
        {
            "last_success_at": (NOW - timedelta(minutes=47)).isoformat(),
            "last_error_at": None,
            "market_data_state": "AVAILABLE",
        },
        now=NOW,
        stale_minutes=15,
    )

    assert state["state"] == "STALE"
    assert "47 minutes" in state["message"]


def test_database_unavailable_is_visible(tmp_path):
    state = authoritative_trade_state(
        branch="main",
        database_url="",
        db_file=tmp_path / "not-used.db",
        now=NOW,
    )

    assert state["storage_state"] == "UNAVAILABLE"
    assert "may be incomplete" in state["message"]


def test_scorecard_and_opened_alerts_share_authoritative_records(tmp_path):
    repo = repository(tmp_path)
    sync_trade_outcome(repo, outcome())
    records = list_trade_outcomes(repo)

    scorecard = daily_scorecard(records, NOW.date())
    alerts = opened_alerts_analytics(records, {"SPY": 502}, NOW)

    assert scorecard["opened_alerts"] == alerts["opened_alerts"] == 1
    assert alerts["currently_open"] == len(repo.list_open_trades()) == 1


def test_closed_trade_is_not_reopened(tmp_path):
    repo = repository(tmp_path)
    closed = outcome(
        exit_time=NOW,
        exit_reason="TARGET_1",
        realized_return=1.0,
    )
    sync_trade_outcome(repo, closed)
    sync_trade_outcome(repo, closed)

    assert repo.list_open_trades() == []
    assert repo.list_recent_trades()[0]["status"] == "CLOSED"


def test_status_model_does_not_call_unknown_empty_healthy():
    model = reliability_status_model(
        {
            "storage_state": "DURABLE",
            "scanner_state": "NEVER RUN",
            "market_data_state": "UNKNOWN",
            "message": "Scanner has never completed successfully.",
        },
        market_open=True,
        latest_results={},
    )

    assert model["severity"] == "warning"
    assert "never completed" in model["summary"]


def test_status_model_distinguishes_market_closed():
    model = reliability_status_model(
        {
            "storage_state": "DURABLE",
            "scanner_state": "CURRENT",
            "market_data_state": "AVAILABLE",
            "message": "Scanner data is current.",
        },
        market_open=False,
        latest_results={"SPY": {"signal": "MARKET CLOSED / WAIT"}},
    )
    assert model["severity"] == "neutral"
    assert model["summary"].startswith("Market is closed")


def test_status_model_distinguishes_market_data_unavailable():
    model = reliability_status_model(
        {
            "storage_state": "DURABLE",
            "scanner_state": "CURRENT",
            "market_data_state": "AVAILABLE",
            "message": "Scanner data is current.",
        },
        market_open=True,
        latest_results={"SPY": {"signal": "DATA UNAVAILABLE"}},
    )
    assert model["severity"] == "warning"
    assert model["market_data_state"] == "UNAVAILABLE"


def test_idempotency_key_uses_stable_signal_fields():
    first = opportunity_idempotency_key(
        symbol="spy",
        direction="Bullish",
        playbook="Breakout",
        signal_timestamp=NOW,
        source_version="v1",
    )
    second = opportunity_idempotency_key(
        symbol="SPY",
        direction="Bullish",
        playbook="Breakout",
        signal_timestamp=NOW.isoformat(),
        source_version="v1",
    )
    assert first == second


def test_local_sqlite_repository_reports_local_development(tmp_path):
    state = authoritative_trade_state(
        db_file=tmp_path / "state.db",
        database_url="",
        now=NOW,
    )
    assert state["storage_state"] == "LOCAL DEVELOPMENT"


def test_postgres_configuration_failure_is_not_sqlite_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "postgresql://invalid.invalid/db")
    with pytest.raises(RepositoryUnavailable):
        TradeRepository(tmp_path / "state.db")
