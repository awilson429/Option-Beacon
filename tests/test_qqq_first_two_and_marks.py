from datetime import date, datetime, timedelta, timezone

import pytest

import optionbeacon.worker.intraday as worker
from intraday_execution import IntradayRepository
from intraday_strategy import Candidate
from qqq_forward_research import compare_first_two, governance, sequence_bucket
from qqq_forward_research_dashboard import mark_coverage
from trade_repository import TradeRepository

NOW=datetime(2026,8,20,14,0,tzinfo=timezone.utc)


def candidate(identity):
    return Candidate(identity,"QQQ","CALL","VWAP RECLAIM",78,480,480.1,NOW,"MORNING","TRENDING UP")


def contract():
    return {"option_symbol":"QQQ-C","symbol":"QQQ-C","expiration":date(2026,8,20).isoformat(),"dte":0,
        "option_type":"call","strike":480,"bid":1,"ask":1.10,"delta":.52,"volume":5000,"open_interest":10000,"spread_pct":9.5}


def opened(ledger, identity, now):
    item=candidate(identity); ledger.save_signal(item); ids=ledger.open_variants(item,contract(),now=now)
    return [(trade_id,ledger.record_first_two_shadow(trade_id,now=now)) for trade_id in sorted(ids)]


def test_first_second_accepted_third_and_tenth_rejected_ties_stable_and_replay_safe(tmp_path):
    ledger=IntradayRepository(TradeRepository(tmp_path/"state.db")); results=[]
    for index in range(5): results.extend(opened(ledger,f"opp-{index}",NOW))
    ordered=sorted(results,key=lambda item:item[1]["session_trade_number"])
    assert [row[1]["shadow_status"] for row in ordered[:3]]==["SHADOW_ACCEPTED","SHADOW_ACCEPTED","SHADOW_REJECTED"]
    assert ordered[2][1]["rejection_reason"]=="SESSION_SEQUENCE_GT_2" and ordered[9][1]["session_trade_number"]==10
    for index in range(0,10,2):
        assert [row[0] for row in ordered[index:index+2]]==sorted(row[0] for row in ordered[index:index+2])
    assert ledger.record_first_two_shadow(ordered[0][0],now=NOW)["shadow_trade_id"]==ordered[0][1]["shadow_trade_id"]


def test_eastern_session_reset_and_same_contract_distinct_identity(tmp_path):
    ledger=IntradayRepository(TradeRepository(tmp_path/"state.db"))
    first=opened(ledger,"one",NOW); next_day=opened(ledger,"two",NOW+timedelta(days=1))
    assert [row[1]["session_trade_number"] for row in first]==[1,2]
    assert [row[1]["session_trade_number"] for row in next_day]==[1,2]
    assert len({row[1]["source_trade_id"] for row in first+next_day})==4


def test_marks_exact_ordered_duplicate_safe_and_time_bounded(tmp_path):
    ledger=IntradayRepository(TradeRepository(tmp_path/"state.db")); trades=opened(ledger,"one",NOW)
    first,second=trades[0][0],trades[1][0]; quote={"bid":1.1,"ask":1.2}
    assert ledger.record_position_mark(first,quote,now=NOW-timedelta(seconds=1)) is None
    mark=ledger.record_position_mark(first,quote,now=NOW+timedelta(minutes=1)); assert mark
    assert ledger.record_position_mark(first,quote,now=NOW+timedelta(minutes=1)) is None
    assert ledger.record_position_mark(second,quote,now=NOW+timedelta(minutes=1))
    snapshot=ledger.qqq_research_snapshot()
    assert {row["trade_id"] for row in snapshot["marks"]}=={first,second}
    assert all(row["variant"] in {"INTRADAY_MIRROR","INTRADAY_MANAGED"} for row in snapshot["marks"])


def test_existing_cached_quote_adds_no_provider_calls_and_failure_does_not_block_management(tmp_path,monkeypatch):
    repository=TradeRepository(tmp_path/"state.db"); ledger=IntradayRepository(repository); opened(ledger,"one",NOW)
    calls=[]
    monkeypatch.setattr(worker,"detect_candidate",lambda *_a,**_k:None)
    original=IntradayRepository.record_position_mark
    monkeypatch.setattr(IntradayRepository,"record_position_mark",lambda *_a,**_k:(_ for _ in ()).throw(RuntimeError("research down")))
    bars=lambda symbol,**kwargs:[{"timestamp":NOW,"open":480,"high":481,"low":479,"close":480,"volume":1000}]
    assert worker.run_intraday_cycle(repository,now=NOW+timedelta(minutes=1),bar_provider=bars,
        quote_provider=lambda symbol:calls.append(symbol) or {"bid":1.1,"ask":1.2})==0
    assert len(calls)==1  # two variants share the pre-existing contract quote
    assert all(row["update_status"]=="CURRENT" for row in ledger.list_trades(status="OPEN"))
    monkeypatch.setattr(IntradayRepository,"record_position_mark",original)


def row(number,day,pnl,status="SHADOW_ACCEPTED"):
    return {"source_trade_id":f"t-{day}-{number}","eastern_session":day,"session_trade_number":number,
        "shadow_status":status,"opened_at":f"{day}T14:00:00+00:00","closed_at":f"{day}T15:00:00+00:00",
        "realized_pnl":pnl,"realized_return_percent":pnl}


def test_forward_analytics_governance_sequence_and_incomplete_exclusion():
    rows=[]
    for session in range(21):
        day=(NOW.date()+timedelta(days=session)).isoformat()
        rows.extend([row(1,day,10),row(2,day,5),row(3,day,-20,"SHADOW_REJECTED")])
    report=compare_first_two(rows,experiment_start_timestamp=rows[0]["opened_at"],now=NOW+timedelta(days=21))
    assert report["first_two_shadow"]["accepted_trades"]==42 and report["governance"]=="UNSTABLE"
    assert report["first_two_shadow"]["expectancy"] > report["baseline"]["expectancy"]
    assert report["sequence_buckets"]["3rd–5th"]["trades"]==21
    assert governance(50,20)=="ELIGIBLE FOR FORWARD EVALUATION"
    assert [sequence_bucket(v) for v in (1,2,3,6,11)]==["1st","2nd","3rd–5th","6th–10th","11th+"]


def test_missing_marks_remain_unavailable():
    coverage=mark_coverage([{"source_trade_id":"a"},{"source_trade_id":"b"}],[])
    assert coverage["positions_with_1_or_more_marks"]==0 and coverage["average_marks_per_trade"]==0
    assert coverage["earliest_mark"] is None and coverage["missing_mark_trades"]==["a","b"]
