import json
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from execution_config import ExecutionConfig
from option_position_tracker import position_from_trade
from option_trade_engine import PaperOptionTrade, capture_qualified_signal
from paper_execution_repository import PaperExecutionRepository
from trade_desk_compact import (
    paper_ledger_reconciliation,
    paper_position_provenance,
    paper_position_rows,
    positions_table_markup,
)
from trade_desk_comparison import trade_comparison_model
from trade_repository import TradeRepository


NOW = datetime(2026, 8, 10, 15, 0, tzinfo=timezone.utc)


def capture(trade_id, source_id, contract="FCX-C"):
    return PaperOptionTrade(
        trade_id=trade_id, source_signal_id=source_id, created_timestamp=NOW,
        ticker="FCX", direction="Bullish", underlying_entry_price=45,
        confidence=90, historical_grade="A", scanner_score=90, entry_reason="x",
        expiration="2026-08-14", strike=45, option_type="call",
        option_symbol=contract, delta=.5, implied_volatility=.2, bid=.9, ask=1.1,
        mid=1, spread_percent=20, open_interest=100, volume=100,
    )


def journal(trade_id, profile="BROAD", accepted=1):
    return {
        "trade_id": trade_id, "scanner_id": "railway-primary",
        "accepted": accepted, "reason_code": "ELIGIBLE",
        "created_at": NOW.isoformat(),
        "metadata_json": json.dumps({
            "journal_type": "ENTRY_DECISION", "simulation_profile": profile,
        }),
    }


def position(trade, minutes=1):
    return position_from_trade(
        trade, execution_time=NOW - timedelta(minutes=minutes), fill_price=1,
    )


def event(identity):
    return {
        "event_type": "TRADE_ENTERED", "opportunity_id": identity,
        "trade_id": identity, "event_timestamp": NOW, "symbol": "FCX",
        "direction": "Bullish", "underlying_price": 45,
    }


def test_all_account_positions_have_explicit_lane_and_account_scope_label():
    captures = [capture("broad", "auth-1"), capture("safe", "auth-2"),
                capture("legacy", "legacy-source")]
    provenance = paper_position_provenance(
        captures, [journal("broad"), journal("safe", "SAFE")]
    )
    positions = [position(captures[0]), position(captures[1]), position(captures[2])]
    rows = paper_position_rows(positions, ExecutionConfig(), NOW, provenance)

    assert [row["lane"] for row in rows] == [
        "BROAD PAPER", "SAFE PAPER", "LEGACY PAPER"
    ]
    assert all(row["source_signal_id"] for row in rows)
    markup = positions_table_markup(rows)
    assert "PAPER ACCOUNT — ALL RECORDED PROFILES" in markup
    assert "SOURCE / LANE" in markup
    assert "Account scope" in markup and "selected authoritative session" in markup


def test_reconciliation_count_matches_stated_account_scope_and_flags_unknown():
    captures = [capture("broad", "auth-1"), capture("legacy", "legacy-1")]
    positions = [position(captures[0]), position(captures[1]),
                 position(capture("missing", "missing-source"))]
    provenance = paper_position_provenance(captures, [journal("broad")])

    result = paper_ledger_reconciliation(positions, provenance)

    assert result == {
        "total_paper_open": 3, "broad_open": 1, "other_legacy_open": 1,
        "unknown_provenance": 1, "duplicate_source_identities": 0,
        "lane_counts": {
            "BROAD PAPER": 1, "LEGACY PAPER": 1, "UNKNOWN PROVENANCE": 1,
        },
    }


def test_session_broad_metrics_exclude_safe_legacy_and_intraday_records():
    captures = [capture("broad", "broad-auth"), capture("safe", "safe-auth"),
                capture("legacy", "legacy-auth")]
    model = trade_comparison_model(
        [event("broad-auth"), event("safe-auth"), event("legacy-auth")],
        [journal("broad"), journal("safe", "SAFE"),
         {**journal("legacy"), "metadata_json": json.dumps({"journal_type": "ENTRY_DECISION"})}],
        captures, [position(item) for item in captures],
        session_date=NOW.astimezone().date(),
        mirror_rows=[{
            "opportunity_id": "broad-auth", "entry_event_at": NOW,
            "opened_at": NOW, "status": "OPEN", "disposition_code": "MIRROR_OPENED",
            "quantity": 1, "total_debit": 100, "unrealized_pnl": 0,
            "exit_quote_at": None,
        }],
        mirror_runtime={"status": "ACTIVE", "enabled": 1,
                        "experiment_start_date": NOW.date().isoformat()},
    )

    assert model["paper"]["opened"] == 1
    assert model["mirror"]["opened"] == 1
    assert {row["authoritative_id"]: row["paper_disposition"] for row in model["rows"]} == {
        "broad-auth": "OPENED", "safe-auth": "PENDING", "legacy-auth": "PENDING",
    }


def test_broad_opened_requires_persisted_position_not_only_accepted_decision():
    model = trade_comparison_model(
        [event("auth-1")], [journal("paper-1")],
        [capture("paper-1", "auth-1")], [],
        session_date=NOW.astimezone().date(),
    )

    assert model["paper"]["opened"] == 0
    assert model["paper"]["accepted_position_missing"] == 1
    assert model["rows"][0]["paper_disposition"] == "ACCEPTED — POSITION MISSING"
    assert model["rows"][0]["paper_reason"] == "POSITION_NOT_PERSISTED"


def test_same_contract_is_valid_for_distinct_authoritative_sources():
    first = capture("paper-one", "auth-one", contract="FCX260814C00045000")
    second = capture("paper-two", "auth-two", contract="FCX260814C00045000")
    provenance = paper_position_provenance(
        [first, second], [journal("paper-one"), journal("paper-two")]
    )

    result = paper_ledger_reconciliation(
        [position(first, 1), position(second, 2)], provenance
    )

    assert result["total_paper_open"] == 2
    assert result["duplicate_source_identities"] == 0


def test_same_source_replay_returns_existing_capture_and_logs_prevention(
        tmp_path, caplog):
    repository = PaperExecutionRepository(
        TradeRepository(tmp_path / "state.db", database_url="")
    )
    existing = capture("paper-one", "auth-one")
    repository.append_once(existing)
    result = {"_authoritative_entry_id": "auth-one"}

    with caplog.at_level(logging.INFO):
        replay = capture_qualified_signal(result, repository=repository, now=NOW)

    assert replay.trade_id == existing.trade_id
    assert repository.counts()["trades"] == 1
    payload = next(json.loads(record.message) for record in caplog.records
                   if record.message.startswith("{"))
    assert payload["event"] == "paper_position_duplicate_prevented"
    assert payload["source_signal_id"] == "auth-one"
