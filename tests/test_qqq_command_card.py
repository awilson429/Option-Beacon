import inspect
from datetime import datetime, timedelta, timezone

import app
from qqq_command_card import (build_qqq_command_card_model, context_quality,
    format_card_timestamp, format_contract_label, load_qqq_command_data,
    qqq_command_card_markup)

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


def test_markup_reflows_as_compact_horizontal_bands_without_dataframe():
    model=build_qqq_command_card_model({},data(),now=NOW,market_open=False)
    model.update(contract="QQQ260819C00716000",updated_at="2026-08-19T19:55:08.138731+00:00")
    model["edge_snapshot"].update(profit_factor=3.7607742551224312,payoff_ratio=3.3429104489977166)
    markup=qqq_command_card_markup(model)
    for label in ("QQQ","SESSION COMPLETE","FIRST_TWO","QQQ EDGE","TRADE / DATA QUALITY","QQQ DNA"):
        assert label in markup
    assert "Today's Best Trade" not in markup and "Win Probability" not in markup
    for css_class in ("ob-qband-hero","ob-qband-setup","ob-qband-session","ob-qband-intel","ob-qband-dna"):
        assert css_class in markup
    assert "QQQ $716 Call · Aug 19" in markup and "QQQ260819C00716000" not in markup
    assert "Updated 3:55 PM ET" in markup and "2026-08-19T19:55" not in markup
    assert "3.76" in markup and "3.34x" in markup
    assert "Trade #0" not in markup and "Trade # 0" not in markup and "No active trade" in markup
    assert "0 marked" not in markup and "awaiting observations" in markup
    assert "@media(max-width:700px)" in markup
    assert "dataframe" not in inspect.getsource(qqq_command_card_markup).lower()


def test_human_contract_and_timestamp_helpers_are_presentation_only():
    assert format_contract_label("QQQ260819P00716000")=="QQQ $716 Put · Aug 19"
    assert format_contract_label(None,strike=715,expiration="2026-08-21",bias="CALL")=="QQQ $715 Call · Aug 21"
    assert format_contract_label(None)=="No active contract"
    assert format_card_timestamp("2026-08-19T19:55:08+00:00")=="Updated 3:55 PM ET"


def test_market_open_and_first_two_active_use_adaptive_priority():
    model=build_qqq_command_card_model({},data(12),now=NOW,market_open=True)
    markup=qqq_command_card_markup(model)
    assert 'class="ob-qband is-live"' in markup and "SESSION ACTIVE" in markup
    assert "INSUFFICIENT DATA" in markup and "2/50 accepted" in markup


def test_trade_desk_integration_is_read_only_bounded_provider_free_and_schema_free():
    source=inspect.getsource(load_qqq_command_data).lower()
    assert "select " in source and "limit ?" in source and "select *" not in source
    for forbidden in ("insert ","update ","delete ","create table","alter table","option_quote","option_chain","provider"):
        assert forbidden not in source
    desk=inspect.getsource(app.render_outcome_trade_journal)
    assert "best_trade=qqq_card" in desk and "load_qqq_command_data" in desk
