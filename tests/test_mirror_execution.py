from datetime import datetime, timedelta, timezone

import pytest

from mirror_execution import (
    MIRROR_FILL_MODEL,
    MirrorExecutionRepository,
    mirror_enabled,
    mirror_summary,
    pending_mirror_entries,
    run_mirror_execution,
)
from paper_execution_repository import PaperExecutionRepository
from paper_trading_page import mirror_status_model, portfolio_comparison
from trade_repository import TradeRepository


NOW = datetime(2026, 8, 5, 15, 0, tzinfo=timezone.utc)


class ChainProvider:
    def expirations(self, ticker):
        return ["2026-08-14"], ""

    def chain(self, ticker, expiration):
        return [{
            "symbol": f"{ticker}260814C00100000", "option_type": "call",
            "expiration": expiration, "strike": 100, "bid": 1.0, "ask": 2.0,
            "open_interest": 0, "volume": 0, "delta": .5,
        }], ""


def repository(tmp_path):
    return TradeRepository(tmp_path / "mirror.db", database_url="")


def entry(repo, identity="auth-1", at=None):
    at = at or NOW - timedelta(minutes=1)
    repo.create_opportunity(
        opportunity_id=identity, idempotency_key=f"opportunity-{identity}", symbol="SPY",
        direction="Bullish", playbook="Breakout", signal_timestamp=at,
        source_version="test", entry_reference=100,
    )
    repo.open_trade(identity, trade_id=identity, opened_at=at, entry_price=100)
    return repo.record_trade_event(
        dedup_key=f"entry-{identity}", opportunity_id=identity, trade_id=identity,
        symbol="SPY", event_type="TRADE_ENTERED", event_timestamp=at,
        description="entered", direction="Bullish", entry_price=100,
    )


def close(repo, identity="auth-1", at=None):
    return repo.record_trade_event(
        dedup_key=f"close-{identity}", opportunity_id=identity, trade_id=identity,
        symbol="SPY", event_type="TRADE_CLOSED", event_timestamp=at or NOW,
        description="closed", direction="Bullish", exit_price=101,
        realized_return=1, exit_reason="TARGET_1",
    )


def candidate(identity="auth-1"):
    return {"_authoritative_entry_id": identity, "symbol": "SPY", "price": 100,
            "score": 1, "bias": "Bullish", "trade_plan": {"direction": "Bullish"}}


def test_enabled_is_explicit_and_defaults_false():
    assert mirror_enabled({}) is False
    assert mirror_enabled({"OPTIONBEACON_MIRROR_ENABLED": " BROAD "}) is False
    assert mirror_enabled({"OPTIONBEACON_MIRROR_ENABLED": " TRUE "}) is True


def test_every_entry_gets_one_contract_without_broad_risk_gates(tmp_path):
    repo = repository(tmp_path)
    mirror = MirrorExecutionRepository(repo)
    candidates = []
    for index in range(30):
        identity = f"auth-{index}"
        entry(repo, identity)
        candidates.append(candidate(identity))
    result = run_mirror_execution(
        repo, mirror, candidates, enabled=True, scanner_id="worker", now=NOW,
        chain_provider=ChainProvider(), quote_provider=lambda symbol: ({"bid": 1, "ask": 2}, ""),
    )
    assert result["opened"] == 30
    assert all(row["quantity"] == 1 for row in mirror.rows())
    assert all(row["entry_fill"] == pytest.approx(1.625) for row in mirror.rows())
    assert all(row["fill_model"] == MIRROR_FILL_MODEL for row in mirror.rows())
    assert all(row["open_interest"] == 0 and row["spread_percent"] > 20 for row in mirror.rows())


def test_invalid_quote_is_explicit_and_duplicate_safe_after_restart(tmp_path):
    repo = repository(tmp_path)
    entry(repo)
    broken = ChainProvider()
    broken.chain = lambda ticker, expiration: ([{
        "symbol": "SPYBAD", "option_type": "call", "expiration": expiration,
        "strike": 100, "bid": 3, "ask": 2,
    }], "")
    mirror = MirrorExecutionRepository(repo)
    for _ in range(2):
        run_mirror_execution(repo, MirrorExecutionRepository(repo), [candidate()], enabled=True,
                             scanner_id="worker", now=NOW, chain_provider=broken,
                             quote_provider=lambda symbol: (None, "unused"))
    rows = mirror.rows()
    assert len(rows) == 1
    assert rows[0]["disposition_code"] == "MIRROR_NO_VALID_CONTRACT"


