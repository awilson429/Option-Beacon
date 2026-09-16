import inspect
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

import paper_execution
import translation_research
from execution_config import ExecutionConfig
from option_position_tracker import OptionPositionStore, position_from_trade
from option_trade_engine import PaperOptionTrade
from paper_execution import pending_authoritative_entries, refresh_paper_positions, run_paper_execution
from paper_execution_repository import PaperExecutionRepository
from signal_history import TradeOutcome
from trade_repository import TradeRepository
from trade_state_service import process_scanner_result, sync_trade_outcome
from translation_research import (
    CAPTURE_PRODUCTION_FILL,
    CAPTURE_TRADE_ENTERED,
    OBSERVATION_SAME_CAPTURE,
    RESEARCH_VERSION,
    RESULT_CHAIN_EMPTY,
    RESULT_NO_ELIGIBLE_CONTRACT,
    RESULT_NOT_REQUESTED_BY_PRODUCTION,
    RESULT_PROVIDER_FAILURE,
    _optional_float,
    build_mark_record,
    record_trade_entered_capture,
    translation_research_enabled,
)
from translation_research_repository import TranslationResearchRepository


NOW = datetime(2026, 8, 4, 14, 35, tzinfo=timezone.utc)


def authoritative_record(trade_id="entry-1", entry=100.0):
    return TradeOutcome(
        trade_id=trade_id,
        timestamp=NOW - timedelta(minutes=10),
        symbol="ABNB",
        direction="Bearish",
        setup="Breakdown",
        confidence=80,
        entry=entry,
        stop=102,
        target_1=98,
        target_2=96,
        target_3=None,
        entry_time=NOW - timedelta(minutes=6),
        exit_time=None,
        exit_reason=None,
        max_favorable_excursion=None,
        max_adverse_excursion=None,
        realized_return=None,
        hold_minutes=None,
    )


def scan_result(score=95):
    return {
        "symbol": "ABNB",
        "price": 99.9,
        "score": score,
        "confidence": 10,
        "signal": "WAIT",
        "entry_timing": "WAIT",
        "timestamp": NOW.isoformat(),
    }


class CountingProvider:
    def __init__(self, contracts=None, *, error="", expirations=None):
        self.contracts = contracts if contracts is not None else [{
            "option_type": "put",
            "expiration_date": "2026-08-14",
            "strike": 100,
            "symbol": "ABNB260814P00100000",
            "bid": 0.95,
            "ask": 1.05,
            "last": 1.0,
            "delta": -0.5,
            "open_interest": 500,
            "volume": 100,
            "implied_volatility": 0.3,
            "bidsize": 10,
            "asksize": 12,
            "greeks": {"delta": -0.5, "mid_iv": 0.3, "gamma": 0.02, "theta": -0.04},
        }]
        self.error = error
        self.listed = ["2026-08-14"] if expirations is None else expirations
        self.expiration_calls = 0
        self.chain_calls = 0
        self.underlying_calls = 0

    def expirations(self, ticker):
        self.expiration_calls += 1
        if self.error:
            return None, self.error
        return self.listed, None

    def chain(self, ticker, expiration):
        self.chain_calls += 1
        if self.error:
            return None, self.error
        return self.contracts, None


class Quotes:
    def __init__(self, payload=None, error=None):
        self.payload = payload if payload is not None else {
            "bid": 1.1, "ask": 1.3, "last": 1.2, "volume": 9, "open_interest": 40,
            "underlying": 99.5, "trade_date": "2026-08-04T14:34:00",
        }
        self.error = error
        self.calls = 0
        self.underlying_calls = 0

    def quote(self, option_symbol):
        self.calls += 1
        if self.error:
            return None, self.error
        return self.payload, None


class ExplodingResearch:
    def __init__(self, *, on_capture=None, on_mark=None):
        self.on_capture = on_capture or (lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("research down")))
        self.on_mark = on_mark or (lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("mark down")))

    def get_capture(self, *args, **kwargs):
        return None

    def record_capture(self, record):
        return self.on_capture(record)

    def record_mark(self, record):
        return self.on_mark(record)

    def opportunity_ids_for_paper_trades(self, trade_ids):
        return {}


