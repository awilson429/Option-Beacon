from datetime import datetime, timedelta, timezone
import inspect

import pytest

from filtered_execution import (FilteredExecutionRepository, filtered_summary,
    filtered_enabled, run_filtered_execution, signal_age_bucket, spread_percent)
from filtered_execution_analytics import filtered_comparison
from trade_repository import TradeRepository

NOW=datetime(2026,8,13,15,tzinfo=timezone.utc)


def event(identity="a", seconds=121):
    return {"id":"e","opportunity_id":identity,"trade_id":identity,"symbol":"SPY",
            "event_timestamp":(NOW-timedelta(seconds=seconds)).isoformat()}


def mirror(identity="a", spread=20, status="OPEN"):
    mid=1; bid=mid*(1-spread/200); ask=mid*(1+spread/200)
    return {"mirror_trade_id":f"m-{identity}","opportunity_id":identity,"direction":"Bullish",
        "option_symbol":"SPY-C","option_type":"call","expiration":"2026-08-14","strike":500,"dte":1,
        "entry_bid":bid,"entry_ask":ask,"entry_fill":1.05,"spread_percent":spread,"total_debit":105,
        "opened_at":NOW.isoformat(),"status":status}


@pytest.fixture
def repo(tmp_path):
    base=TradeRepository(tmp_path/"state.db")
    return base,FilteredExecutionRepository(base)


def test_broad_rejection_prevents_execution(repo):
    _,filtered=repo; row=filtered.record("a",event(),{"accepted":0,"reason_code":"SCORE_TOO_LOW"},mirror(),NOW)
    assert row["status"]=="REJECTED" and row["execution_rejection_reason"]=="BROAD_REJECTED"


def test_filtered_is_paper_enabled_by_default_and_can_be_disabled():
    assert filtered_enabled({}) is True
    assert filtered_enabled({"OPTIONBEACON_FILTERED_ENABLED":"false"}) is False


@pytest.mark.parametrize("spread,eligible,reason",[(20,1,None),(19.99,1,None),(20.01,0,"SPREAD_TOO_WIDE")])
def test_spread_cap_boundary_and_conservative_mirror_fill(repo,spread,eligible,reason):
    _,filtered=repo; row=filtered.record("a",event(),{"accepted":1,"reason_code":"ELIGIBLE"},mirror(spread=spread),NOW)
    assert row["execution_eligible"]==eligible and row["execution_rejection_reason"]==reason
    assert row["entry_fill"]==1.05
    assert spread_percent(row["entry_bid"],row["entry_ask"])==pytest.approx(spread)


def test_signal_age_buckets_persist_and_do_not_block(repo):
    assert [signal_age_bucket(v) for v in (60,61,120,121,180,181,300,301)] == ["LE_60","61_120","61_120","121_180","121_180","181_300","181_300","GT_300"]
    _,filtered=repo; row=filtered.record("a",event(seconds=400),{"accepted":1},mirror(),NOW)
    assert row["signal_age_seconds"]==400 and row["signal_age_bucket"]=="GT_300" and row["execution_eligible"]==1


def test_idempotency_restart_and_same_contract_across_opportunities(repo):
    base,filtered=repo
    first=filtered.record("a",event("a"),{"accepted":1},mirror("a"),NOW)
    again=FilteredExecutionRepository(base).record("a",event("a"),{"accepted":1},mirror("a"),NOW)
    second=filtered.record("b",event("b"),{"accepted":1},mirror("b"),NOW)
    assert first["filtered_trade_id"]==again["filtered_trade_id"]
    assert second["filtered_trade_id"]!=first["filtered_trade_id"] and second["option_symbol"]==first["option_symbol"]


def test_loss_cap_shadows_use_first_observed_breach(repo):
    _,filtered=repo; row=filtered.record("a",event(),{"accepted":1},mirror(),NOW)
    closed={**mirror(),"status":"CLOSED","realized_return_percent":-60,"realized_pnl":-63,
            "exit_quote_at":NOW.isoformat(),"authoritative_exit_reason":"STOP","exit_fill":.42}
    marks=[{"return_pct":-10},{"return_pct":-35},{"return_pct":-50},{"return_pct":-60}]
    filtered.sync(row,closed,marks,NOW)
    result=filtered.get("a")
    assert result["shadow_30_return"]==-35 and result["shadow_45_return"]==-50
    assert result["mfe_pct"]==-10 and result["mae_pct"]==-60 and result["giveback_pct"]==50


class Paper:
    def __init__(self,accepted): self.accepted=accepted
    def analytics_decisions(self,*_args,**_kwargs):
        return [{"source_signal_id":"a","accepted":self.accepted,"reason_code":"X","metadata_json":'{"simulation_profile":"BROAD"}'}]
class Mirrors:
    def __init__(self,row): self.row=row
    def get(self,identity): return self.row if identity=="a" else None
    def marks(self,_trade): return []


def test_run_reuses_persisted_broad_and_mirror_without_provider_calls(repo):
    _,filtered=repo
    result=run_filtered_execution(None,filtered,Paper(True),Mirrors(mirror()),[event()],enabled=True,scanner_id="s",now=NOW)
    assert result["opened"]==1
    source=inspect.signature(run_filtered_execution).parameters
    assert "chain_provider" not in source and "quote_provider" not in source


def test_analytics_spread_age_loss_caps_and_governance():
    rows=[{"opportunity_id":"a","execution_rejection_reason":"SPREAD_TOO_WIDE","signal_age_bucket":"GT_300"},
          {"opportunity_id":"b","execution_eligible":1,"status":"CLOSED","signal_age_bucket":"LE_60","realized_pnl":10,
           "realized_return_percent":10,"shadow_30_return":10,"shadow_30_pnl":10,"shadow_45_return":10,"shadow_45_pnl":10,
           "broad_decision":"ACCEPTED","spread_percent":10,"signal_age_seconds":30}]
    mirrors=[{"opportunity_id":"a","realized_pnl":-20},{"opportunity_id":"b","realized_pnl":10}]
    analysis=filtered_comparison(rows,mirrors)
    assert analysis["spread_gate"]=={"rejected":1,"rejected_winners":0,"rejected_losers":1,"rejected_mirror_pnl":-20.0,"retained_mirror_pnl":10.0}
    assert filtered_summary(rows)["governance"]=="INSUFFICIENT DATA"


def test_dashboard_reader_is_bounded_projected_and_streamlit_has_no_writes():
    source=inspect.getsource(FilteredExecutionRepository.rows).lower()
    assert "select *" not in source and "limit ?" in source
    import app
    ui=inspect.getsource(app.render_paper_trading_page).lower()
    assert "filteredexecutionrepository" in ui and "filtered_summary" in ui
    assert all(token not in ui for token in ("insert into filtered", "update filtered", "delete from filtered"))
