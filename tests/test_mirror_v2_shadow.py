from datetime import datetime, timedelta, timezone

import pytest

from mirror_execution import MirrorExecutionRepository, run_mirror_execution
from mirror_v2_shadow import (
    CachedChainProvider,
    MirrorV2Repository,
    evaluate_v2_contracts,
    mirror_v2_enabled,
    run_mirror_v2_shadow,
)
from trade_repository import TradeRepository


NOW = datetime(2026, 8, 10, 15, 0, tzinfo=timezone.utc)


def repo(tmp_path):
    return TradeRepository(tmp_path / "v2.db", database_url="")


def add_entry(repository, identity="auth-1"):
    at = NOW - timedelta(minutes=1)
    repository.create_opportunity(
        opportunity_id=identity, idempotency_key=f"op-{identity}", symbol="SPY",
        direction="Bullish", playbook="Breakout", signal_timestamp=at,
        source_version="test", entry_reference=100,
    )
    repository.open_trade(identity, trade_id=identity, opened_at=at, entry_price=100)
    return repository.record_trade_event(
        dedup_key=f"entry-{identity}", opportunity_id=identity, trade_id=identity,
        symbol="SPY", event_type="TRADE_ENTERED", event_timestamp=at,
        description="entered", direction="Bullish", entry_price=100,
    )


def candidate(identity="auth-1"):
    return {"_authoritative_entry_id": identity, "symbol": "SPY", "price": 100,
            "bias": "Bullish", "trade_plan": {"direction": "Bullish"}}


class Provider:
    def __init__(self, contracts):
        self.contracts = contracts
        self.expiration_calls = self.chain_calls = 0

    def expirations(self, _ticker):
        self.expiration_calls += 1
        return ["2026-08-21"], ""

    def chain(self, _ticker, _expiration):
        self.chain_calls += 1
        return self.contracts, ""


def contract(symbol="SPY_ATM", strike=100, bid=0.95, ask=1.05, oi=100):
    return {"symbol": symbol, "option_type": "call", "expiration": "2026-08-21",
            "strike": strike, "bid": bid, "ask": ask, "open_interest": oi, "volume": 10}


def test_v2_flag_is_explicit_and_defaults_off():
    assert mirror_v2_enabled({}) is False
    assert mirror_v2_enabled({"OPTIONBEACON_MIRROR_V2_SHADOW_ENABLED": "true"}) is True


def test_v2_selects_best_eligible_alternative_not_control_contract():
    provider = Provider([
        contract("WIDE_ATM", bid=.80, ask=1.20, oi=1000),
        contract("LIQUID_ATM", bid=.95, ask=1.05, oi=200),
        contract("FAR", strike=102, bid=.98, ask=1.02, oi=5000),
    ])
    evaluation = evaluate_v2_contracts(candidate(), {"event_timestamp": NOW}, provider, NOW)
    assert evaluation["decision"] == "TAKE"
    assert evaluation["selected"]["option_symbol"] == "LIQUID_ATM"
    assert len(evaluation["considered"]) == 3


@pytest.mark.parametrize("contracts,reason", [
    ([contract(bid=None, ask=1.0)], "MISSING_OR_UNRELIABLE_BID_ASK"),
    ([contract(strike=101)], "NO_NEAR_ATM_CONTRACT"),
    ([contract(bid=.80, ask=1.20)], "SPREAD_ABOVE_12_5_PERCENT"),
])
def test_v2_fails_closed_with_exact_rejection_reason(contracts, reason):
    result = evaluate_v2_contracts(candidate(), {"event_timestamp": NOW}, Provider(contracts), NOW)
    assert result["decision"] == "REJECT"
    assert result["reasons"] == [reason]


def test_independent_ledger_exact_ids_restart_recovery_and_control_unchanged(tmp_path):
    repository = repo(tmp_path)
    add_entry(repository)
    control = MirrorExecutionRepository(repository)
    v2 = MirrorV2Repository(repository)
    provider = Provider([contract()])
    shared = CachedChainProvider(provider)
    run_mirror_execution(repository, control, [candidate()], enabled=True, scanner_id="worker",
                         now=NOW, chain_provider=shared,
                         quote_provider=lambda _symbol: ({"bid": 1, "ask": 1.1}, ""))
    for _ in range(2):
        run_mirror_v2_shadow(repository, MirrorV2Repository(repository), [candidate()],
                             enabled=True, scanner_id="worker", now=NOW,
                             chain_provider=shared, quote_provider=lambda _symbol: ({"bid": .95, "ask": 1.05}, ""),
                             control_repository=control)
    assert len(v2.rows()) == 1
    assert v2.rows()[0]["opportunity_id"] == "auth-1"
    assert len(control.rows()) == 1
    assert control.rows()[0]["disposition_code"] == "MIRROR_OPENED"
    assert provider.expiration_calls == provider.chain_calls == 1
    assert v2.comparisons()[0]["control_contract"] == "SPY_ATM"


def test_target_and_stop_are_independent_and_never_execute_live(tmp_path):
    repository = repo(tmp_path)
    add_entry(repository, "target")
    add_entry(repository, "stop")
    v2 = MirrorV2Repository(repository)
    # Persisted rows are deterministically ordered by opportunity ID: stop, then target.
    quotes = iter([({"bid": .80, "ask": .82}, ""), ({"bid": 1.20, "ask": 1.22}, "")])
    run_mirror_v2_shadow(repository, v2, [candidate("target"), candidate("stop")],
                         enabled=True, scanner_id="worker", now=NOW,
                         chain_provider=Provider([contract()]), quote_provider=lambda _symbol: next(quotes))
    rows = {row["opportunity_id"]: row for row in v2.rows()}
    assert rows["target"]["exit_reason"] == "TARGET_10"
    assert rows["stop"]["exit_reason"] == "STOP_10"
    assert rows["target"]["status"] == rows["stop"]["status"] == "CLOSED"
    source = open("mirror_v2_shadow.py", encoding="utf-8").read().lower()
    assert "place_order" not in source and "submit_order" not in source


def test_forward_start_does_not_rewrite_historical_opportunities(tmp_path):
    repository = repo(tmp_path)
    add_entry(repository)
    v2 = MirrorV2Repository(repository)
    result = run_mirror_v2_shadow(
        repository, v2, [candidate()], enabled=True, scanner_id="worker", now=NOW,
        experiment_start_date=(NOW + timedelta(days=1)).date(),
        chain_provider=Provider([contract()]),
    )
    assert result["taken"] == result["rejected"] == 0
    assert v2.rows() == []
    assert v2.runtime_state()["experiment_start_date"] == "2026-08-11"
