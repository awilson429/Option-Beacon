from datetime import date, datetime, timedelta, timezone

import pytest

from intraday_execution import FILL_MODEL, IntradayRepository, entry_fill, exit_fill, managed_update, select_contracts
from intraday_strategy import Candidate
from trade_repository import TradeRepository

def chain(dte, symbol):
    return {"symbol": symbol, "expiration": (date(2026,8,7)+timedelta(days=dte)).isoformat(),
            "option_type": "call", "strike": 600, "bid": 1, "ask": 1.10,
            "delta": .52, "volume": 5000, "open_interest": 10000}

def test_0dte_1dte_selection_and_spread_fills():
    selected = select_contracts([chain(0,"SPY0"), chain(1,"SPY1")], "call", 600, date(2026,8,7))
    assert [row["dte"] for row in selected] == [0,1]
    assert entry_fill(1,1.10) == pytest.approx(1.0625)
    assert exit_fill(1,1.10) == pytest.approx(1.0375)

def test_managed_stops_max_hold_and_excursions():
    now = datetime(2026,8,7,15,tzinfo=timezone.utc)
    position = {"entry_fill":1,"opened_at":now.isoformat(),"mfe_pct":30,"mae_pct":-5,"protection_armed":True,"trailing_active":True}
    update = managed_update(position,{"bid":1.18,"ask":1.20},now+timedelta(minutes=1))
    assert update["exit_reason"] == "TRAILING_STOP" and update["mfe_pct"] == 30
    stopped = managed_update({**position,"mfe_pct":0,"protection_armed":False,"trailing_active":False},{"bid":.7,"ask":.72},now)
    assert stopped["exit_reason"] == "HARD_STOP"
    held = managed_update({**position,"mfe_pct":0,"protection_armed":False,"trailing_active":False},{"bid":1,"ask":1.02},now+timedelta(minutes=46))
    assert held["exit_reason"] == "MAX_HOLD"

def test_separate_schema_one_contract_two_variants_no_duplicates(tmp_path):
    ledger = IntradayRepository(TradeRepository(tmp_path/"state.db"))
    candidate = Candidate("opp","SPY","CALL","VWAP RECLAIM",78,600,600.1,datetime.now(timezone.utc),"MORNING","TRENDING UP")
    contract = {**chain(0,"SPY0"),"option_symbol":"SPY0","dte":0,"spread_pct":9.5}
    ledger.save_signal(candidate)
    assert len(ledger.open_variants(candidate,contract)) == 2
    assert ledger.open_variants(candidate,contract) == []
    rows = ledger.list_trades()
    assert {r["variant"] for r in rows} == {"INTRADAY_MIRROR","INTRADAY_MANAGED"}
    assert all(r["quantity"] == 1 and r["fill_model"] == FILL_MODEL for r in rows)
    managed = next(r for r in rows if r["variant"] == "INTRADAY_MANAGED")
    closed = ledger.update_managed(managed["trade_id"], {"bid":.7,"ask":.72})
    assert closed["status"] == "CLOSED" and closed["exit_reason"] == "HARD_STOP"
    assert ledger.close_mirror("opp", {"bid":1.2,"ask":1.22}) == 1