def test_stale_entry_is_disposition_not_silent(tmp_path):
    repo = repository(tmp_path)
    entry(repo, at=NOW - timedelta(minutes=61))
    mirror = MirrorExecutionRepository(repo)
    run_mirror_execution(repo, mirror, [candidate()], enabled=True, scanner_id="worker",
                         now=NOW, chain_provider=ChainProvider())
    assert mirror.rows()[0]["disposition_code"] == "MIRROR_STALE_ENTRY"


def test_malformed_authoritative_payload_gets_explicit_disposition(tmp_path):
    repo = repository(tmp_path)
    event = entry(repo)
    mirror = MirrorExecutionRepository(repo)
    candidates = pending_mirror_entries(repo, {}, mirror)
    assert len(candidates) == 1
    run_mirror_execution(repo, mirror, candidates, enabled=True, scanner_id="worker", now=NOW,
                         chain_provider=ChainProvider())
    assert mirror.rows()[0]["disposition_code"] == "MIRROR_AUTHORITATIVE_DATA_FAILURE"


def test_authoritative_exit_controls_close_and_failure_stays_pending(tmp_path):
    repo = repository(tmp_path)
    entry(repo)
    mirror = MirrorExecutionRepository(repo)
    run_mirror_execution(repo, mirror, [candidate()], enabled=True, scanner_id="worker", now=NOW,
                         chain_provider=ChainProvider(), quote_provider=lambda symbol: ({"bid": 1, "ask": 2}, ""))
    close(repo, at=NOW + timedelta(minutes=20))
    run_mirror_execution(repo, mirror, [], enabled=True, scanner_id="worker", now=NOW + timedelta(minutes=20),
                         quote_provider=lambda symbol: (None, "temporary provider failure"))
    pending = mirror.rows()[0]
    assert pending["status"] == "EXIT_PENDING"
    assert pending["exit_fill"] is None
    assert pending["authoritative_exit_at"] == (NOW + timedelta(minutes=20)).isoformat()
    run_mirror_execution(repo, MirrorExecutionRepository(repo), [], enabled=True, scanner_id="worker",
                         now=NOW + timedelta(minutes=21), quote_provider=lambda symbol: ({"bid": 2, "ask": 3}, ""))
    closed = mirror.rows()[0]
    assert closed["status"] == "CLOSED"
    assert closed["exit_fill"] == pytest.approx(2.375)
    assert closed["realized_pnl"] == pytest.approx(75)
    assert closed["authoritative_exit_reason"] == "TARGET_1"


def test_broad_and_mirror_have_separate_tables_for_same_authoritative_id(tmp_path):
    repo = repository(tmp_path)
    broad = PaperExecutionRepository(repo)
    mirror = MirrorExecutionRepository(repo)
    entry(repo)
    run_mirror_execution(repo, mirror, [candidate()], enabled=True, scanner_id="worker", now=NOW,
                         chain_provider=ChainProvider(), quote_provider=lambda symbol: ({"bid": 1, "ask": 2}, ""))
    assert mirror.get("auth-1") is not None
    assert broad.counts() == {"positions": 0, "trades": 0, "journal": 0}


def test_summary_capital_pnl_drawdown_and_read_only_models(tmp_path):
    repo = repository(tmp_path)
    mirror = MirrorExecutionRepository(repo)
    for index in range(2):
        identity = f"auth-{index}"
        entry(repo, identity, NOW + timedelta(minutes=index))
        run_mirror_execution(repo, mirror, [candidate(identity)], enabled=True, scanner_id="worker",
                             now=NOW + timedelta(minutes=index), chain_provider=ChainProvider(),
                             quote_provider=lambda symbol: ({"bid": 1, "ask": 2}, ""))
    assert mirror_summary(mirror.rows())["peak_capital_required"] == pytest.approx(325)
    assert mirror_status_model({"enabled": 1, "status": "ACTIVE"})["label"] == "MIRROR ACTIVE"
    assert mirror_status_model(None)["label"] == "MIRROR WAITING"


def test_comparison_preserves_underlying_vs_option_units(tmp_path):
    repo = repository(tmp_path)
    entered = entry(repo)
    exited = close(repo)
    comparison = portfolio_comparison([entered, exited], [], [], [], [{
        "opportunity_id": "auth-1", "opened_at": NOW.isoformat(), "option_symbol": "SPY_CALL",
        "disposition_code": "MIRROR_CLOSED", "realized_pnl": 50,
    }])
    assert comparison["trades"][0]["Auth Return (underlying %)"] == 1
    assert comparison["trades"][0]["MIRROR Option P&L ($)"] == 50
    assert comparison["metrics"][-1]["OptionBeacon"] == "N/A — underlying %"


def test_source_contains_no_broker_order_path():
    source = open("mirror_execution.py", encoding="utf-8").read().lower()
    assert "place_order" not in source
    assert "submit_order" not in source
    assert "robinhood" not in source
