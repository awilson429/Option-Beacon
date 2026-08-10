import inspect
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from trade_desk_comparison import trade_comparison_model
from trade_repository import (
    TradeRepository,
    authoritative_session_bounds,
    authoritative_session_dates,
    authoritative_session_event_summaries,
    projected_trade_event_summaries,
)


ET = ZoneInfo("America/New_York")
SESSION = datetime(2026, 8, 10, 9, 31, tzinfo=ET)


def record(repository, identity, event_type, at, **values):
    repository.record_trade_event(
        dedup_key=f"{identity}-{event_type}-{at.timestamp()}",
        opportunity_id=identity, trade_id=identity, symbol=values.pop("symbol", "SPY"),
        direction=values.pop("direction", "Bullish"), event_type=event_type,
        event_timestamp=at, description=event_type, **values,
    )


def opportunity(repository, identity, at):
    repository.create_opportunity(
        opportunity_id=identity, idempotency_key=identity, symbol="SPY",
        direction="Bullish", playbook="TEST", signal_timestamp=at,
        source_version="session-window-test",
    )


def paper_journal(trade_id):
    return {
        "trade_id": trade_id, "accepted": 1, "reason_code": "ELIGIBLE",
        "created_at": SESSION.isoformat(), "risk_state_json": "{}",
        "metadata_json": json.dumps({
            "journal_type": "ENTRY_DECISION", "simulation_profile": "BROAD",
        }),
    }


def paper_position(trade_id):
    return SimpleNamespace(
        trade_id=trade_id, quantity=1, entry_mid=1.0, current_mid=1.1,
        exit_mid=None, status="OPEN",
    )


def mirror_row(identity):
    return {
        "opportunity_id": identity, "entry_event_at": SESSION,
        "opened_at": SESSION, "exit_quote_at": None, "status": "OPEN",
        "disposition_code": "MIRROR_OPENED", "quantity": 1,
        "total_debit": 100, "unrealized_pnl": 10,
    }


def flooded_repository(tmp_path, *, close=False):
    repository = TradeRepository(tmp_path / "state.db", database_url="")
    opportunity(repository, "early-entry", SESSION)
    opportunity(repository, "later-lifecycle", SESSION)
    record(repository, "early-entry", "TRADE_ENTERED", SESSION,
           underlying_price=600, entry_price=600)
    if close:
        record(repository, "early-entry", "TRADE_CLOSED", SESSION + timedelta(minutes=20),
               exit_price=603, realized_return=.5)
    event_types = ("TARGET_REACHED", "STOP_REACHED", "ENTRY_READY", "INVALIDATED")
    for index in range(520):
        record(repository, "later-lifecycle", event_types[index % len(event_types)],
               SESSION + timedelta(hours=1, seconds=index))
    return repository


def comparison(events, *, mirror=True):
    return trade_comparison_model(
        events, [paper_journal("paper-early")],
        [SimpleNamespace(trade_id="paper-early", source_signal_id="early-entry")],
        [paper_position("paper-early")], session_date=SESSION.date(),
        mirror_rows=[mirror_row("early-entry")] if mirror else [],
        mirror_runtime={"status": "ACTIVE", "enabled": 1,
                        "experiment_start_date": SESSION.date().isoformat()},
    )


def test_early_entry_and_exact_joins_survive_more_than_500_later_events(tmp_path):
    repository = flooded_repository(tmp_path)
    global_latest = projected_trade_event_summaries(repository, limit=500)
    assert comparison(global_latest)["authoritative"]["trades"] == 0

    session_events = authoritative_session_event_summaries(repository, SESSION.date())
    model = comparison(session_events)

    assert model["authoritative"]["trades"] == 1
    assert model["paper"]["opened"] == 1
    assert model["mirror"]["opened"] == 1
    assert len(session_events) == 1


def test_history_limit_does_not_change_complete_session_population(tmp_path):
    repository = flooded_repository(tmp_path)
    expected = None
    for history_limit in (200, 500, 1000, 5000):
        projected_trade_event_summaries(repository, limit=history_limit)
        model = comparison(authoritative_session_event_summaries(repository, SESSION.date()))
        population = (model["authoritative"]["trades"], model["paper"]["opened"],
                      model["mirror"]["opened"])
        expected = expected or population
        assert population == expected == (1, 1, 1)


def test_previous_session_comes_from_latest_prior_entry_not_history_window(tmp_path):
    repository = flooded_repository(tmp_path)
    prior = datetime(2026, 8, 7, 15, 0, tzinfo=ET)
    older = datetime(2026, 8, 6, 15, 0, tzinfo=ET)
    opportunity(repository, "prior", prior)
    opportunity(repository, "older", older)
    record(repository, "prior", "TRADE_ENTERED", prior)
    record(repository, "older", "TRADE_ENTERED", older)

    dates = authoritative_session_dates(repository, SESSION)

    assert dates == {"today": SESSION.date(), "previous": prior.date()}
    assert {row["opportunity_id"] for row in
            authoritative_session_event_summaries(repository, dates["previous"])} == {"prior"}


def test_projected_read_keeps_older_repository_signature_compatible():
    class OlderRepository:
        def list_trade_event_summaries(self, *, limit, event_type, start_at, end_at):
            return [(limit, event_type, start_at, end_at)]

    assert projected_trade_event_summaries(OlderRepository(), limit=7) == [
        (7, None, None, None)
    ]


def test_open_and_closed_authoritative_state_reconstruct_from_session_query(tmp_path):
    open_model = comparison(authoritative_session_event_summaries(
        flooded_repository(tmp_path / "open"), SESSION.date()
    ))
    closed_model = comparison(authoritative_session_event_summaries(
        flooded_repository(tmp_path / "closed", close=True), SESSION.date()
    ))

    assert open_model["rows"][0]["status"] == "OPEN"
    assert closed_model["rows"][0]["status"] == "CLOSED"
    assert closed_model["authoritative"]["closed"] == 1


def test_eastern_calendar_bounds_are_utc_and_end_exclusive():
    start, end = authoritative_session_bounds(SESSION.date())
    assert start == datetime(2026, 8, 10, 4, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 8, 11, 4, 0, tzinfo=timezone.utc)


def test_session_sql_predicates_precede_limit_and_projection_stays_narrow():
    repository_source = inspect.getsource(TradeRepository.list_trade_event_summaries)
    session_source = inspect.getsource(authoritative_session_event_summaries)
    app_source = inspect.getsource(__import__("app").render_outcome_trade_journal)

    assert repository_source.index('query += " WHERE "') < repository_source.index("LIMIT ?")
    assert "SELECT *" not in repository_source
    assert "count_trade_events" in session_source
    assert 'event_types = ("TRADE_ENTERED", "TRADE_CLOSED")' in session_source
    assert "start_at=start_at" in session_source and "end_at=end_inclusive" in session_source
    assert "limit=trade_desk_event_limit" in app_source
    assert "authoritative_session_event_summaries(trade_repository, session_date)" in app_source
