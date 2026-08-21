import inspect
from datetime import datetime, timedelta, timezone

import app
from qqq_command_card import (build_qqq_command_card_model, context_quality,
    build_qqq_trade_coverage, format_card_timestamp, format_contract_label, format_trade_timestamp, load_qqq_command_data,
    qqq_command_card_markup, render_qqq_command_card,
    QQQ_COMMAND_CARD_VIEWS, QQQ_COMMAND_CARD_VIEW_KEY)

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


def test_live_session_markup_preserves_polished_card_without_custom_navigation():
    model=build_qqq_command_card_model({},data(),now=NOW,market_open=False)
    model.update(contract="QQQ260819C00716000",updated_at="2026-08-19T19:55:08.138731+00:00")
    model["edge_snapshot"].update(profit_factor=3.7607742551224312,payoff_ratio=3.3429104489977166)
    markup=qqq_command_card_markup(model)
    for label in ("QQQ","FIRST TWO","LAST SESSION SETUP","SESSION COMPLETE"):
        assert label in markup
    assert "EDGE" not in markup and "RESEARCH" not in markup and "QQQ DNA" not in markup
    assert "Today's Best Trade" not in markup and "Win Probability" not in markup
    for css_class in ("ob-qnative-head","ob-qnative-live-grid","ob-qnative-support"):
        assert css_class in markup
    assert "QQQ $716 Call · Aug 19" in markup and "QQQ260819C00716000" not in markup
    assert "Updated 3:55 PM ET" in markup and "2026-08-19T19:55" not in markup
    assert "Trade #0" not in markup and "Trade # 0" not in markup and "No active trade" not in markup
    assert "ob-qnative-contract" in markup and "ob-qnative-setup-metrics" in markup
    assert "ob-qnative-pnl" in markup and "ob-qnative-session-row" in markup
    assert "min-height:" not in markup
    assert "@media(max-width:560px)" in markup and "grid-template-columns:minmax(0,1fr)" in markup
    assert "dataframe" not in inspect.getsource(qqq_command_card_markup).lower()


def test_human_contract_and_timestamp_helpers_are_presentation_only():
    assert format_contract_label("QQQ260819P00716000")=="QQQ $716 Put · Aug 19"
    assert format_contract_label(None,strike=715,expiration="2026-08-21",bias="CALL")=="QQQ $715 Call · Aug 21"
    assert format_contract_label(None)=="No active contract"
    assert format_card_timestamp("2026-08-19T19:55:08+00:00")=="Updated 3:55 PM ET"
    assert format_trade_timestamp("2026-08-19T19:55:08+00:00")=="3:55:08 PM ET"


def managed_trade(**updates):
    row={"trade_id":"managed-1","opportunity_id":"opp-1","variant":"INTRADAY_MANAGED","direction":"CALL",
        "option_symbol":"QQQ260820C00480000","expiration":"2026-08-20","dte":0,"strike":480,"quantity":1,
        "underlying_entry_price":479.75,"entry_bid":1.10,"entry_ask":1.20,"entry_fill":1.15,"spread_percent":8.7,
        "status":"OPEN","management_state":"OPEN","opened_at":"2026-08-20T14:31:02+00:00",
        "last_quote_at":"2026-08-20T14:32:03+00:00","updated_at":"2026-08-20T14:32:03+00:00"}
    row.update(updates);return row


def test_trade_coverage_never_promotes_selection_or_trigger_to_entered():
    signal={"opportunity_id":"opp-1","state":"TRIGGERED","direction":"CALL","underlying_price":479.75,
        "trigger_price":479.80,"updated_at":"2026-08-20T14:30:59+00:00"}
    triggered=build_qqq_trade_coverage([],signal,{},now=NOW)
    assert triggered["state"]=="ENTRY TRIGGERED" and triggered.get("entry_fill") is None
    selected=build_qqq_trade_coverage([],signal,{"opportunity_id":"opp-1","option_symbol":"QQQ260820C00480000","strike":480,
        "expiration":"2026-08-20","dte":0,"bid":1.10,"ask":1.20,"selected_at":"2026-08-20T14:30:59+00:00"},now=NOW)
    assert selected["state"]=="CONTRACT SELECTED" and selected["option_symbol"]=="QQQ260820C00480000"
    assert selected.get("entry_fill") is None


