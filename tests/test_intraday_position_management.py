import json
import logging
from datetime import date, datetime, timedelta, timezone

import pytest

import optionbeacon.worker.intraday as worker
from intraday_execution import IntradayRepository
from intraday_strategy import Candidate
from trade_repository import TradeRepository


NOW = datetime(2026, 8, 7, 18, 0, tzinfo=timezone.utc)  # 14:00 ET


def tape(symbol="SPY", *, bearish=False):
    start = NOW - timedelta(minutes=30)
    rows = []
    for index in range(30):
        price = (600 - index * .15) if bearish else (600 + index * .15)
        rows.append({"timestamp": start + timedelta(minutes=index), "open": price,
                     "high": price + .08, "low": price - .08, "close": price,
                     "volume": 1000 + index})
    return rows


def candidate(opportunity_id="opp", symbol="SPY"):
    return Candidate(opportunity_id, symbol, "CALL", "VWAP RECLAIM", 78, 600, 600.1,
                     NOW - timedelta(minutes=1), "AFTERNOON", "TRENDING UP")


def contract(symbol="SPY0"):
    return {"option_symbol": symbol, "symbol": symbol, "expiration": date(2026, 8, 7).isoformat(),
            "dte": 0, "option_type": "call", "strike": 600, "bid": 1, "ask": 1.10,
            "delta": .52, "volume": 5000, "open_interest": 10000, "spread_pct": 9.5}


def opened_ledger(tmp_path, *, opened_at=NOW, opportunity_id="opp"):
    repository = TradeRepository(tmp_path / "state.db")
    ledger = IntradayRepository(repository)
    setup = candidate(opportunity_id)
    ledger.save_signal(setup)
    ledger.transition_signal(opportunity_id, "ARMED", "TRIGGERED", now=opened_at)
    ledger.open_variants(setup, contract(), now=opened_at)
    ledger.transition_signal(opportunity_id, "TRIGGERED", "PAPER_OPENED", now=opened_at)
    return repository, ledger


def run(repository, monkeypatch, quote, *, now=NOW, bars=None):
    monkeypatch.setattr(worker, "detect_candidate", lambda *args, **kwargs: None)
    bars = bars or {"SPY": tape(), "QQQ": tape("QQQ")}
    return worker.run_intraday_cycle(
        repository, now=now,
        bar_provider=lambda symbol, **kwargs: bars[symbol],
        quote_provider=lambda symbol: quote,
    )


def test_mirror_closes_on_underlying_reversal_managed_remains_isolated(tmp_path, monkeypatch):
    repository, ledger = opened_ledger(tmp_path)
    assert run(repository, monkeypatch, {"bid": 1.05, "ask": 1.07},
               bars={"SPY": tape(bearish=True), "QQQ": tape("QQQ")}) == 0
    rows = ledger.list_trades()
    mirror = next(row for row in rows if row["variant"] == "INTRADAY_MIRROR")
    managed = next(row for row in rows if row["variant"] == "INTRADAY_MANAGED")
    assert mirror["status"] == "CLOSED" and mirror["exit_reason"] == "UNDERLYING_SIGNAL_CLOSED"
    assert managed["status"] == "OPEN"


def test_managed_hard_stop_closes_without_closing_mirror(tmp_path, monkeypatch):
    repository, ledger = opened_ledger(tmp_path)
    run(repository, monkeypatch, {"bid": .70, "ask": .72})
    rows = ledger.list_trades()
    managed = next(row for row in rows if row["variant"] == "INTRADAY_MANAGED")
    mirror = next(row for row in rows if row["variant"] == "INTRADAY_MIRROR")
    assert managed["status"] == "CLOSED" and managed["exit_reason"] == "HARD_STOP"
    assert mirror["status"] == "OPEN"


def test_profit_protection_trailing_and_giveback_persist_across_restart(tmp_path, monkeypatch, caplog):
    repository, ledger = opened_ledger(tmp_path)
    with caplog.at_level(logging.INFO):
        run(repository, monkeypatch, {"bid": 1.34, "ask": 1.36})
    managed = next(row for row in ledger.list_trades() if row["variant"] == "INTRADAY_MANAGED")
    assert managed["protection_armed"] == 1 and managed["trailing_active"] == 1
    assert managed["peak_return_pct"] >= 25 and managed["management_state"] == "TRAILING"
    events = [json.loads(record.message).get("event") for record in caplog.records if record.message.startswith("{")]
    assert "intraday_profit_protection_armed" in events
    assert "intraday_trailing_activated" in events
    # A new repository wrapper models a Railway process restart.
    restarted = IntradayRepository(repository)
    run(repository, monkeypatch, {"bid": 1.20, "ask": 1.22}, now=NOW + timedelta(minutes=1))
    closed = restarted.trade(managed["trade_id"])
    assert closed["status"] == "CLOSED" and closed["exit_reason"] == "TRAILING_STOP"
    assert closed["profit_giveback_pct"] >= 10


