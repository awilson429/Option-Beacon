from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from capital_readiness import (
    AccountSnapshot, CapitalCandidate, DecisionState, DrawdownState,
    LaneCapitalConfig, ReadinessStatus, capital_efficiency,
    classify_readiness, drawdown_state, evaluate_capital_candidate,
    execution_outcome, lane_configs,
)
from capital_repository import CapitalRepository
from execution_config import ExecutionConfig
from option_position_tracker import PaperOptionPosition
from option_trade_engine import PaperOptionTrade
from paper_execution import run_paper_execution
from paper_execution_repository import PaperExecutionRepository
from trade_repository import TradeRepository


NOW = datetime(2026, 8, 24, 15, 0, tzinfo=timezone.utc)


def config(lane="OB", **changes):
    return replace(LaneCapitalConfig.for_lane(lane, {}), **changes)


def account(lane="OB", **changes):
    values = dict(lane=lane,starting_equity=25_000,current_equity=25_000,
        cash_available=25_000,peak_equity=25_000,daily_starting_equity=25_000)
    values.update(changes)
    return AccountSnapshot(**values)


def candidate(**changes):
    values = dict(opportunity_id="opp-1",symbol="QQQ",direction="CALL",observed_at=NOW,
        option_symbol="QQQ260824C00713000",expiration="2026-08-24",strike=713,dte=0,
        bid=1.40,ask=1.44,midpoint=1.42,stop_price=1.28,open_interest=500,volume=100,
        underlying_price=712.8,maximum_chase=713.2)
    values.update(changes)
    return CapitalCandidate(**values)


def test_independent_lane_defaults_and_environment_overrides():
    configs=lane_configs({})
    assert configs["OB"].starting_capital == configs["BROAD"].starting_capital == 25_000
    assert configs["OB"].risk_per_trade_pct == .5
    assert configs["BROAD"].risk_per_trade_pct == .25
    assert configs["OB"].max_concurrent_positions == 3
    assert configs["BROAD"].max_concurrent_positions == 6
    changed=lane_configs({"OB_STARTING_CAPITAL":"5000","BROAD_STARTING_CAPITAL":"100000"})
    assert changed["OB"].starting_capital == 5000
    assert changed["BROAD"].starting_capital == 100000


def test_position_sizing_uses_planned_loss_fees_slippage_and_rounds_down():
    decision=evaluate_capital_candidate(candidate(),account(),config(),now=NOW)
    assert decision.state == DecisionState.TAKE
    assert decision.realistic_entry == pytest.approx(1.43)
    assert decision.stop_fill == pytest.approx(1.27)
    assert decision.risk_per_contract == pytest.approx(17.30)
    assert decision.proposed_quantity == 7
    assert decision.proposed_dollar_risk == pytest.approx(121.10)
    assert decision.proposed_account_risk_pct == pytest.approx(.4844)


def test_minimum_contract_and_insufficient_buying_power_are_distinct():
    too_risky=evaluate_capital_candidate(candidate(),account(current_equity=1000),config(),now=NOW)
    assert too_risky.state == DecisionState.RISK_LIMIT
    assert too_risky.reason_code == "MINIMUM_POSITION_EXCEEDS_RISK_BUDGET"
    no_cash=evaluate_capital_candidate(candidate(),account(cash_available=100),config(),now=NOW)
    assert no_cash.state == DecisionState.NO_CAPITAL
    assert no_cash.reason_code == "INSUFFICIENT_BUYING_POWER"


def test_maximum_open_risk_and_positions_block_new_capital():
    risk=evaluate_capital_candidate(candidate(),account(open_risk=370),config(),now=NOW)
    assert risk.reason_code == "MAXIMUM_OPEN_RISK_REACHED"
    positions=evaluate_capital_candidate(candidate(),account(open_positions=3),config(),now=NOW)
    assert positions.reason_code == "MAXIMUM_CONCURRENT_POSITIONS"


def test_daily_loss_lock_does_not_describe_liquidation():
    decision=evaluate_capital_candidate(candidate(),account(daily_pnl=-500),config(),now=NOW)
    assert decision.state == DecisionState.BLOCKED
    assert decision.reason_code == "DAILY_LOSS_LIMIT_REACHED"
    assert "No new capital" in decision.explanation


@pytest.mark.parametrize(("drawdown","expected"),[(4.9,"NORMAL"),(5,"WARNING"),(8,"REDUCED_RISK"),(12,"HALTED")])
def test_drawdown_states(drawdown,expected):
    assert drawdown_state(account(current_drawdown_pct=drawdown),config()) == expected