def test_trade_coverage_uses_managed_lane_and_preserves_exact_entry_fields():
    mirror=managed_trade(trade_id="mirror-1",variant="INTRADAY_MIRROR",entry_fill=9.99)
    coverage=build_qqq_trade_coverage([mirror,managed_trade()],{"trigger_price":479.80},{},now=NOW)
    assert coverage["state"]=="ENTERED" and coverage["trade_id"]=="managed-1"
    assert coverage["entry_fill"]==1.15 and coverage["midpoint"]==1.15 and coverage["quantity"]==1
    assert "10:31:02 AM ET" in coverage["copy_line"] and "OCC QQQ260820C00480000" in coverage["copy_line"]
    assert "INTRADAY_MANAGED" in coverage["copy_line"] and "9.99" not in coverage["copy_line"]


def test_trade_coverage_managing_closed_recent_session_and_stale_states():
    managing=build_qqq_trade_coverage([managed_trade(management_state="TRAILING",current_mark=1.35,
        unrealized_pnl=20,mfe_pct=18,mae_pct=-4)],{}, {},now=NOW,stale=True)
    assert managing["state"]=="MANAGING" and managing["stale"] is True
    assert managing["current_mark"]==1.35 and managing["unrealized_pnl"]==20
    closed=build_qqq_trade_coverage([managed_trade(status="CLOSED",management_state="CLOSED",
        closed_at="2026-08-20T14:46:12+00:00",exit_fill=1.40,realized_return_percent=21.7,
        realized_pnl=25,exit_reason="TRAILING_STOP",mfe_pct=30,mae_pct=-4)],{}, {},now=NOW,stale=True)
    assert closed["state"]=="CLOSED" and closed["stale"] is False and closed["duration"]=="15m 10s"
    assert closed["exit_fill"]==1.40 and closed["exit_reason"]=="TRAILING_STOP"


def test_live_trade_coverage_is_prominent_copy_friendly_and_presentation_only():
    source=[managed_trade(status="CLOSED",management_state="CLOSED",closed_at="2026-08-20T14:46:12+00:00",
        exit_fill=1.40,realized_return_percent=21.7,realized_pnl=25,exit_reason="TARGET")]
    original=[dict(source[0])]
    model=build_qqq_command_card_model({},dict(data(),trades=source),now=NOW,market_open=True)
    markup=qqq_command_card_markup(model)
    assert markup.index("QQQ TRADE COVERAGE") < markup.index("CURRENT QQQ SETUP")
    for value in ("CLOSED","10:31:02 AM ET","10:46:12 AM ET","QQQ260820C00480000","INTRADAY_MANAGED","TARGET"):
        assert value in markup
    assert "user-select:all" in markup and source==original


def test_production_aug_21_put_setup_never_splices_aug_19_call_contract():
    now=datetime(2026,8,21,14,20,tzinfo=timezone.utc)
    historical=managed_trade(option_symbol="QQQ260819C00716000",strike=716,expiration="2026-08-19",
        opened_at="2026-08-19T14:31:02+00:00",closed_at="2026-08-19T15:00:00+00:00",status="CLOSED")
    live={"price":710.24,"timestamp":"2026-08-21T14:20:00+00:00","bias":"Bearish","regime":"TRENDING DOWN",
        "trade_plan":{"direction":"Bearish","setup_type":"Bearish breakdown","trigger_price":709.41}}
    signal={"opportunity_id":"aug21-put","direction":"PUT","setup":"Bearish breakdown","trigger_price":709.41,
        "state":"ARMED","updated_at":"2026-08-21T14:20:00+00:00"}
    model=build_qqq_command_card_model(live,dict(data(),trades=[historical],signals=[signal]),now=now,market_open=True)
    assert model["contract"] is None and model["strike"] is None and model["dte"] is None
    markup=qqq_command_card_markup(model)
    assert "AWAITING CONTRACT SELECTION" in markup and "QQQ260819C00716000" not in markup
    assert "QQQ $716 Call" not in markup and "CURRENT QQQ SETUP" in markup


def test_current_contract_requires_current_session_direction_and_exact_identity():
    now=datetime(2026,8,21,15,tzinfo=timezone.utc)
    signal={"opportunity_id":"current-put","direction":"PUT","state":"TRIGGERED","updated_at":"2026-08-21T15:00:00+00:00"}
    previous=managed_trade(opportunity_id="current-put",direction="PUT",option_type="PUT",option_symbol="QQQ260820P00480000",
        expiration="2026-08-20",opened_at="2026-08-20T15:00:00+00:00")
    assert build_qqq_command_card_model({},dict(data(),trades=[previous],signals=[signal]),now=now,market_open=True)["contract"] is None
    expired=managed_trade(opportunity_id="current-put",direction="PUT",option_type="PUT",option_symbol="QQQ260820P00480000",
        expiration="2026-08-20",opened_at="2026-08-21T14:30:00+00:00")
    expired_model=build_qqq_command_card_model({},dict(data(),trades=[expired],signals=[signal]),now=now,market_open=True)
    assert expired_model["contract_status"]=="CONTRACT DATA MISMATCH" and expired_model["trade_coverage"]["copy_line"] is None
    wrong_identity=managed_trade(opportunity_id="other",direction="PUT",option_type="PUT",option_symbol="QQQ260821P00710000",
        expiration="2026-08-21",opened_at="2026-08-21T14:30:00+00:00")
    mismatch=build_qqq_command_card_model({},dict(data(),trades=[wrong_identity],signals=[signal]),now=now,market_open=True)
    assert mismatch["contract_status"]=="CONTRACT DATA MISMATCH"
    assert mismatch["trade_coverage"]["state"]=="CONTRACT DATA MISMATCH" and mismatch["trade_coverage"]["copy_line"] is None