def enabled_config(**changes):
    return replace(
        ExecutionConfig(),
        trading_enabled=True,
        max_open_positions=10,
        max_trades_per_day=10,
        min_open_interest=0,
        **changes,
    )


def entered_repository(tmp_path, records=None, score=95):
    repository = TradeRepository(tmp_path / "state.db", database_url="")
    for record in records or [authoritative_record()]:
        sync_trade_outcome(repository, record)
    process_scanner_result(repository, scan_result(score=score), current_timestamp=NOW)
    return repository


def paper_bundle(tmp_path, repository=None):
    repository = repository or entered_repository(tmp_path)
    paper = PaperExecutionRepository(repository)
    research = TranslationResearchRepository(repository)
    return repository, paper, research


def run_entered(tmp_path, *, provider=None, research=None, config=None, now=NOW):
    repository, paper, default_research = paper_bundle(tmp_path)
    candidates = pending_authoritative_entries(repository, {"ABNB": scan_result()}, paper)
    result = run_paper_execution(
        candidates,
        config=config or enabled_config(min_beacon_score=40),
        now=now,
        chain_provider=provider or CountingProvider(),
        trade_ledger=paper,
        position_store=paper,
        journal=paper,
        refreshed_positions=[],
        research_repository=default_research if research is True else research,
    )
    return repository, paper, (default_research if research is True else research), result, candidates


def test_enabled_by_default_and_can_be_disabled():
    assert translation_research_enabled({}) is True
    assert translation_research_enabled({"OPTIONBEACON_TRANSLATION_RESEARCH_ENABLED": "false"}) is False


def test_research_success_leaves_authoritative_result_unchanged(tmp_path):
    provider = CountingProvider()
    repository, paper, _, with_research, _ = run_entered(tmp_path, provider=provider, research=True)
    control_repo = entered_repository(tmp_path / "control")
    control_paper = PaperExecutionRepository(control_repo)
    control_candidates = pending_authoritative_entries(control_repo, {"ABNB": scan_result()}, control_paper)
    control = run_paper_execution(
        control_candidates,
        config=enabled_config(min_beacon_score=40),
        now=NOW,
        chain_provider=CountingProvider(),
        trade_ledger=control_paper,
        position_store=control_paper,
        journal=control_paper,
        refreshed_positions=[],
    )
    assert len(with_research["opened"]) == 1
    assert with_research["opened"][0].option_symbol == control["opened"][0].option_symbol
    assert with_research["opened"][0].paper_fill_price == control["opened"][0].paper_fill_price
    assert with_research["decisions"][0].reason == control["decisions"][0].reason
    assert paper.load()[0].option_symbol == control_paper.load()[0].option_symbol
    research = TranslationResearchRepository(repository)
    capture = research.get_capture("entry-1", CAPTURE_TRADE_ENTERED)
    fill = research.get_capture("entry-1", CAPTURE_PRODUCTION_FILL)
    assert capture["lane_role"] == "RESEARCH"
    assert capture["research_version"] == RESEARCH_VERSION
    assert capture["capture_reason"] == CAPTURE_TRADE_ENTERED
    assert fill["production_option_symbol"] == "ABNB260814P00100000"
    assert fill["production_fill"] == with_research["decisions"][0].paper_fill_price
    candidates = research.candidates(capture["capture_id"])
    assert candidates[0]["option_symbol"] == "ABNB260814P00100000"
    assert candidates[0]["bid"] == 0.95
    assert candidates[0]["ask"] == 1.05
    assert candidates[0]["mid"] == 1.0
    assert candidates[0]["delta"] == -0.5
    assert candidates[0]["dte"] == 10
    assert candidates[0]["is_selector_choice"] == 1
    assert fill["elapsed_from_trade_entered_seconds"] == 360.0
    t0_meta = json.loads(capture["metadata_json"])
    fill_meta = json.loads(fill["metadata_json"])
    assert t0_meta["observation_relation"] == OBSERVATION_SAME_CAPTURE
    assert fill_meta["observation_relation"] == OBSERVATION_SAME_CAPTURE
    assert t0_meta["payload_identity"] and t0_meta["payload_identity"] == fill_meta["payload_identity"]
    assert t0_meta["market_data_source"] == fill_meta["market_data_source"] == "PRODUCTION_CAPTURE"


