from datetime import datetime, timedelta
import inspect

import pytest

from scalp.analytics import compare, performance
from scalp.contracts import ExecutionConfig, filter_contracts, simulate_execution
from scalp.engine import ScalpEngine
from scalp.exits import evaluate_exit
from scalp.models import ScalpState, StrategyMode, transition
from scalp.persistence import SCHEMA_SQL, ScalpResearchRepository


NOW = datetime.fromisoformat("2026-08-21T10:00:00-04:00")


def bars(direction="up", count=30, breakout=False):
    result=[]; price=500.0
    for index in range(count):
        prior=price; price += .08 if direction=="up" else -.08
        high=max(prior,price)+.04; low=min(prior,price)-.04
        result.append({"timestamp":NOW-timedelta(minutes=count-index-1),"open":prior,"high":high,"low":low,"close":price,"volume":1000})
    if breakout:
        move=.8 if direction=="up" else -.8; prior=price; price+=move
        result[-1].update(open=prior,close=price,high=max(prior,price)+.02,low=min(prior,price)-.02,volume=1600)
    return result


def test_symbol_independence_call_put_and_attribution():
    engine=ScalpEngine(); spy=engine.evaluate("SPY",bars("up"),now=NOW); qqq=engine.evaluate("QQQ",bars("down"),now=NOW)
    assert spy.symbol=="SPY" and spy.direction.value=="CALL"
    assert qqq.symbol=="QQQ" and qqq.direction.value=="PUT"
    assert spy.opportunity_id != qqq.opportunity_id
    assert spy.strategy=="SCALP_RESEARCH" and spy.mode==StrategyMode.SHADOW


def test_missing_data_is_no_trade_and_maximum_chase_is_explicit():
    idle=ScalpEngine().evaluate("SPY",[],now=NOW)
    assert idle.state==ScalpState.IDLE and idle.direction is None
    active=ScalpEngine().evaluate("SPY",bars("up",breakout=True),now=NOW)
    assert active.maximum_chase is not None and active.entry_zone is not None
    assert active.state in {ScalpState.TRIGGERED,ScalpState.EXTENDED}


def test_state_machine_accepts_expected_path_and_rejects_jump():
    assert transition("IDLE","WATCHING")==ScalpState.WATCHING
    assert transition("FORMING","READY")==ScalpState.READY
    assert transition("READY","TRIGGERED")==ScalpState.TRIGGERED
    with pytest.raises(ValueError): transition("IDLE","TRIGGERED")


def quotes():
    return [
      {"symbol":"SPY260821C00500000","option_type":"call","dte":0,"bid":1.00,"ask":1.10,"delta":.52,"volume":100,"open_interest":500,"iv":.2},
      {"symbol":"SPY260822C00500000","option_type":"call","dte":1,"bid":1.30,"ask":1.42,"delta":.60,"volume":80,"open_interest":400,"iv":.21},
      {"symbol":"BAD","option_type":"call","dte":3,"bid":.5,"ask":1.0,"delta":.2,"volume":0,"open_interest":0},
    ]


def test_contract_filtering_and_dte_classification():
    accepted,rejected=filter_contracts(quotes(),"CALL")
    assert [row["term"] for row in accepted]==["0DTE","1DTE"]
    assert rejected[0]["rejection_reasons"]==["dte_outside_research_universe","delta_outside_range","spread_too_wide","low_volume","low_open_interest"]


def test_realistic_execution_is_primary_and_includes_slippage_and_fees():
    result=simulate_execution(quotes()[0],{"bid":1.30,"ask":1.40},config=ExecutionConfig(.02,.03,.65))
    assert result["entry_fill"]==pytest.approx(1.12) and result["exit_fill"]==pytest.approx(1.27)
    assert result["realistic_pnl"] < result["ideal_pnl"]
    assert result["slippage"]>0 and result["fees"]==1.3


def test_scalp_exit_rules_are_independent_and_max_hold_applies():
    opp=ScalpEngine().evaluate("SPY",bars("up"),now=NOW)
    assert evaluate_exit(opp,underlying_price=opp.invalidation-.01,option_return_pct=0,hold_minutes=1)=="UNDERLYING_INVALIDATION"
    assert evaluate_exit(opp,underlying_price=opp.features["price"],option_return_pct=31,hold_minutes=2)=="PROFIT_TARGET"
    assert evaluate_exit(opp,underlying_price=opp.features["price"],option_return_pct=0,hold_minutes=15)=="MAX_HOLD"


def sample(symbol,pnl,**extra):
    return {"symbol":symbol,"strategy":"SCALP_RESEARCH","realistic_pnl":pnl,"ideal_pnl":pnl+3,"hold_minutes":5,"mfe":10,"mae":-4,"setup_family":"VWAP_CONTINUATION","direction":"CALL","term":"0DTE",**extra}


def test_performance_and_normalized_spy_qqq_comparison():
    metrics=performance([sample("SPY",20),sample("SPY",-10)])
    assert metrics["expectancy"]==5 and metrics["profit_factor"]==2 and metrics["maximum_drawdown"]==10
    assert metrics["evidence"]=="INSUFFICIENT" and metrics["by_term"]["0DTE"]["triggered_trades"]==2
    result=compare([sample("SPY",10)],[sample("QQQ",20)])
    assert result["SPY"]["expectancy"]==10 and result["QQQ"]["expectancy"]==20


def test_new_shared_modules_have_no_streamlit_or_broker_submission_dependency():
    import scalp.engine, scalp.features, scalp.signals, scalp.exits, scalp.contracts, scalp.persistence, scalp.analytics
    source="\n".join(inspect.getsource(module) for module in (scalp.engine,scalp.features,scalp.signals,scalp.exits,scalp.contracts,scalp.persistence,scalp.analytics))
    assert "streamlit" not in source.lower()
    assert "submit_order" not in source and "place_order" not in source


def test_persistence_is_additive_and_strategy_attribution_is_forced():
    class Cursor:
        def __init__(self): self.calls=[]
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def execute(self,*args): self.calls.append(args)
    class Connection:
        def __init__(self): self.cursor_value=Cursor(); self.commits=0
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def cursor(self): return self.cursor_value
        def commit(self): self.commits+=1
    connections=[]
    def factory(): connections.append(Connection()); return connections[-1]
    repo=ScalpResearchRepository(factory); repo.initialize()
    opportunity=ScalpEngine().evaluate("SPY",bars("up"),now=NOW); repo.save_observation(opportunity)
    assert "scalp_research_observations" in SCHEMA_SQL and "intraday_paper_trades" not in SCHEMA_SQL
    insert=connections[-1].cursor_value.calls[0]
    assert "SCALP_RESEARCH" in insert[1] and "SHADOW" in insert[1]
