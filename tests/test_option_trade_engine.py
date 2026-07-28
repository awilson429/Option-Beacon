import json
from dataclasses import FrozenInstanceError
from datetime import date, datetime, timezone

import pytest

from option_trade_engine import (
    OptionTradeLedger,
    capture_qualified_signal,
    normalized_contracts,
    preferred_expiration,
    select_contract,
)


NOW = datetime(2026, 7, 29, 14, 0, tzinfo=timezone.utc)  # Wednesday


def signal(**overrides):
    value = {
        "symbol": "SPY",
        "bias": "Bullish",
        "signal": "BULLISH SETUP",
        "confidence": 80,
        "score": 82,
        "timestamp": NOW.isoformat(),
        "setup_stage": "Armed",
        "entry_timing": "Watch closely",
        "entry_timing_reason": "Watch the trigger.",
        "price": 100,
        "trade_plan": {
            "direction": "Bullish",
            "setup_type": "Breakout",
            "trigger_price": 100,
            "technical_stop": 95,
            "target_1": 105,
        },
    }
    value.update(overrides)
    return value


def contract(
    *,
    symbol="SPY260731C00100000",
    option_type="call",
    expiration="2026-07-31",
    strike=100,
    bid=2,
    ask=2.2,
    delta=0.5,
    open_interest=100,
    volume=50,
):
    return {
        "symbol": symbol,
        "option_type": option_type,
        "expiration_date": expiration,
        "strike": strike,
        "bid": bid,
        "ask": ask,
        "greeks": {"delta": delta, "mid_iv": 0.25},
        "open_interest": open_interest,
        "volume": volume,
    }


class Provider:
    def __init__(self, contracts=None, *, error="", expirations=None):
        self.contracts = [contract()] if contracts is None else contracts
        self.error = error
        self.listed = (
            ["2026-07-31", "2026-08-07"]
            if expirations is None
            else expirations
        )
        self.expiration_calls = 0
        self.chain_calls = 0

    def expirations(self, ticker):
        self.expiration_calls += 1
        return ([], self.error) if self.error else (self.listed, "")

    def chain(self, ticker, expiration):
        self.chain_calls += 1
        return self.contracts, ""


def test_canonical_eligibility_integration_and_ineligible_exclusions(tmp_path):
    provider = Provider()
    repository = OptionTradeLedger(tmp_path / "ledger.jsonl")
    assert capture_qualified_signal(
        signal(confidence=45), repository=repository, provider=provider
    ) is None
    assert capture_qualified_signal(
        signal(watch_only=True), repository=repository, provider=provider
    ) is None
    assert capture_qualified_signal(
        signal(entry_time=NOW.isoformat(), exit_time=NOW.isoformat()),
        repository=repository,
        provider=provider,
    ) is None
    assert provider.expiration_calls == 0
    assert repository.records() == []


@pytest.mark.parametrize(
    ("direction", "option_type"),
    [("Bullish", "call"), ("Bearish", "put")],
)
def test_direction_selects_matching_option_type(tmp_path, direction, option_type):
    plan = signal()["trade_plan"] | {"direction": direction}
    result = signal(bias=direction, trade_plan=plan)
    selected = contract(option_type=option_type)
    record = capture_qualified_signal(
        result,
        repository=OptionTradeLedger(tmp_path / "ledger.jsonl"),
        provider=Provider([selected]),
        now=NOW,
    )
    assert record.option_type == option_type


def test_preferred_friday_selection_and_late_week_policy():
    listed = ["2026-07-31", "2026-08-07", "2026-08-14"]
    assert preferred_expiration(listed, date(2026, 7, 29)) == "2026-07-31"
    assert preferred_expiration(listed, date(2026, 7, 30)) == "2026-08-07"
    assert preferred_expiration(listed, date(2026, 7, 31)) == "2026-08-07"


def test_missing_preferred_friday_uses_next_listed_expiration():
    assert preferred_expiration(
        ["2026-08-03", "2026-08-10"], date(2026, 7, 29)
    ) == "2026-08-03"


def test_delta_closest_to_half_wins_deterministically():
    selected = select_contract(
        [
            contract(symbol="A", strike=99, delta=0.40),
            contract(symbol="B", strike=101, delta=0.51),
        ],
        option_type="call",
        underlying_price=100,
    )
    assert selected["option_symbol"] == "B"


def test_missing_delta_fallback_uses_closest_strike():
    selected = select_contract(
        [
            contract(symbol="FAR", strike=105, delta=None),
            contract(symbol="ATM", strike=101, delta=None),
        ],
        option_type="call",
        underlying_price=100,
    )
    assert selected["option_symbol"] == "ATM"
    assert selected["delta"] is None


def test_spread_open_interest_volume_and_symbol_tie_breaking():
    assert select_contract(
        [
            contract(symbol="WIDE", bid=1, ask=2, delta=0.5),
            contract(symbol="TIGHT", bid=1.9, ask=2, delta=0.5),
        ],
        option_type="call",
        underlying_price=100,
    )["option_symbol"] == "TIGHT"
    assert select_contract(
        [
            contract(symbol="LOW", open_interest=10),
            contract(symbol="HIGH", open_interest=20),
        ],
        option_type="call",
        underlying_price=100,
    )["option_symbol"] == "HIGH"
    assert select_contract(
        [
            contract(symbol="LOW", volume=10),
            contract(symbol="HIGH", volume=20),
        ],
        option_type="call",
        underlying_price=100,
    )["option_symbol"] == "HIGH"
    assert select_contract(
        [contract(symbol="B"), contract(symbol="A")],
        option_type="call",
        underlying_price=100,
    )["option_symbol"] == "A"


