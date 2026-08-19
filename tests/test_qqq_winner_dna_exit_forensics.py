import copy
import inspect
from datetime import datetime, timedelta, timezone

from analysis.qqq_winner_dna_exit_forensics import (
    analyze_qqq_forensics, classify_trade, compact_time_bucket,
    reentry_features, spread_bucket, time_bucket,
)
from analysis.run_qqq_winner_dna_exit_forensics import read_qqq_snapshot
from contextual_research import simulate_shadow_exits

NOW = datetime(2026, 8, 17, 14, tzinfo=timezone.utc)


def trade(identity, symbol="QQQ", *, opened=NOW, pnl=10, return_pct=10, mfe=20, mae=-3, direction="CALL", dte=0, spread=.4):
    return {"trade_id":identity,"opportunity_id":f"o-{identity}","variant":"INTRADAY_MANAGED","symbol":symbol,
        "direction":direction,"opened_at":opened.isoformat() if opened else None,
        "closed_at":(opened+timedelta(minutes=30)).isoformat() if opened else None,"status":"CLOSED" if opened else "OPEN",
        "pnl":pnl,"return_pct":return_pct,"mfe":mfe,"mae":mae,"entry_fill":1,"spread_percent":spread,
        "dte":dte,"total_debit":100,"exit_reason":"TARGET","signal_age_seconds":45}


def test_exact_qqq_isolation_excludes_spy_and_broad_mirror_without_mutation():
    rows=[trade("q"),trade("s","SPY"),{**trade("m"),"symbol":"AAPL","variant":"MIRROR"}];before=copy.deepcopy(rows)
    report=analyze_qqq_forensics(rows)
    assert rows==before and report["inventory"]["qqq_records"]==1
    assert {r["reason"] for r in report["inventory"]["excluded"]}=={"NON_QQQ"}
    assert report["per_trade"][0]["trade_id"]=="q"


def test_predeclared_development_and_forward_boundaries():
    rows=[trade("d",opened=datetime(2026,8,13,14,tzinfo=timezone.utc)),trade("f",opened=datetime(2026,8,17,14,tzinfo=timezone.utc))]
    report=analyze_qqq_forensics(rows)
    scopes={row["trade_id"]:row["scope"] for row in report["per_trade"]}
    assert scopes=={"d":"DEVELOPMENT","f":"FORWARD TEST"}


def test_time_spread_sequence_and_reentry_buckets_are_deterministic():
    assert time_bucket(datetime(2026,8,17,13,45,tzinfo=timezone.utc))=="09:30-10:00"
    assert compact_time_bucket(datetime(2026,8,17,19,15,tzinfo=timezone.utc))=="POWER HOUR"
    assert [spread_bucket(x) for x in (.5,.75,1.25,1.75,2.5,4,None)]==["<=0.5%","0.5-1%","1-1.5%","1.5-2%","2-3%",">3%","UNAVAILABLE"]
    first=trade("one");second=trade("two",opened=NOW+timedelta(hours=1));second["direction"]="PUT"
    features=reentry_features([second,first])
    assert features["one"]["trade_sequence"]=="1st" and features["one"]["reentry_class"]=="FIRST ENTRY"
    assert features["two"]["trade_sequence"]=="2nd" and features["two"]["reentry_class"]=="OPPOSITE-DIRECTION REVERSAL"


def test_entry_and_exit_failure_classification_is_predeclared():
    assert classify_trade(trade("never",mfe=2,mae=-20,return_pct=-30))=="ENTRY_NEVER_WORKED"
    assert classify_trade(trade("weak",mfe=20,mae=-2,return_pct=4))=="ENTRY_WORKED_EXIT_WEAK"
    assert classify_trade(trade("clean",mfe=20,mae=-2,return_pct=15))=="CLEAN_WINNER"
    assert classify_trade(trade("missing",mfe=None,mae=None,return_pct=None))=="INSUFFICIENT_DATA"


def test_mfe_threshold_paths_and_unavailable_values_are_preserved():
    report=analyze_qqq_forensics([trade("winner",mfe=30,return_pct=10),trade("loser",mfe=15,return_pct=-5),trade("unknown",mfe=None,mae=None,return_pct=None,pnl=None)])
    paths={row["threshold"]:row for row in report["mfe_paths"]}
    assert paths[10]["n"]==2 and paths[10]["closed_negative"]==1
    assert paths[30]["n"]==1 and report["baseline"]["closed_trades"]==2


def test_shadow_exit_uses_first_hit_and_never_future_marks():
    marks=[{"observed_at":NOW.isoformat(),"unrealized_return":0},{"observed_at":(NOW+timedelta(minutes=1)).isoformat(),"unrealized_return":12},
        {"observed_at":(NOW+timedelta(minutes=2)).isoformat(),"unrealized_return":-1},{"observed_at":(NOW+timedelta(minutes=3)).isoformat(),"unrealized_return":50}]
    result=simulate_shadow_exits(marks)["BREAKEVEN_AFTER_10"]
    assert result["observed_at"]==marks[2]["observed_at"] and result["shadow_return"]==-1


def test_signal_context_is_entry_safe_and_post_trade_fields_do_not_create_features():
    row=trade("ctx");context={"opportunity_id":"o-ctx","technical":{"price_vs_vwap":"ABOVE","ema_aligned":True},
        "multi_timeframe":{"multi_timeframe_alignment_pct":100},"future_bar":{"close":999}}
    report=analyze_qqq_forensics([row],contexts=[context])
    assert report["dimensions"]["vwap"][0]["group"]=="ABOVE"
    assert "future_bar" not in report["per_trade"][0]
    assert report["metadata"]["hindsight_tags"]["entry_features"]=="PRE-ENTRY SAFE"


def test_empty_missing_lanes_and_quality_are_explicit():
    report=analyze_qqq_forensics([trade("open",opened=None,pnl=None,return_pct=None,mfe=None,mae=None)])
    assert report["data_quality"]["grade"]=="INSUFFICIENT"
    assert report["inventory"]["eligible_closed"]==0
    assert report["shadow_exits"]["coverage"].startswith("UNAVAILABLE")


def test_reader_source_is_bounded_projected_read_only_provider_and_write_free():
    source=inspect.getsource(read_qqq_snapshot).lower()
    assert "select *" not in source and "limit %s" in source
    assert "symbol='qqq'" in source and "read_only_connection" in source
    assert "row_limit" in source and "mark_limit" in source
    assert '"provider_calls":0' in source and '"database_writes":0' in source
    for forbidden in ("insert ","update ","delete ","create table","tradier"):
        assert forbidden not in source