def test_reduced_risk_halves_budget_and_halt_blocks():
    normal=evaluate_capital_candidate(candidate(),account(),config(),now=NOW)
    reduced=evaluate_capital_candidate(candidate(),account(current_drawdown_pct=8),config(),now=NOW)
    halted=evaluate_capital_candidate(candidate(),account(current_drawdown_pct=12),config(),now=NOW)
    assert reduced.proposed_quantity < normal.proposed_quantity
    assert reduced.drawdown_state == DrawdownState.REDUCED_RISK
    assert halted.reason_code == "DRAWDOWN_HALT"


@pytest.mark.parametrize(("candidate_changes","reason"),[
    ({"observed_at":NOW-timedelta(minutes=6)},"DATA_STALE"),
    ({"bid":1.0,"ask":1.5,"midpoint":1.25},"CONTRACT_SPREAD_TOO_WIDE"),
    ({"stop_price":1.44},"INVALID_STOP"),
    ({"underlying_price":713.3},"ENTRY_BEYOND_MAXIMUM_CHASE"),
    ({"provider_healthy":False},"PROVIDER_OR_SYSTEM_DEGRADED"),
    ({"option_symbol":None},"REQUIRED_DATA_UNAVAILABLE"),
    ({"opportunity_expired":True},"OPPORTUNITY_EXPIRED"),
])
def test_data_liquidity_and_entry_controls(candidate_changes,reason):
    assert evaluate_capital_candidate(candidate(**candidate_changes),account(),config(),now=NOW).reason_code == reason


def test_duplicate_exposure_is_lane_local():
    duplicate=account(duplicate_exposures=("QQQ:CALL",))
    assert evaluate_capital_candidate(candidate(),duplicate,config(),now=NOW).reason_code == "DUPLICATE_EXPOSURE"
    broad=account("BROAD",duplicate_exposures=())
    assert evaluate_capital_candidate(candidate(),broad,config("BROAD"),now=NOW).state == DecisionState.TAKE


def test_realistic_execution_keeps_theoretical_pnl_fees_and_slippage_separate():
    result=execution_outcome(quantity=2,theoretical_entry=1.42,realistic_entry=1.43,
        exit_bid=1.58,exit_ask=1.62,config=config())
    assert result["theoretical_pnl"] == 36
    assert result["realistic_exit"] == pytest.approx(1.59)
    assert result["fees"] == pytest.approx(2.60)
    assert result["slippage"] == pytest.approx(4)
    assert result["realistic_pnl"] == pytest.approx(29.40)


def readiness_metrics(**changes):
    values=dict(trades=120,sessions=35,expectancy=4,profit_factor=1.25,
        maximum_drawdown_pct=7,data_completeness=.97,execution_evidence=.97,
        risk_control_coverage=True,regimes=3,stable_across_regimes=False)
    values.update(changes); return values


def test_readiness_classification_requires_evidence_and_never_promotes_arbitrarily():
    assert classify_readiness(readiness_metrics(trades=10,sessions=3)) == ReadinessStatus.EARLY_RESEARCH
    assert classify_readiness(readiness_metrics(trades=40,sessions=15)) == ReadinessStatus.DEVELOPING
    assert classify_readiness(readiness_metrics()) == ReadinessStatus.PAPER_VALIDATED
    assert classify_readiness(readiness_metrics(trades=300,sessions=80,profit_factor=1.35,
        maximum_drawdown_pct=7,data_completeness=.99,execution_evidence=.99,
        regimes=4,stable_across_regimes=True)) == ReadinessStatus.LIVE_CANDIDATE
    assert classify_readiness(readiness_metrics(expectancy=-1)) == ReadinessStatus.NOT_READY
    assert classify_readiness(readiness_metrics(risk_control_coverage=False)) == ReadinessStatus.NOT_READY


def test_capital_efficiency_is_separate_from_raw_profit():
    assert capital_efficiency(500,5000) == 10
    assert capital_efficiency(500,0) is None