def test_research_throw_leaves_authoritative_result_unchanged(tmp_path):
    _, paper, _, result, _ = run_entered(tmp_path, research=ExplodingResearch())
    assert len(result["opened"]) == 1
    assert paper.load()[0].status == "OPEN"


def test_research_database_unavailable_does_not_block_paper(tmp_path):
    class DeadRepo:
        def get_capture(self, *args, **kwargs):
            from trade_repository import RepositoryUnavailable
            raise RepositoryUnavailable("research db down")

        def record_capture(self, record):
            from trade_repository import RepositoryUnavailable
            raise RepositoryUnavailable("research db down")

    _, paper, _, result, _ = run_entered(tmp_path, research=DeadRepo())
    assert len(result["opened"]) == 1
    assert paper.journal_rows()[0]["accepted"] == 1


def test_research_cannot_replace_production_contract_selection(tmp_path):
    repository, paper, research, result, _ = run_entered(tmp_path, research=True)
    assert result["opened"][0].option_symbol == "ABNB260814P00100000"
    t0 = research.get_capture("entry-1", CAPTURE_TRADE_ENTERED)
    fill = research.get_capture("entry-1", CAPTURE_PRODUCTION_FILL)
    assert t0["selected_option_symbol"] == fill["production_option_symbol"] == "ABNB260814P00100000"
    assert paper.load()[0].option_symbol == "ABNB260814P00100000"


def test_duplicate_trade_entered_capture_is_idempotent(tmp_path):
    repository, paper, research = paper_bundle(tmp_path)
    provider = CountingProvider()
    candidates = pending_authoritative_entries(repository, {"ABNB": scan_result()}, paper)
    kwargs = dict(
        config=enabled_config(min_beacon_score=40), now=NOW, chain_provider=provider,
        trade_ledger=paper, position_store=paper, journal=paper, refreshed_positions=[],
        research_repository=research,
    )
    first = run_paper_execution(candidates, **kwargs)
    second = run_paper_execution(candidates, **kwargs)
    rows = research.captures(opportunity_id="entry-1")
    t0 = [row for row in rows if row["capture_reason"] == CAPTURE_TRADE_ENTERED]
    fill = [row for row in rows if row["capture_reason"] == CAPTURE_PRODUCTION_FILL]
    assert len(t0) == 1 and len(fill) == 1
    assert len(first["opened"]) == 1 and not second["opened"]
    assert provider.expiration_calls == 1 and provider.chain_calls == 1


def test_worker_restart_does_not_duplicate_logical_captures(tmp_path):
    repository, paper, research = paper_bundle(tmp_path)
    provider = CountingProvider()
    candidates = pending_authoritative_entries(repository, {"ABNB": scan_result()}, paper)
    run_paper_execution(
        candidates, config=enabled_config(min_beacon_score=40), now=NOW,
        chain_provider=provider, trade_ledger=paper, position_store=paper, journal=paper,
        refreshed_positions=[], research_repository=research,
    )
    restarted = PaperExecutionRepository(repository)
    leftover = pending_authoritative_entries(repository, {"ABNB": scan_result()}, restarted)
    run_paper_execution(
        leftover, config=enabled_config(min_beacon_score=40), now=NOW,
        chain_provider=CountingProvider(), trade_ledger=restarted, position_store=restarted,
        journal=restarted, refreshed_positions=restarted.load(), research_repository=research,
    )
    assert len(research.captures(opportunity_id="entry-1")) == 2
    assert leftover == []


def test_mark_recorder_failure_does_not_stop_management(tmp_path):
    repository, paper, _ = paper_bundle(tmp_path)
    opened = run_paper_execution(
        pending_authoritative_entries(repository, {"ABNB": scan_result()}, paper),
        config=enabled_config(min_beacon_score=40), now=NOW, chain_provider=CountingProvider(),
        trade_ledger=paper, position_store=paper, journal=paper, refreshed_positions=[],
    )
    refreshed = refresh_paper_positions(
        config=enabled_config(), now=NOW + timedelta(minutes=5),
        quote_provider=Quotes(), trade_ledger=paper, position_store=paper,
        research_repository=ExplodingResearch(),
    )
    assert refreshed[0].status == "OPEN"
    assert refreshed[0].current_mid == pytest.approx(1.2)
    assert opened["opened"][0].trade_id == refreshed[0].trade_id


