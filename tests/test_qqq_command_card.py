import inspect
from datetime import datetime, timedelta, timezone

import app
from qqq_command_card import (build_qqq_command_card_model, context_quality,
    load_qqq_command_data, qqq_command_card_markup)

NOW=datetime(2026,8,20,15,tzinfo=timezone.utc)


def data(count=0):
    shadow=[]; trades=[]
    for index in range(count):
        day="2026-08-19"; accepted=index<2
        shadow.append({"source_trade_id":f"t{index}","eastern_session":day,"session_trade_number":index+1,
            "shadow_status":"SHADOW_ACCEPTED" if accepted else "SHADOW_REJECTED","opened_at":f"{day}T14:00:00+00:00",
            "closed_at":f"{day}T15:00:00+00:00","realized_pnl":10 if accepted else -5,"realized_return_percent":5,"variant":"INTRADAY_MANAGED"})
        trades.append({"trade_id":f"t{index}","direction":"CALL","variant":"INTRADAY_MANAGED","dte":0,"opened_at":shadow[-1]["opened_at"],
            "closed_at":shadow[-1]["closed_at"],"realized_pnl":shadow[-1]["realized_pnl"],"realized_return_percent":5,"mfe_pct":10,"mae_pct":-2})
    return {"trades":trades,"signals":[],"shadow":shadow,"marks":[],"experiment":{"experiment_start_timestamp":"2026-08-19T00:00:00+00:00"} if count else None}


def test_context_quality_aligned_mixed_missing_and_stale_are_non_probabilistic():
    keys=("vwap_aligned","ema_aligned","trend_aligned","orb_aligned","cross_confirmed","spread_tight","regime_available")
    assert context_quality({key:True for key in keys})=={"label":"STRONG","score":100}
    assert context_quality({key:index%2==0 for index,key in enumerate(keys)})["label"]=="MODERATE"
    assert context_quality({"vwap_aligned":True})["score"] is None
    assert context_quality({key:True for key in keys},stale=True)["label"]=="INSUFFICIENT CONTEXT"


def test_status_market_closed_stale_active_and_empty_states():
    live={"price":480,"trade_plan":{"direction":"Bullish","setup":"VWAP RECLAIM"},"ema_aligned":True,"price_vs_vwap":"ABOVE","opening_range_state":"BREAKOUT","cross_market":{"SPY":"UP"},"regime":"TREND"}
    assert build_qqq_command_card_model(live,data(),now=NOW,market_open=False)["status"]=="MARKET CLOSED"
    assert build_qqq_command_card_model(live,data(),now=NOW,market_open=True,stale=True)["status"]=="DATA STALE"
    assert build_qqq_command_card_model(live,data(),now=NOW,market_open=True,active_setup=True)["status"]=="ACTIVE SETUP"
    assert build_qqq_command_card_model({},data(),now=NOW,market_open=True)["status"]=="DATA UNAVAILABLE"


def test_first_two_governance_edge_pulse_and_current_session_exclusion():
    model=build_qqq_command_card_model({},data(12),now=NOW,market_open=True)
    assert model["first_two"]["governance"]=="INSUFFICIENT DATA"  # only first two accepted
    assert model["edge_snapshot"]["closed_trades"]==12
    assert model["session_pulse"]["closed_trades"]==0
    assert model["mark_coverage"]["earliest_mark"] is None


def test_markup_replaces_best_trade_with_compact_sections_and_no_dataframe():
    model=build_qqq_command_card_model({},data(),now=NOW,market_open=False)
    markup=qqq_command_card_markup(model)
    for label in ("QQQ COMMAND CARD","CONTEXT QUALITY","SESSION PULSE","FIRST_TWO FORWARD TEST","QQQ EDGE SNAPSHOT","MARK COVERAGE","QQQ DNA"):
        assert label in markup
    assert "Today's Best Trade" not in markup and "Win Probability" not in markup
    assert "dataframe" not in inspect.getsource(qqq_command_card_markup).lower()


def test_trade_desk_integration_is_read_only_bounded_provider_free_and_schema_free():
    source=inspect.getsource(load_qqq_command_data).lower()
    assert "select " in source and "limit ?" in source and "select *" not in source
    for forbidden in ("insert ","update ","delete ","create table","alter table","option_quote","option_chain","provider"):
        assert forbidden not in source
    desk=inspect.getsource(app.render_outcome_trade_journal)
    assert "best_trade=qqq_card" in desk and "load_qqq_command_data" in desk