def test_repository_persists_independent_states_decisions_and_risk_tables(tmp_path):
    base=TradeRepository(tmp_path/"capital.db",database_url="")
    repository=CapitalRepository(base,configs=lane_configs({}))
    ob=evaluate_capital_candidate(candidate(),account(),config(),now=NOW)
    broad=evaluate_capital_candidate(candidate(),account("BROAD"),config("BROAD"),now=NOW)
    repository.record_decision(ob)
    repository.record_decision(broad)
    assert [row["lane"] for row in repository.lane_states()] == ["BROAD","OB"]
    decisions=repository.recent_decisions(limit=10)
    assert {row["lane"] for row in decisions} == {"OB","BROAD"}
    assert all(row["decision_state"] == "TAKE" for row in decisions)
    with base.connection() as connection:
        tables={row["name"] for row in base._fetchall(connection,
            "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"lane_capital_state","capital_decisions","capital_positions",
            "capital_risk_events","capital_equity_history","capital_daily_state"} <= tables


def test_rejected_hypothetical_outcome_never_changes_account_equity(tmp_path):
    base=TradeRepository(tmp_path/"missed.db",database_url="")
    repository=CapitalRepository(base,configs=lane_configs({}))
    rejected=evaluate_capital_candidate(candidate(bid=1,ask=1.5,midpoint=1.25),account(),config(),now=NOW)
    decision_id=repository.record_decision(rejected)
    before=repository.account_snapshot("OB",now=NOW).current_equity
    repository.record_hypothetical_outcome(decision_id,realistic_pnl=75,outcome="MISSED_WINNER")
    after=repository.account_snapshot("OB",now=NOW).current_equity
    assert before == after == 25_000
    row=repository.recent_decisions(lane="OB",limit=1)[0]
    assert row["hypothetical_realistic_pnl"] == 75


def test_worker_paper_handoff_creates_lane_owned_quantities_without_shared_dollars(tmp_path,monkeypatch):
    base=TradeRepository(tmp_path/"worker.db",database_url="")
    paper=PaperExecutionRepository(base)
    capital=CapitalRepository(base,configs=lane_configs({}))
    trade=PaperOptionTrade(trade_id="paper-1",source_signal_id="opp-1",created_timestamp=NOW,
        ticker="QQQ",direction="Bullish",underlying_entry_price=713,confidence=90,
        historical_grade="A",scanner_score=90,entry_reason="authoritative",
        expiration="2026-08-24",strike=713,option_type="call",option_symbol="QQQ-C",
        delta=.5,implied_volatility=.2,bid=.9,ask=1.1,mid=1,spread_percent=20,
        open_interest=500,volume=100)
    paper.append_once(trade)
    monkeypatch.setattr("paper_execution.capture_qualified_signal",lambda *args,**kwargs:trade)
    legacy=replace(ExecutionConfig(),simulation_profile="BROAD",trading_enabled=True,
        min_beacon_score=40,max_spread_percent=20,min_open_interest=50,min_volume=0)
    result=run_paper_execution([{"_authoritative_entry_id":"opp-1","timestamp":NOW.isoformat(),
        "symbol":"QQQ","score":90,"confidence":90}],config=legacy,now=NOW,
        market_open=True,trade_ledger=paper,position_store=paper,journal=paper,
        refreshed_positions=[],capital_repository=capital)
    assert len(result["opened"]) == 1
    assert result["opened"][0].quantity == 1
    with base.connection() as connection:
        positions=base._fetchall(connection,
            "SELECT lane,quantity,capital_committed FROM capital_positions ORDER BY lane")
        snapshots=base._fetchall(connection,
            "SELECT trade_id,lane FROM trade_management_snapshots ORDER BY lane")
    assert [(row["lane"],row["quantity"]) for row in positions] == [("BROAD",1),("OB",3)]
    assert positions[0]["capital_committed"] != positions[1]["capital_committed"]
    assert [(row["trade_id"],row["lane"]) for row in snapshots] == [
        ("BROAD:paper-1","BROAD"),("OB:paper-1","OB")]


def test_snapshot_write_failure_is_logged_and_does_not_change_capital_position(tmp_path,monkeypatch,caplog):
    base=TradeRepository(tmp_path/"snapshot-failure.db",database_url="")
    capital=CapitalRepository(base,configs=lane_configs({}))
    position=PaperOptionPosition(
        trade_id="paper-1",status="OPEN",entry_time=NOW-timedelta(minutes=2),last_update=NOW,
        ticker="QQQ",direction="Bullish",option_symbol="QQQ260824C00713000",
        expiration="2026-08-24",strike=713,option_type="call",entry_bid=1.4,entry_ask=1.44,
        entry_mid=1.42,current_bid=1.5,current_ask=1.54,current_mid=1.52,current_return_percent=7.04,
        highest_mid=1.52,lowest_mid=1.4,max_favorable_excursion_percent=7.04,
        max_adverse_excursion_percent=-1.41,last_underlying_price=713.8,last_option_quote_time=NOW,
    )
    decision={"lane":"OB","proposed_quantity":2,"realistic_entry":1.43,
              "theoretical_entry":1.42,"stop_fill":1.27,
              "proposed_capital_required":286,"proposed_dollar_risk":32}
    monkeypatch.setattr(base,"record_trade_management_snapshot",
        lambda payload: (_ for _ in ()).throw(RuntimeError("snapshot unavailable")))
    with caplog.at_level("ERROR"):
        capital._upsert_from_paper(position,"opp-1",decision,now=NOW)
    with base.connection() as connection:
        stored=base._fetchone(connection,
            "SELECT position_id,status FROM capital_positions WHERE position_id=?",("OB:paper-1",))
    assert stored == {"position_id":"OB:paper-1","status":"OPEN"}
    assert "trade_management_snapshot_write_failed" in caplog.text