def test_research_never_writes_authoritative_or_capital_tables():
    sources = "\n".join([
        inspect.getsource(translation_research),
        inspect.getsource(TranslationResearchRepository),
        inspect.getsource(paper_execution._record_translation_research),
        inspect.getsource(paper_execution._record_translation_research_marks),
    ]).lower()
    for forbidden in (
        "insert into authoritative_trades",
        "update authoritative_trades",
        "insert into capital_decisions",
        "update capital_decisions",
        "sync_paper_positions",
        "evaluate_capital_candidate",
        "insert into paper_execution_trades",
        "insert into paper_execution_positions",
    ):
        assert forbidden not in sources


def test_capture_integrity_and_nulls_are_not_faked(tmp_path):
    assert _optional_float(None) is None
    assert _optional_float("") is None
    assert _optional_float(0) == 0.0
    contracts = [{
        "option_type": "put",
        "expiration_date": "2026-08-14",
        "strike": 100,
        "symbol": "ABNB260814P00100000",
            "bid": None,
            "ask": None,
            "delta": None,
        "open_interest": 500,
        "volume": None,
    }]
    repository, paper, research, result, _ = run_entered(
        tmp_path, provider=CountingProvider(contracts), research=True,
    )
    assert not result["opened"]
    assert result["decisions"][0].reason == "NO_VALID_CONTRACT"
    fill = research.get_capture("entry-1", CAPTURE_PRODUCTION_FILL)
    t0 = research.get_capture("entry-1", CAPTURE_TRADE_ENTERED)
    assert t0["capture_result"] == RESULT_NO_ELIGIBLE_CONTRACT
    row = research.candidates(t0["capture_id"])[0]
    assert row["bid"] is None
    assert row["mid"] is None
    assert row["delta"] is None
    assert row["volume"] is None
    assert row["passed_selector_eligibility"] == 0
    assert row["rejection_reason"] == "MISSING_ASK"
    assert fill["production_fill"] is None
    assert paper.journal_rows()[0]["accepted"] == 0


def test_provider_failure_is_distinct_from_no_eligible_contract_and_empty_chain(tmp_path):
    failed = run_entered(tmp_path, provider=CountingProvider(error="upstream 500"), research=True)
    empty = run_entered(tmp_path / "empty", provider=CountingProvider(contracts=[]), research=True)
    none = run_entered(
        tmp_path / "none",
        provider=CountingProvider([{
            "option_type": "put", "expiration_date": "2026-08-14", "strike": 100,
            "symbol": "ABNB260814P00100000", "bid": 1.2, "ask": 1.0, "delta": -0.5,
            "open_interest": 10, "volume": 1,
        }]),
        research=True,
    )
    assert failed[2].get_capture("entry-1", CAPTURE_TRADE_ENTERED)["capture_result"] == RESULT_PROVIDER_FAILURE
    assert failed[2].get_capture("entry-1", CAPTURE_TRADE_ENTERED)["candidate_count"] is None
    assert empty[2].get_capture("entry-1", CAPTURE_TRADE_ENTERED)["capture_result"] == RESULT_CHAIN_EMPTY
    assert none[2].get_capture("entry-1", CAPTURE_TRADE_ENTERED)["capture_result"] == RESULT_NO_ELIGIBLE_CONTRACT
    assert failed[3]["opened"] == empty[3]["opened"] == none[3]["opened"] == []


