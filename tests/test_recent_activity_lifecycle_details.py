import inspect
from datetime import datetime, timedelta, timezone

import app

from trade_desk_compact import (
    ACTIVITY_FILTERS,
    activity_rows_markup,
    enrich_authoritative_activity_events,
    filtered_activity_rows,
)


NOW = datetime(2026, 8, 6, 18, 10, tzinfo=timezone.utc)


def opportunity(identity, direction, trigger, confidence, *, created=None, state="CANDIDATE"):
    return {
        "id": identity, "symbol": identity.upper(), "direction": direction,
        "entry_reference": trigger, "confidence": confidence, "state": state,
        "signal_timestamp": created or NOW - timedelta(minutes=14),
    }


def event(identity, kind="ENTRY_READY", **values):
    return {
        "id": f"event-{identity}", "opportunity_id": identity,
        "trade_id": identity if kind == "TRADE_ENTERED" else None,
        "event_type": kind, "event_timestamp": NOW,
        "symbol": identity.upper(), "description": f"{identity} lifecycle event",
        **values,
    }


def funnel(identity, current, **values):
    return {
        "opportunity_id": identity, "current_price": current,
        "state": "Armed", "primary_blocker": "TRIGGER_NOT_REACHED",
        "authoritative_disposition": "TRIGGER_NOT_REACHED",
        "visible_setup_qualified": 0, **values,
    }


def rows(events, opportunities, funnels):
    enriched = enrich_authoritative_activity_events(
        events, opportunities, funnels, now=NOW
    )
    return filtered_activity_rows(enriched, now=NOW, view_all=True)


def test_ready_call_and_put_show_persisted_trigger_and_direction_aware_distance():
    values = rows(
        [event("call"), event("put")],
        [opportunity("call", "Bullish", 101, 72), opportunity("put", "Bearish", 99, 71)],
        [funnel("call", 100), funnel("put", 100)],
    )
    by_symbol = {row["Symbol"]: row for row in values}
    assert by_symbol["CALL"]["Direction"] == "CALL"
    assert by_symbol["PUT"]["Direction"] == "PUT"
    assert "Current $100.00 · Trigger $101.00 · $1.00 away (0.99%)" in by_symbol["CALL"]["Lifecycle Detail"]
    assert "Current $100.00 · Trigger $99.00 · $1.00 away (1.01%)" in by_symbol["PUT"]["Lifecycle Detail"]
    assert "Confidence 72" in by_symbol["CALL"]["Lifecycle Meta"]
    assert "Age 14m" in by_symbol["CALL"]["Lifecycle Meta"]


def test_crossed_trigger_says_reached_not_away():
    row = rows(
        [event("call")], [opportunity("call", "Bullish", 101, 72)],
        [funnel("call", 102, state="Triggered", primary_blocker="AWAITING_AUTHORITATIVE_LIFECYCLE")],
    )[0]
    assert "TRIGGER REACHED" in row["Lifecycle Detail"]
    assert "beyond trigger" in row["Lifecycle Detail"]
    assert "away" not in row["Lifecycle Detail"]


def test_immutable_opportunity_trigger_wins_over_event_or_scanner_reference():
    row = rows(
        [event("spy", entry_price=999)],
        [opportunity("spy", "Bullish", 101, 72)],
        [funnel("spy", 100, trigger_price=555)],
    )[0]
    assert "Trigger $101.00" in row["Lifecycle Detail"]
    assert "$999" not in row["Lifecycle Detail"] and "$555" not in row["Lifecycle Detail"]


def test_confidence_64_and_65_are_authoritative_not_visible_setup_semantics():
    values = rows(
        [event("low"), event("gate")],
        [opportunity("low", "Bullish", 100, 64), opportunity("gate", "Bullish", 100, 65)],
        [
            funnel("low", 100, primary_blocker="ENTRY_CONFIDENCE_BELOW_MINIMUM", visible_setup_qualified=1),
            funnel("gate", 99, visible_setup_qualified=0),
        ],
    )
    by_symbol = {row["Symbol"]: row for row in values}
    assert "Confidence below 65" in by_symbol["LOW"]["Lifecycle Meta"]
    assert "Authoritative confidence qualified NO" in by_symbol["LOW"]["Lifecycle Diagnostics"]
    assert "Visible setup qualified YES" in by_symbol["LOW"]["Lifecycle Diagnostics"]
    assert "Authoritative confidence qualified YES" in by_symbol["GATE"]["Lifecycle Diagnostics"]
    assert "Visible setup qualified NO" in by_symbol["GATE"]["Lifecycle Diagnostics"]


def test_missing_fields_are_honest_and_exact_id_join_prevents_symbol_guessing():
    values = rows(
        [event("known"), event("unknown", symbol="KNOWN", event_timestamp=NOW + timedelta(seconds=1))],
        [opportunity("known", "Bullish", None, None)],
        [funnel("different-id", 123)],
    )
    known = next(row for row in values if row.get("Lifecycle Diagnostics"))
    assert known["Lifecycle Detail"] == "—"
    unknown = next(row for row in values if not row.get("Lifecycle Diagnostics"))
    assert not unknown.get("Lifecycle Detail")


def test_entry_and_exit_rows_keep_authoritative_underlying_context():
    entered, closed = rows(
        [
            event("arkg", "TRADE_ENTERED", direction="Bearish", underlying_price=40.47),
            event("done", "TRADE_CLOSED", entry_price=100, exit_price=98,
                  realized_return=2, exit_reason="TARGET_1", metadata={"hold_minutes": 18}),
        ],
        [
            opportunity("arkg", "Bearish", 40.52, 71, state="OPEN"),
            opportunity("done", "Bearish", 100, 75, state="CLOSED"),
        ], [],
    )
    by_symbol = {row["Symbol"]: row for row in (entered, closed)}
    assert by_symbol["ARKG"]["Event"] == "ENTER"
    assert by_symbol["ARKG"]["Lifecycle State"] == "ENTERED"
    assert "Entry $40.47 · Trigger $40.52" in by_symbol["ARKG"]["Lifecycle Detail"]
    assert by_symbol["DONE"]["Event"] == "EXIT"
    assert "Entry $100.00 · Exit $98.00 · Return +2.00% · Hold 18m" == by_symbol["DONE"]["Lifecycle Detail"]
    assert "TARGET 1" in by_symbol["DONE"]["Lifecycle Meta"]


def test_markup_is_compact_mobile_structured_and_filters_remain_unchanged():
    row = rows(
        [event("amzn")], [opportunity("amzn", "Bearish", 270.92, 72)],
        [funnel("amzn", 271.85)],
    )[0]
    markup = activity_rows_markup([row])
    assert "ob-activity-lifecycle" in markup
    assert "READY" in markup and "AMZN" in markup and "PUT" in markup
    assert "Current $271.85" in markup and "Trigger $270.92" in markup
    assert "<details" in markup
    assert ACTIVITY_FILTERS == ("ALL", "ENTRIES", "EXITS", "SIGNALS")


def test_streamlit_remains_read_only_and_introduces_no_provider_calls():
    source = inspect.getsource(app.render_outcome_trade_journal)
    assert "enrich_authoritative_activity_events" in source
    for forbidden in (
        "generate_signal", "download_data", "option_quote", "run_mirror_execution",
        "process_scanner_result", "record_trade_event", "update_opportunity",
    ):
        assert forbidden not in source