def test_valid_current_call_put_zero_and_future_dte_are_derived_from_expiration():
    now=datetime(2026,8,21,15,tzinfo=timezone.utc)
    for direction,kind,symbol,expiration,expected_dte in (
        ("CALL","CALL","QQQ260821C00710000","2026-08-21",0),
        ("PUT","PUT","QQQ260822P00710000","2026-08-22",1),
    ):
        signal={"opportunity_id":f"opp-{kind}","direction":direction,"state":"PAPER_OPENED","updated_at":"2026-08-21T15:00:00+00:00"}
        trade=managed_trade(opportunity_id=f"opp-{kind}",direction=direction,option_type=kind,option_symbol=symbol,
            expiration=expiration,dte=99,opened_at="2026-08-21T14:30:00+00:00")
        model=build_qqq_command_card_model({},dict(data(),trades=[trade],signals=[signal]),now=now,market_open=True)
        assert model["contract"]==symbol and model["dte"]==expected_dte
        assert model["trade_coverage"]["display_dte"]==expected_dte and model["trade_coverage"]["copy_line"]


def test_current_selected_contract_requires_timestamp_expiration_direction_and_identity():
    now=datetime(2026,8,21,15,tzinfo=timezone.utc)
    signal={"opportunity_id":"selected-put","direction":"PUT","state":"TRIGGERED","updated_at":"2026-08-21T15:00:00+00:00"}
    base={"opportunity_id":"selected-put","direction":"PUT","option_type":"PUT","option_symbol":"QQQ260821P00710000",
        "expiration":"2026-08-21","strike":710,"selected_at":"2026-08-21T14:59:50+00:00"}
    selected=build_qqq_trade_coverage([],signal,base,now=now)
    assert selected["state"]=="CONTRACT SELECTED" and selected.get("entry_fill") is None
    for changes in ({"selected_at":"2026-08-20T14:59:50+00:00"},{"expiration":"2026-08-20"},
        {"option_type":"CALL","option_symbol":"QQQ260821C00710000"},{"opportunity_id":"other"}):
        invalid=build_qqq_trade_coverage([],signal,{**base,**changes},now=now)
        assert invalid["state"]!="CONTRACT SELECTED" and invalid.get("copy_line") is None


def test_market_open_and_first_two_active_use_adaptive_priority():
    model=build_qqq_command_card_model({},data(12),now=NOW,market_open=True)
    markup=qqq_command_card_markup(model)
    assert 'data-view="LIVE / SESSION"' in markup
    assert "CURRENT QQQ SETUP" in markup and "SESSION ACTIVE" in markup
    assert "INSUFFICIENT DATA" in markup and "2/50 accepted" in markup


def test_market_closed_defaults_to_combined_pane_and_first_two_awaiting_is_compact():
    model=build_qqq_command_card_model({},data(),now=NOW,market_open=False)
    markup=qqq_command_card_markup(model)
    assert 'data-view="LIVE / SESSION"' in markup
    assert "LAST SESSION SETUP" in markup and "SESSION COMPLETE" in markup and "AWAITING SAMPLE" in markup
    assert "No active trade" not in markup
    assert "CONTEXT COVERAGE" in markup and "Known factors:" in markup and "LIMITED" in markup


def test_edge_and_research_render_exclusively_with_all_existing_content():
    model=build_qqq_command_card_model({},data(),now=NOW,market_open=False)
    model["edge_snapshot"].update(profit_factor=3.7607742551224312,payoff_ratio=3.3429104489977166)
    edge=qqq_command_card_markup(model,view="EDGE")
    for label in ("Closed Trades","Expectancy","Profit Factor","Win Rate","Avg Winner","Avg Loser","Payoff","Profitable Sessions"):
        assert label in edge
    assert "LAST SESSION SETUP" not in edge and "QQQ DNA" not in edge
    assert "3.76" in edge and "3.34x" in edge
    research=qqq_command_card_markup(model,view="RESEARCH")
    for label in ("CONTEXT COVERAGE","FIRST_TWO GOVERNANCE","MARK TELEMETRY","QQQ DNA","Sequence and overtrading"):
        assert label in research
    assert "0 marked" not in research and "awaiting observations" in research.lower()
    assert "Closed Trades" not in research and "LAST SESSION SETUP" not in research