def test_open_marks_are_distinct_and_reuse_refresh_quotes(tmp_path):
    repository, paper, research, result, _ = run_entered(tmp_path, research=True)
    position = result["opened"][0]
    first = refresh_paper_positions(
        config=enabled_config(), now=NOW + timedelta(minutes=5),
        quote_provider=Quotes({"bid": 1.02, "ask": 1.04, "last": 1.03, "volume": 9, "open_interest": 40}),
        trade_ledger=paper, position_store=paper,
        research_repository=research, scan_cycle_id="cycle-a",
    )
    second = refresh_paper_positions(
        config=enabled_config(), now=NOW + timedelta(minutes=10),
        quote_provider=Quotes({"bid": 1.03, "ask": 1.05, "last": 1.04, "volume": 11}),
        trade_ledger=paper, position_store=paper, research_repository=research,
        scan_cycle_id="cycle-b",
    )
    marks = research.marks(opportunity_id="entry-1")
    assert len(marks) == 2
    assert marks[0]["bid"] == 1.02 and marks[1]["bid"] == 1.03
    assert marks[0]["mark_id"] != marks[1]["mark_id"]
    again = dict(marks[1])
    again["bid"] = 9
    research.record_mark(again)
    still = research.marks(opportunity_id="entry-1")
    assert len(still) == 2
    assert still[1]["bid"] == 1.03
    assert first[0].status == second[0].status == "OPEN"
    assert marks[0]["paper_trade_id"] == position.trade_id
    missing = build_mark_record(
        paper_trade_id="t", opportunity_id="entry-1", symbol="ABNB",
        option_symbol="ABNB260814P00100000", recorded_at=NOW,
        quote={"bid": None, "ask": None, "last": None},
        position=replace(position_from_trade(
            PaperOptionTrade(
                trade_id="t", source_signal_id="entry-1", created_timestamp=NOW,
                ticker="ABNB", direction="Bearish", underlying_entry_price=100,
                confidence=80, historical_grade="A", scanner_score=80, entry_reason="t",
                expiration="2026-08-14", strike=100, option_type="put",
                option_symbol="ABNB260814P00100000", delta=-0.5, implied_volatility=0.3,
                bid=None, ask=1.05, mid=None, spread_percent=None, open_interest=500, volume=1,
            ),
            execution_time=NOW, fill_price=1.05, quantity=1,
        ), current_bid=None, current_ask=None, current_mid=1.05),
    )
    assert missing["bid"] is None and missing["ask"] is None and missing["last"] is None


def test_query_api_filters_by_reason_session_and_symbol(tmp_path):
    _, _, research, _, _ = run_entered(tmp_path, research=True)
    rows = research.captures(
        opportunity_id="entry-1", capture_reason=CAPTURE_PRODUCTION_FILL,
        option_symbol="ABNB260814P00100000", session_date="2026-08-04",
    )
    assert len(rows) == 1
    assert rows[0]["capture_reason"] == CAPTURE_PRODUCTION_FILL
    assert research.candidates_for_opportunity("entry-1")


def test_t0_helper_does_not_request_provider_data(tmp_path):
    repository, _, research = paper_bundle(tmp_path)
    provider = CountingProvider()
    result = {
        **scan_result(),
        "_authoritative_entry_id": "entry-1",
        "bias": "Bearish",
        "trade_plan": {"direction": "Bearish"},
        "timestamp": (NOW - timedelta(minutes=6)).isoformat(),
    }
    first = record_trade_entered_capture(research, result, provider, now=NOW)
    second = record_trade_entered_capture(research, result, provider, now=NOW)
    assert first["capture_id"] == second["capture_id"]
    assert first["capture_result"] == RESULT_NOT_REQUESTED_BY_PRODUCTION
    assert first["candidate_count"] is None
    assert provider.expiration_calls == 0 and provider.chain_calls == 0
    assert len(research.captures(opportunity_id="entry-1", capture_reason=CAPTURE_TRADE_ENTERED)) == 1


def _provider_counts(chain, quotes=None):
    return {
        "expirations": getattr(chain, "expiration_calls", 0),
        "chain": getattr(chain, "chain_calls", 0),
        "option_quote": getattr(quotes, "calls", 0) if quotes is not None else 0,
        "underlying_quote": (
            getattr(chain, "underlying_calls", 0)
            + (getattr(quotes, "underlying_calls", 0) if quotes is not None else 0)
        ),
    }


def _authoritative_snapshot(result, paper):
    opened = result["opened"]
    decisions = result["decisions"]
    positions = paper.load() if hasattr(paper, "load") else []
    return {
        "opened": [
            (row.option_symbol, row.paper_fill_price, row.quantity, row.status)
            for row in opened
        ],
        "decisions": [(row.eligible, row.reason, row.paper_fill_price, row.position_size) for row in decisions],
        "positions": [
            (row.option_symbol, row.status, row.paper_fill_price, row.current_mid, row.exit_reason)
            for row in positions
        ],
        "journal": [
            (row.get("accepted"), row.get("reason_code"), row.get("option_symbol"))
            for row in (paper.journal_rows() if hasattr(paper, "journal_rows") else [])
        ],
    }


