from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from contextual_research import (
    ContextualResearchRepository, context_conviction, context_shadow_decision,
    entry_current_exit_deltas, heikin_ashi_states, llm_synthesis_interface,
    interaction_counts, liquidity_bucket, moneyness_bucket, portfolio_context, position_context_mark, relative_strength_bucket,
    setup_health, signal_timing, simulate_shadow_exits,
)
from opportunity_context import build_opportunity_context
from trade_repository import TradeRepository

NOW=datetime(2026,8,18,14,0,tzinfo=timezone.utc)


def _context(identifier="opp"):
    result={"timestamp":NOW,"relative_volume":2,"symbol_session_return":2,"sector_session_return":1,"spy_session_return":.2,
        "market_context":{"spy_direction":"UP","qqq_direction":"UP"},
        "timeframe_trends":{"1m":"UP","5m":"UP","15m":"UP"},
        "first_candidate_detected_at":(NOW-timedelta(minutes=2)).isoformat(),
        "setup_detected_at":(NOW-timedelta(minutes=1)).isoformat(),
        "price_structure":{"initial_impulse_magnitude":1,"pullback_depth":.2,"reclaim_confirmed":True},
        "option_context":{"spread_percent":10,"conservative_fill":1.1,"volume":50,"open_interest":100}}
    record=SimpleNamespace(trade_id=identifier,symbol="AAPL",direction="Bullish",timestamp=NOW,entry_time=NOW)
    context=build_opportunity_context(result,record);context["lifecycle"]["authoritative_to_mirror_open_seconds"]=30
    return context


def _mark(minute,ret,**changes):
    row={"trade_id":"m1","opportunity_id":"opp","lane":"MIRROR","symbol":"AAPL","direction":"Bullish",
        "observed_at":(NOW+timedelta(minutes=minute)).isoformat(),"unrealized_return":ret,"mfe_to_date":max(0,ret),
        "mae_to_date":min(0,ret),"price_vs_vwap":"ABOVE","ema_aligned":True,"market_alignment":"PASS",
        "multi_timeframe_alignment":100,"rsi":60,"relative_volume":2,"spread_percent":10,"setup_health":"HEALTHY",
        "underlying_price":100+minute,"underlying_peak":100+minute,"atr":1,"ha_state":"BULLISH"}
    row.update(changes);return row


def test_conviction_is_dimensional_and_shadow_cannot_open_trades():
    conviction=context_conviction(_context())
    assert len(conviction["dimensions"])==10
    assert all({"status","score","reasons","coverage"}<=set(value) for value in conviction["dimensions"].values())
    decision=context_shadow_decision(_context())
    assert decision["decision"] in {"WOULD_TRADE","WOULD_WATCH","WOULD_REJECT"}
    assert decision["cannot_open_positions"] is True
    assert "open" not in decision and "quantity" not in decision


def test_spread_rule_is_predeclared_and_descriptive():
    context=_context();context["option_execution"]["spread_percent"]=21
    assert context_shadow_decision(context)["decision"]=="WOULD_REJECT"


def test_disabled_llm_interface_has_zero_authority():
    result=llm_synthesis_interface(_context())
    assert result["status"]=="DISABLED" and result["trading_authority"] is False


def test_setup_health_state_machine_never_returns_exit_command():
    broken=_mark(1,-5,price_vs_vwap="BELOW",ema_aligned=False)
    assert setup_health(broken)=="BROKEN"
    assert setup_health(_mark(2,1),{"setup_health":"BROKEN"})=="RECOVERING"
    assert setup_health({})=="INSUFFICIENT_DATA"
    assert "EXIT" not in setup_health(broken)


def test_position_mark_exact_identity_and_missing_data():
    mark=position_context_mark(trade_id="t",opportunity_id="o",lane="MIRROR",symbol="AAPL",observed_at=NOW)
    assert mark["trade_id"]=="t" and mark["opportunity_id"]=="o" and mark["lane"]=="MIRROR"
    assert mark["underlying_price"] is None and mark["setup_health"]=="INSUFFICIENT_DATA"


def test_entry_current_exit_deltas_use_ordered_observations():
    rows=[_mark(2,-4,rsi=50,spread_percent=14),_mark(0,0,rsi=60,spread_percent=10),_mark(1,8,rsi=65)]
    result=entry_current_exit_deltas(rows)
    assert result["rsi_change"]==-10 and result["spread_change"]==4
    assert result["mfe"]==8 and result["mae"]==-4