def test_invalid_and_crossed_quotes_are_filtered():
    values = normalized_contracts(
        [
            contract(symbol="NOASK", ask=None),
            contract(symbol="ZEROASK", ask=0),
            contract(symbol="CROSSED", bid=3, ask=2),
            contract(symbol="VALID"),
            contract(symbol="PUT", option_type="put"),
        ],
        "call",
    )
    assert [item["option_symbol"] for item in values] == ["VALID"]


def test_midpoint_and_spread_percent_calculation():
    value = normalized_contracts([contract(bid=2, ask=2.2)], "call")[0]
    assert value["mid"] == pytest.approx(2.1)
    assert value["spread_percent"] == pytest.approx(0.2 / 2.1 * 100)


def test_ask_only_contract_is_honest_and_ranks_after_complete_quote():
    values = normalized_contracts([contract(bid=None, ask=2)], "call")
    assert values[0]["bid"] is None
    assert values[0]["mid"] is None
    assert values[0]["spread_percent"] is None


def test_snapshot_is_frozen_and_contains_entry_fields(tmp_path):
    record = capture_qualified_signal(
        signal(),
        repository=OptionTradeLedger(tmp_path / "ledger.jsonl"),
        provider=Provider(),
        now=NOW,
    )
    assert record.status == "QUALIFIED"
    assert record.source == "SCANNER"
    assert record.execution_type == "PAPER"
    assert record.mid == pytest.approx(2.1)
    assert record.entry_snapshot_complete is True
    with pytest.raises(FrozenInstanceError):
        record.ask = 99


def test_duplicate_prevention_same_instance_and_repository_reload(tmp_path):
    path = tmp_path / "ledger.jsonl"
    provider = Provider()
    first = capture_qualified_signal(
        signal(), repository=OptionTradeLedger(path), provider=provider, now=NOW
    )
    second = capture_qualified_signal(
        signal(), repository=OptionTradeLedger(path), provider=provider, now=NOW
    )
    assert first == second
    assert provider.expiration_calls == 1
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_separate_source_signals_same_ticker_remain_separate(tmp_path):
    path = tmp_path / "ledger.jsonl"
    repository = OptionTradeLedger(path)
    capture_qualified_signal(
        signal(timestamp="2026-07-29T14:00:00+00:00"),
        repository=repository,
        provider=Provider(),
        now=NOW,
    )
    capture_qualified_signal(
        signal(timestamp="2026-07-29T14:10:00+00:00"),
        repository=repository,
        provider=Provider(),
        now=NOW,
    )
    assert len(repository.records()) == 2


def test_append_only_and_malformed_prior_row_tolerance(tmp_path):
    path = tmp_path / "ledger.jsonl"
    path.write_text("{malformed}\n", encoding="utf-8")
    record = capture_qualified_signal(
        signal(),
        repository=OptionTradeLedger(path),
        provider=Provider(),
        now=NOW,
    )
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "{malformed}"
    assert json.loads(lines[1])["trade_id"] == record.trade_id
    assert len(OptionTradeLedger(path).records()) == 1


@pytest.mark.parametrize(
    ("provider", "expected_reason"),
    [
        (Provider(error="TRADIER_ACCESS_TOKEN is not configured."), "credentials"),
        (Provider(contracts=[]), "No valid option contract"),
        (Provider(expirations=[]), "No listed expiration"),
    ],
)
def test_data_unavailable_is_persisted_once_without_crashing(
    tmp_path, provider, expected_reason
):
    path = tmp_path / "ledger.jsonl"
    repository = OptionTradeLedger(path)
    first = capture_qualified_signal(
        signal(), repository=repository, provider=provider, now=NOW
    )
    second = capture_qualified_signal(
        signal(), repository=OptionTradeLedger(path), provider=provider, now=NOW
    )
    assert first.status == "DATA_UNAVAILABLE"
    assert first.entry_snapshot_complete is False
    assert expected_reason.lower() in first.data_unavailable_reason.lower()
    assert second == first
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_provider_exception_does_not_escape(tmp_path):
    class BrokenProvider:
        def expirations(self, ticker):
            raise RuntimeError("secret response")

    record = capture_qualified_signal(
        signal(),
        repository=OptionTradeLedger(tmp_path / "ledger.jsonl"),
        provider=BrokenProvider(),
        now=NOW,
    )
    assert record.status == "DATA_UNAVAILABLE"
    assert record.data_unavailable_reason == "Option-chain provider unavailable."


def test_capture_does_not_mutate_history_or_backup_files(tmp_path):
    history = tmp_path / "signal_history.jsonl"
    backup = tmp_path / "signal_history.backup.jsonl"
    history.write_text("active-history\n", encoding="utf-8")
    backup.write_text("backup-history\n", encoding="utf-8")
    capture_qualified_signal(
        signal(),
        repository=OptionTradeLedger(tmp_path / "paper_option_trades.jsonl"),
        provider=Provider(),
        now=NOW,
    )
    assert history.read_text(encoding="utf-8") == "active-history\n"
    assert backup.read_text(encoding="utf-8") == "backup-history\n"