def _run_parity(tmp_path, *, research, provider, quotes=None, config=None, refresh=False, score=95):
    repository = entered_repository(tmp_path, score=score)
    paper = PaperExecutionRepository(repository)
    default_research = TranslationResearchRepository(repository)
    repo = default_research if research is True else research
    candidates = pending_authoritative_entries(repository, {"ABNB": scan_result(score=score)}, paper)
    result = run_paper_execution(
        candidates,
        config=config or enabled_config(min_beacon_score=40),
        now=NOW,
        chain_provider=provider,
        quote_provider=quotes,
        trade_ledger=paper,
        position_store=paper,
        journal=paper,
        refreshed_positions=[],
        research_repository=repo,
    )
    refreshed = None
    if refresh:
        refreshed = refresh_paper_positions(
            config=enabled_config(), now=NOW + timedelta(minutes=5),
            quote_provider=quotes, trade_ledger=paper, position_store=paper,
            research_repository=repo,
        )
    return result, paper, _provider_counts(provider, quotes), refreshed


@pytest.mark.parametrize("label,provider_factory,config,refresh,score", [
    ("successful_fill", lambda: CountingProvider(), enabled_config(min_beacon_score=40), False, 95),
    ("no_eligible_contract", lambda: CountingProvider(contracts=[{
        "option_type": "put", "expiration_date": "2026-08-14", "strike": 100,
        "symbol": "ABNB260814P00100000", "bid": None, "ask": None, "delta": None,
        "open_interest": 500, "volume": None,
    }]), enabled_config(min_beacon_score=40), False, 95),
    ("provider_failure", lambda: CountingProvider(error="upstream 500"), enabled_config(min_beacon_score=40), False, 95),
    ("score_rejection", lambda: CountingProvider(), enabled_config(min_beacon_score=92), False, 44),
    ("open_position_refresh", lambda: CountingProvider(), enabled_config(min_beacon_score=40), True, 95),
])
def test_provider_call_and_authoritative_parity_off_vs_on(
    tmp_path, label, provider_factory, config, refresh, score,
):
    off_provider, on_provider = provider_factory(), provider_factory()
    quotes_off = Quotes({"bid": 1.02, "ask": 1.04, "last": 1.03}) if refresh else None
    quotes_on = Quotes({"bid": 1.02, "ask": 1.04, "last": 1.03}) if refresh else None
    off_result, off_paper, off_counts, off_refreshed = _run_parity(
        tmp_path / "off", research=None, provider=off_provider, quotes=quotes_off,
        config=config, refresh=refresh, score=score,
    )
    on_result, on_paper, on_counts, on_refreshed = _run_parity(
        tmp_path / "on", research=True, provider=on_provider, quotes=quotes_on,
        config=config, refresh=refresh, score=score,
    )
    assert off_counts == on_counts, (label, off_counts, on_counts)
    assert _authoritative_snapshot(off_result, off_paper) == _authoritative_snapshot(on_result, on_paper)
    if refresh:
        assert [(row.status, row.current_mid, row.exit_reason) for row in off_refreshed] == [
            (row.status, row.current_mid, row.exit_reason) for row in on_refreshed
        ]


def test_research_persistence_throw_keeps_provider_and_authoritative_parity(tmp_path):
    off_provider, on_provider = CountingProvider(), CountingProvider()
    off_result, off_paper, off_counts, _ = _run_parity(
        tmp_path / "off", research=None, provider=off_provider,
    )
    on_result, on_paper, on_counts, _ = _run_parity(
        tmp_path / "on", research=ExplodingResearch(), provider=on_provider,
    )
    assert off_counts == on_counts
    assert _authoritative_snapshot(off_result, off_paper) == _authoritative_snapshot(on_result, on_paper)


def test_recorders_never_invoke_provider_methods():
    for fn in (
        translation_research.record_trade_entered_capture,
        translation_research.record_production_fill_capture,
        translation_research.record_open_position_marks,
        translation_research.production_chain_observation,
    ):
        source = inspect.getsource(fn)
        assert ".expirations(" not in source
        assert ".chain(" not in source
        assert ".quote(" not in source
        assert "load_selector_chain" not in source