@pytest.mark.parametrize("minutes,now,reason", [
    (46, NOW, "MAX_HOLD"),
    (1, datetime(2026, 8, 7, 19, 55, tzinfo=timezone.utc), "EOD_CLOSE"),
])
def test_managed_time_exits(tmp_path, monkeypatch, minutes, now, reason):
    repository, ledger = opened_ledger(tmp_path, opened_at=now - timedelta(minutes=minutes))
    run(repository, monkeypatch, {"bid": 1.04, "ask": 1.06}, now=now)
    managed = next(row for row in ledger.list_trades() if row["variant"] == "INTRADAY_MANAGED")
    assert managed["status"] == "CLOSED" and managed["exit_reason"] == reason


def test_open_marks_unrealized_and_excursions_are_updated(tmp_path, monkeypatch):
    repository, ledger = opened_ledger(tmp_path)
    run(repository, monkeypatch, {"bid": 1.12, "ask": 1.14})
    rows = ledger.list_trades(status="OPEN")
    assert all(row["current_mark"] == pytest.approx(1.1275) for row in rows)
    assert all(row["unrealized_pnl"] == pytest.approx(6.5) for row in rows)
    assert all(row["mfe_pct"] > 0 and row["mae_pct"] == 0 for row in rows)


def test_unavailable_quote_never_closes_or_fabricates_and_retries(tmp_path, monkeypatch):
    repository, ledger = opened_ledger(tmp_path)
    run(repository, monkeypatch, (None, "provider unavailable"))
    rows = ledger.list_trades()
    assert all(row["status"] == "OPEN" for row in rows)
    assert all(row["exit_fill"] is None and row["update_status"] == "QUOTE_UNAVAILABLE" for row in rows)
    run(repository, monkeypatch, {"bid": 1.04, "ask": 1.06}, now=NOW + timedelta(minutes=1))
    assert all(row["update_status"] == "CURRENT" for row in ledger.list_trades())


def test_duplicate_cycles_do_not_duplicate_open_or_close(tmp_path, monkeypatch):
    repository, ledger = opened_ledger(tmp_path)
    run(repository, monkeypatch, {"bid": .70, "ask": .72})
    first = ledger.list_trades()
    realized = next(row["realized_pnl"] for row in first if row["variant"] == "INTRADAY_MANAGED")
    run(repository, monkeypatch, {"bid": .60, "ask": .62}, now=NOW + timedelta(minutes=1))
    second = ledger.list_trades()
    assert len(second) == 2
    assert next(row["realized_pnl"] for row in second if row["variant"] == "INTRADAY_MANAGED") == realized


def test_management_precedes_both_symbol_evaluations_and_runtime_persists(tmp_path, monkeypatch, caplog):
    repository, ledger = opened_ledger(tmp_path)
    with caplog.at_level(logging.INFO):
        run(repository, monkeypatch, {"bid": 1.04, "ask": 1.06})
    events = [json.loads(record.message) for record in caplog.records if record.message.startswith("{")]
    names = [row.get("event") for row in events]
    assert names.index("intraday_position_updated") < names.index("intraday_symbol_evaluated")
    evaluated = [row["symbol"] for row in events if row.get("event") == "intraday_symbol_evaluated"]
    assert evaluated == ["SPY", "QQQ"]
    state = ledger.runtime_state()
    assert state["status"] == "HEALTHY" and state["symbols_processed"] == 2


def test_detected_setup_persists_detected_then_armed_and_emits_both_events(tmp_path, monkeypatch, caplog):
    repository = TradeRepository(tmp_path / "state.db")
    setup = candidate("detected")
    monkeypatch.setattr(worker, "detect_candidate",
                        lambda symbol, *args, **kwargs: setup if symbol == "SPY" else None)
    with caplog.at_level(logging.INFO):
        worker.run_intraday_cycle(repository, now=NOW,
            bar_provider=lambda symbol, **kwargs: tape(symbol),
            quote_provider=lambda symbol: {"bid": 1, "ask": 1.02})
    ledger = IntradayRepository(repository)
    assert ledger.signal("detected")["state"] == "ARMED"
    names = [json.loads(record.message).get("event") for record in caplog.records
             if record.message.startswith("{")]
    assert names.index("intraday_setup_detected") < names.index("intraday_setup_armed")


def test_schema_upgrade_is_idempotent(tmp_path):
    repository = TradeRepository(tmp_path / "state.db")
    IntradayRepository(repository)
    IntradayRepository(repository)
    with repository.connection() as connection:
        columns = {row["name"] for row in repository._fetchall(
            connection, "PRAGMA table_info(intraday_paper_trades)")}
    assert {"current_value", "unrealized_pnl", "peak_return_pct", "last_quote_at",
            "update_status", "last_update_error"} <= columns


def test_eod_quote_failure_stays_explicitly_open(tmp_path, monkeypatch):
    now = datetime(2026, 8, 7, 19, 55, tzinfo=timezone.utc)
    repository, ledger = opened_ledger(tmp_path, opened_at=now - timedelta(minutes=1))
    run(repository, monkeypatch, (None, "provider unavailable"), now=now)
    assert all(row["status"] == "OPEN" and row["update_status"] == "QUOTE_UNAVAILABLE"
               for row in ledger.list_trades())
