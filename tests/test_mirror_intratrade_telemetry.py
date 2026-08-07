import json
import logging
from datetime import date, datetime, timedelta, timezone

import pytest

from analysis.mirror_pnl_attribution import build_session_audit
from mirror_execution import MirrorExecutionRepository, run_mirror_execution
from trade_repository import TradeRepository


NOW = datetime(2026, 8, 7, 14, 0, tzinfo=timezone.utc)


class Chain:
    def expirations(self, ticker): return ["2026-08-14"], ""
    def chain(self, ticker, expiration):
        return [{"symbol": "SPY260814C00100000", "option_type": "call",
                 "expiration": expiration, "strike": 100, "bid": 1, "ask": 2,
                 "open_interest": 1000, "volume": 1000, "delta": .5}], ""


def setup(tmp_path):
    repository = TradeRepository(tmp_path / "mirror.db", database_url="")
    repository.create_opportunity(opportunity_id="auth-1", idempotency_key="auth-1",
        symbol="SPY", direction="Bullish", playbook="Breakout", signal_timestamp=NOW,
        source_version="test", entry_reference=100)
    repository.open_trade("auth-1", trade_id="auth-1", opened_at=NOW, entry_price=100)
    repository.record_trade_event(dedup_key="entry", opportunity_id="auth-1", trade_id="auth-1",
        symbol="SPY", event_type="TRADE_ENTERED", event_timestamp=NOW,
        description="entered", direction="Bullish", entry_price=100)
    candidate = {"_authoritative_entry_id":"auth-1", "symbol":"SPY", "price":100,
                 "bias":"Bullish", "trade_plan":{"direction":"Bullish"}}
    return repository, MirrorExecutionRepository(repository), candidate


def cycle(repository, mirror, candidates, now, quote_provider, **kwargs):
    return run_mirror_execution(repository, mirror, candidates, enabled=True,
        scanner_id="worker", now=now, chain_provider=Chain(),
        quote_provider=quote_provider, underlying_prices={"SPY": kwargs.get("underlying", 100)})


def test_snapshots_append_and_high_water_survives_restart(tmp_path):
    repository, mirror, candidate = setup(tmp_path)
    cycle(repository, mirror, [candidate], NOW, lambda symbol: ({"bid":1,"ask":2},""))
    trade = mirror.rows()[0]
    first = mirror.marks(trade["mirror_trade_id"])
    assert len(first) == 1 and first[0]["underlying_price"] == 100
    assert first[0]["update_status"] == "CURRENT"
    cycle(repository, MirrorExecutionRepository(repository), [], NOW + timedelta(minutes=1),
          lambda symbol: ({"bid":2,"ask":3},""), underlying=101)
    restarted = MirrorExecutionRepository(repository)
    marks = restarted.marks(trade["mirror_trade_id"])
    row = restarted.rows()[0]
    assert len(marks) == 2 and marks[0]["mark_id"] != marks[1]["mark_id"]
    assert row["mfe_pct"] == pytest.approx((2.375 / 1.625 - 1) * 100)
    assert row["mae_pct"] == pytest.approx((1.375 / 1.625 - 1) * 100)
    assert row["peak_return_pct"] == row["mfe_pct"]
    # A lower subsequent mark cannot reduce MFE or reset MAE.
    cycle(repository, restarted, [], NOW + timedelta(minutes=2),
          lambda symbol: ({"bid":1.5,"ask":2},""))
    final = restarted.rows()[0]
    assert final["mfe_pct"] == row["mfe_pct"]
    assert final["mae_pct"] == row["mae_pct"]
    # Replaying the same observed timestamp cannot append or alter high-water state.
    cycle(repository, restarted, [], NOW + timedelta(minutes=2),
          lambda symbol: ({"bid":3,"ask":4},""))
    assert len(restarted.marks(trade["mirror_trade_id"])) == 3
    assert restarted.rows()[0]["mfe_pct"] == final["mfe_pct"]


def test_quote_unavailable_appends_null_snapshot_without_changing_excursions(tmp_path):
    repository, mirror, candidate = setup(tmp_path)
    cycle(repository, mirror, [candidate], NOW, lambda symbol: ({"bid":1,"ask":2},""))
    before = mirror.rows()[0]
    cycle(repository, mirror, [], NOW + timedelta(minutes=1),
          lambda symbol: (None,"temporary failure"))
    after = mirror.rows()[0]
    unavailable = mirror.marks(after["mirror_trade_id"])[-1]
    assert unavailable["update_status"] == "QUOTE_UNAVAILABLE"
    assert unavailable["bid"] is None and unavailable["conservative_mark"] is None
    assert unavailable["return_pct"] is None and unavailable["unrealized_pnl"] is None
    assert after["mfe_pct"] == before["mfe_pct"] and after["mae_pct"] == before["mae_pct"]


def test_close_snapshot_and_analysis_identify_profitable_loser_giveback(tmp_path):
    repository, mirror, candidate = setup(tmp_path)
    cycle(repository, mirror, [candidate], NOW, lambda symbol: ({"bid":2,"ask":3},""))
    repository.record_trade_event(dedup_key="close", opportunity_id="auth-1", trade_id="auth-1",
        symbol="SPY", event_type="TRADE_CLOSED", event_timestamp=NOW+timedelta(minutes=2),
        description="closed", direction="Bullish", exit_price=101,
        realized_return=1, exit_reason="TARGET_1")
    cycle(repository, mirror, [], NOW+timedelta(minutes=2),
          lambda symbol: ({"bid":1,"ask":1.5},""))
    row = mirror.rows()[0]
    marks = mirror.marks(row["mirror_trade_id"])
    audit = build_session_audit(repository.list_trade_events(limit=100),
        repository.list_opportunities(limit=100), [row], [], [],
        session_date=date(2026,8,7), mirror_marks=marks)
    result = audit["trades"][0]
    assert marks[-1]["update_status"] == "CLOSED"
    assert result["peak_option_return_percent"] > 0
    assert result["option_return_percent"] < 0
    assert result["final_loser_was_previously_profitable"] is True
    assert result["favorable_excursion_given_back_percent"] == pytest.approx(
        result["peak_option_return_percent"] - result["option_return_percent"])
    assert result["time_to_peak_minutes"] == 0
    assert result["time_peak_to_exit_minutes"] == 2


def test_one_existing_quote_call_per_position_and_compact_event(tmp_path, caplog):
    repository, mirror, candidate = setup(tmp_path)
    calls = []
    def quote(symbol):
        calls.append(symbol); return {"bid":1,"ask":2}, ""
    with caplog.at_level(logging.INFO):
        cycle(repository, mirror, [candidate], NOW, quote)
    assert calls == ["SPY260814C00100000"]
    events = [json.loads(record.message) for record in caplog.records
              if record.message.startswith("{") and "mirror_position_marked" in record.message]
    assert len(events) == 1
    assert events[0]["trade_id"] == mirror.rows()[0]["mirror_trade_id"]
    assert "mark" in events[0] and "mfe_pct" in events[0]


def test_migration_is_additive_and_idempotent(tmp_path):
    repository, mirror, _ = setup(tmp_path)
    MirrorExecutionRepository(repository)
    with repository.connection() as connection:
        tables = {row["name"] for row in repository._fetchall(connection,
            "SELECT name FROM sqlite_master WHERE type='table'")}
        columns = {row["name"] for row in repository._fetchall(connection,
            "PRAGMA table_info(mirror_execution_trades)")}
    assert "mirror_execution_marks" in tables
    assert {"mfe_pct","mae_pct","peak_return_pct","peak_unrealized_pnl"} <= columns
