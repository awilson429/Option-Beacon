import inspect
from datetime import datetime, timedelta, timezone

import app
from qqq_command_card import (build_qqq_command_card_model, context_quality,
    format_card_timestamp, format_contract_label, load_qqq_command_data,
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
    model.update(contract=None,strike=716,expiration="2026-08-19",bias="PUT")
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
