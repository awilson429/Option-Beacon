from datetime import datetime,timezone
import inspect
import json

import pytest

from experiment_scorecard import (ExperimentScorecardRepository,age_bucket,build_scorecard,
    experiment_period,governance,lane_summary,spread_gate_effectiveness)
from experiment_scorecard_dashboard import render_experiment_scorecard


def row(identity,session,pnl,*,opened=True,spread=10,age=90,debit=100,rejected=None):
    at=f"{session}T14:00:00+00:00"
    return {"opportunity_id":identity,"session":session,"signal_at":at,"opened_at":at if opened else None,
        "closed_at":f"{session}T15:00:00+00:00" if opened and pnl is not None else None,"pnl":pnl,
        "return_pct":pnl,"spread_percent":spread,"signal_age_seconds":age,"debit":debit,
        "broad_decision":"ACCEPTED","rejection_reason":rejected}


def fixture():
    auth=[{"opportunity_id":f"a{i}","session":"2026-08-13"} for i in range(3)]+[{"opportunity_id":"f1","session":"2026-08-17"}]
    mirror=[row("a1","2026-08-13",10),row("a2","2026-08-13",-20),row("a3","2026-08-13",0),row("f1","2026-08-17",5)]
    broad=[row("a1","2026-08-13",8),row("a2","2026-08-13",-10),row("f1","2026-08-17",4)]
    filtered=[row("a1","2026-08-13",10),row("a2","2026-08-13",None,opened=False,spread=25,rejected="SPREAD_TOO_WIDE"),
              row("a3","2026-08-13",None,opened=False,spread=30,rejected="SPREAD_TOO_WIDE"),row("f1","2026-08-17",5)]
    return auth,mirror,broad,filtered


def test_daily_lane_totals_and_missing_values_are_not_zero():
    report=build_scorecard(*fixture()); day=report["daily"][0]
    assert day["lanes"]["MIRROR"]["opened"]==4 if day["session"]=="2026-08-17" else day["lanes"]["MIRROR"]["opened"]==3
    development=next(d for d in report["daily"] if d["session"]=="2026-08-13")
    assert development["lanes"]["MIRROR"]["opened"]==3
    assert development["lanes"]["BROAD"]["opened"]==2
    assert development["lanes"]["FILTERED"]["opened"]==1
    assert development["lanes"]["FILTERED"]["unrealized_pnl"] is None


def test_exact_shadow_join_counts_winners_losses_flats_and_unknowns():
    _,mirror,_,filtered=fixture()
    result=spread_gate_effectiveness(filtered,mirror)
    assert result["spread_rejected"]==2 and result["rejected_mirror_losers"]==1
    assert result["rejected_mirror_flats"]==1 and result["unknown_shadow_outcomes"]==0
    assert result["pnl_avoided_from_losers"]==20 and result["net_pnl_effect"]==20
    missing={**filtered[1],"opportunity_id":"missing"}
    result=spread_gate_effectiveness([missing],mirror)
    assert result["unknown_shadow_outcomes"]==1 and result["net_pnl_effect"]==0


def test_rejected_mirror_winner_is_sacrificed_and_net_effect_is_negative():
    rejected=[row("winner","2026-08-17",None,opened=False,spread=25,rejected="SPREAD_TOO_WIDE")]
    mirror=[row("winner","2026-08-17",15)]
    result=spread_gate_effectiveness(rejected,mirror)
    assert result["rejected_mirror_winners"]==1 and result["pnl_sacrificed_from_winners"]==15
    assert result["net_pnl_effect"]==-15


def test_signal_age_buckets_are_observational_and_complete():
    assert [age_bucket(v) for v in (60,61,120,121,180,181,300,301,None)]==["LE_60","61_120","61_120","121_180","121_180","181_300","181_300","GT_300","DATA UNAVAILABLE"]
    old=row("old","2026-08-17",10,age=999)
    assert lane_summary([old])["opened"]==1


def test_development_forward_boundary_and_governance():
    assert experiment_period("2026-08-10")==experiment_period("2026-08-13")=="DEVELOPMENT"
    assert experiment_period("2026-08-14")=="OUTSIDE BOUNDARY"
    assert experiment_period("2026-08-17")=="FORWARD TEST"
    assert [governance(v) for v in (0,29,30,49,50)]==["INSUFFICIENT DATA","INSUFFICIENT DATA","DESCRIPTIVE ONLY","DESCRIPTIVE ONLY","ELIGIBLE FOR CHRONOLOGICAL VALIDATION"]


def test_history_scope_does_not_change_accounting_for_same_session():
    auth,mirror,broad,filtered=fixture()
    full=build_scorecard(auth,mirror,broad,filtered)
    scoped=build_scorecard([r for r in auth if r["session"]=="2026-08-13"],[r for r in mirror if r["session"]=="2026-08-13"],[r for r in broad if r["session"]=="2026-08-13"],[r for r in filtered if r["session"]=="2026-08-13"])
    full_day=next(d for d in full["daily"] if d["session"]=="2026-08-13")
    assert full_day["lanes"]==scoped["daily"][0]["lanes"]


def test_query_is_projected_bounded_and_broad_only():
    source=inspect.getsource(ExperimentScorecardRepository.load).lower()
    assert "select *" not in source and "limit ?" in source
    assert "simulation_profile" in source and "='broad'" in source
    assert "safe" not in source and "intraday" not in source
    assert "mirror_execution_marks" not in source


def test_streamlit_scorecard_is_read_only_and_has_no_provider_or_worker_calls():
    source=inspect.getsource(render_experiment_scorecard).lower()
    for forbidden in ("insert ","update ","delete ","create table","option_quote","chain_provider","run_filtered_execution"):
        assert forbidden not in source
