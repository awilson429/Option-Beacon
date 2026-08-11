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


def test_close_after_session_midnight_remains_with_originating_entry(tmp_path):
    repository = TradeRepository(tmp_path / "state.db", database_url="")
    entry_at = datetime(2026, 8, 10, 15, 55, tzinfo=ET)
    close_at = datetime(2026, 8, 11, 9, 35, tzinfo=ET)
    opportunity(repository, "overnight-close", entry_at)
    record(repository, "overnight-close", "TRADE_ENTERED", entry_at,
           underlying_price=600, entry_price=600)
    record(repository, "overnight-close", "TRADE_CLOSED", close_at,
           exit_price=603, realized_return=.5)
    events = authoritative_session_event_summaries(repository, entry_at.date())
    assert {row["event_type"] for row in events} == {"TRADE_ENTERED", "TRADE_CLOSED"}
    assert trade_comparison_model(events, [], [], [], session_date=entry_at.date())["rows"][0]["status"] == "CLOSED"


def test_today_is_stable_until_eastern_midnight_then_rolls_to_previous(tmp_path):
    repository = TradeRepository(tmp_path / "state.db", database_url="")
    opportunity(repository, "today", SESSION)
    record(repository, "today", "TRADE_ENTERED", SESSION)
    expected = {"today": SESSION.date(), "previous": None}
    for clock in (
        SESSION.replace(hour=15, minute=55), SESSION.replace(hour=16, minute=30),
        SESSION.replace(hour=19, minute=30),
        SESSION.replace(hour=23, minute=59, second=59),
    ):
        assert authoritative_session_dates(repository, clock) == expected
        assert len(authoritative_session_event_summaries(repository, clock.date())) == 1
    after_midnight = SESSION.replace(day=11, hour=0, minute=0)
    assert authoritative_session_dates(repository, after_midnight) == {
        "today": after_midnight.date(), "previous": SESSION.date(),
    }
    assert authoritative_session_event_summaries(repository, after_midnight.date()) == []


def test_previous_session_skips_weekend_without_authoritative_entries(tmp_path):
    repository = TradeRepository(tmp_path / "state.db", database_url="")
    friday = datetime(2026, 8, 7, 15, 0, tzinfo=ET)
    monday_evening = datetime(2026, 8, 10, 19, 30, tzinfo=ET)
    opportunity(repository, "friday", friday)
    record(repository, "friday", "TRADE_ENTERED", friday)
    assert authoritative_session_dates(repository, monday_evening) == {
        "today": monday_evening.date(), "previous": friday.date(),
    }


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
    assert 'event_type="TRADE_ENTERED"' in session_source
    assert "trade_event_summaries_for_opportunity_ids" in session_source
    assert "start_at=start_at" in session_source and "end_at=end_inclusive" in session_source
    assert "limit=trade_desk_event_limit" in app_source
    assert "authoritative_session_event_summaries(trade_repository, session_date)" in app_source
    assert "positions_for_trade_ids(session_trade_ids)" in app_source
    assert "mirror_repository.analytics_rows" in app_source
    assert "mirror_repository.rows()" not in app_source


def test_session_reconciliation_is_independent_of_ui_history_market_and_worker_state():
    app_source = inspect.getsource(__import__("app").render_outcome_trade_journal)
    session_start = app_source.index("sessions = (")
    comparison_end = app_source.index("comparison = trade_comparison_model", session_start)
    session_path = app_source[session_start:comparison_end]
    assert "trade_desk_event_limit" not in session_path
    assert "market_open" not in session_path
    assert "worker_config_state" not in session_path