class NativeStreamlit:
    def __init__(self, selection=None): self.selection=selection;self.calls=[];self.markups=[]
    def segmented_control(self,label,options,**kwargs):
        self.calls.append((label,tuple(options),kwargs));return self.selection
    def markdown(self,value,**kwargs): self.markups.append(value)


def test_native_control_default_and_every_direct_transition_are_state_driven():
    model=build_qqq_command_card_model({},data(),now=NOW,market_open=False)
    for source,target in (
        ("LIVE / SESSION","EDGE"),("LIVE / SESSION","RESEARCH"),
        ("EDGE","LIVE / SESSION"),("EDGE","RESEARCH"),
        ("RESEARCH","LIVE / SESSION"),("RESEARCH","EDGE"),
    ):
        native=NativeStreamlit(target)
        assert render_qqq_command_card(native,model)==target
        _,options,kwargs=native.calls[0]
        assert options==QQQ_COMMAND_CARD_VIEWS and kwargs["key"]==QQQ_COMMAND_CARD_VIEW_KEY
        assert kwargs["default"]=="LIVE / SESSION"
        assert f'data-view="{target}"' in native.markups[-1]
    default=NativeStreamlit(None)
    assert render_qqq_command_card(default,model)=="LIVE / SESSION"


def test_streamlit_harness_switches_native_state_and_renders_one_pane():
    from streamlit.testing.v1 import AppTest
    script='''
from datetime import datetime, timezone
import streamlit as st
from qqq_command_card import build_qqq_command_card_model, render_qqq_command_card
model=build_qqq_command_card_model({}, {"trades":[],"signals":[],"shadow":[],"marks":[],"experiment":None}, now=datetime(2026,8,20,15,tzinfo=timezone.utc), market_open=False)
render_qqq_command_card(st,model)
'''
    app_test=AppTest.from_string(script).run()
    rendered=lambda:" ".join(element.value for element in app_test.markdown)
    assert "LAST SESSION SETUP" in rendered() and "Closed Trades" not in rendered()
    app_test.session_state[QQQ_COMMAND_CARD_VIEW_KEY]="EDGE";app_test.run()
    assert "Closed Trades" in rendered() and "LAST SESSION SETUP" not in rendered()
    app_test.session_state[QQQ_COMMAND_CARD_VIEW_KEY]="RESEARCH";app_test.run()
    assert "QQQ DNA" in rendered() and "Closed Trades" not in rendered()
    app_test.session_state[QQQ_COMMAND_CARD_VIEW_KEY]="LIVE / SESSION";app_test.run()
    assert "LAST SESSION SETUP" in rendered() and "QQQ DNA" not in rendered()


def test_native_navigation_has_no_custom_javascript_radio_or_data_access():
    source=inspect.getsource(render_qqq_command_card)+inspect.getsource(qqq_command_card_markup)
    for forbidden in ("onclick",'type="radio"',":checked","load_qqq_command_data","repository","provider","select "):
        assert forbidden not in source.lower()
    assert "segmented_control" in source and "session_state" not in source


def test_expiration_is_formatted_and_closed_setup_preserves_source_value():
    model=build_qqq_command_card_model({},data(),now=NOW,market_open=False)
    model.update(contract="QQQ260819P00716000",strike=716,expiration="2026-08-19",bias="PUT")
    original=dict(model)
    markup=qqq_command_card_markup(model)
    assert "QQQ $716 Put" in markup and "Aug 19" in markup and ">Aug 19</strong>" in markup
    assert "2026-08-19" not in markup and model==original


def test_trade_desk_integration_is_read_only_bounded_provider_free_and_schema_free():
    source=inspect.getsource(load_qqq_command_data).lower()
    assert "select " in source and "limit ?" in source and "select *" not in source
    for forbidden in ("insert ","update ","delete ","create table","alter table","option_quote","option_chain","provider"):
        assert forbidden not in source
    desk=inspect.getsource(app.render_outcome_trade_journal)
    assert 'best_trade=""' in desk and "load_qqq_command_data" in desk
    assert "render_qqq_command_card_fragment(qqq_model)" in desk
    fragment=inspect.getsource(app.render_qqq_command_card_fragment)
    assert "load_qqq_command_data" not in fragment and "render_qqq_command_card" in fragment