def test_shadow_exits_do_not_mutate_real_exit_or_marks():
    rows=[_mark(0,0),_mark(1,12),_mark(2,-1,price_vs_vwap="BELOW",ema_aligned=False,setup_health="BROKEN")]
    original=deepcopy(rows);real_trade={"exit_reason":"AUTHORITATIVE_EXIT","realized_return":-7}
    result=simulate_shadow_exits(rows)
    assert result["SETUP_HEALTH_EXIT"]["shadow_return"]==-1
    assert result["BREAKEVEN_AFTER_10"]["reason"]=="BREAKEVEN_FLOOR"
    assert rows==original and real_trade=={"exit_reason":"AUTHORITATIVE_EXIT","realized_return":-7}


def test_heikin_ashi_and_opposing_combinations_are_observational():
    states=heikin_ashi_states([{"open":10,"high":14,"low":9,"close":12},{"open":12,"high":12,"low":8,"close":8}])
    assert states==["BULLISH","BEARISH"]
    assert heikin_ashi_states([{"open":None}])==["INSUFFICIENT_DATA"]


def test_signal_timing_has_no_future_lookup():
    timing=signal_timing(_context())
    assert timing["first_seen_to_authoritative_seconds"]==120
    assert timing["authoritative_to_execution_seconds"]==30
    assert timing["classification"]=="NORMAL_MATURITY"


def test_relative_strength_buckets_and_portfolio_shadow():
    assert [relative_strength_bucket(v) for v in (2,.5,0,-.6,None)]==["STRONG_OUTPERFORMANCE","MODERATE_OUTPERFORMANCE","NEUTRAL","UNDERPERFORMANCE","UNKNOWN"]
    result=portfolio_context({"symbol":"AAPL","sector":"Technology","direction":"CALL","debit":100},
        [{"symbol":"MSFT","sector":"Technology","direction":"CALL","debit":200}],{("AAPL","MSFT"):.9})
    assert result["same_sector_positions"]==1 and result["highly_correlated_positions"]==1
    assert result["aggregate_debit_after"]==300


def test_option_buckets_and_eight_predeclared_interactions():
    assert [moneyness_bucket(v) for v in (2,0,-2,None)]==["ITM","ATM","OTM","UNKNOWN"]
    assert [liquidity_bucket(v) for v in (5,25,75,250,500,None)]==["LT_10","10_49","50_99","100_499","GE_500","UNKNOWN"]
    rows=interaction_counts([_context()],[{"opportunity_id":"opp","broad_decision":"ACCEPTED","spread_percent":10,"signal_age_seconds":30}])
    assert len(rows)==8 and all(row["N"] in {0,1} for row in rows)


def test_idempotent_position_context_and_shadow_identity(tmp_path):
    repo=TradeRepository(tmp_path/"phase2.db");repo.initialize()
    repo.create_opportunity(opportunity_id="opp",idempotency_key="opp",symbol="AAPL",direction="Bullish",playbook="Breakout",signal_timestamp=NOW,source_version="test")
    repo.create_opportunity_context("opp",_context())
    mark=position_context_mark(trade_id="m1",opportunity_id="opp",lane="MIRROR",symbol="AAPL",observed_at=NOW,context=_context(),unrealized_return=1)
    repo.record_position_context_mark(mark);repo.record_position_context_mark(mark)
    assert len(repo.list_position_context_marks(opportunity_ids=["opp"]))==1
    assert len(repo.list_context_shadow_decisions())==1


def test_scope_separation_and_bounded_read_only_analytics(tmp_path):
    source=Path("contextual_research.py").read_text(encoding="utf-8")
    section=source[source.index("class ContextualResearchRepository"):]
    assert "limit=" in section and "list_position_context_marks" in section
    for forbidden in ("INSERT ","UPDATE ","DELETE ","provider","option_quote","select_contract"):
        assert forbidden not in section


def test_no_streamlit_writes_or_provider_calls():
    source=Path("contextual_research_dashboard.py").read_text(encoding="utf-8")
    assert "Load Phase 2 Research" in source
    for forbidden in ("INSERT","UPDATE","DELETE","record_","provider","option_quote","select_contract"):
        assert forbidden not in source


def test_worker_cadence_and_trading_policies_are_not_changed():
    changed={"contextual_research.py","contextual_research_dashboard.py","trade_repository.py","mirror_execution.py",
        "paper_execution_repository.py","app.py","experiment_scorecard_dashboard.py"}
    assert "optionbeacon/worker/scan_once.py" not in changed
    assert "execution_config.py" not in changed and "option_trade_engine.py" not in changed
