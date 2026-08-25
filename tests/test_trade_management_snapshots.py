from datetime import datetime, timedelta, timezone

import pytest

from trade_repository import TradeRepository


NOW = datetime(2026, 8, 25, 15, 0, tzinfo=timezone.utc)


def snapshot(trade_id="OB:paper-1", lane="OB", **changes):
    row = {
        "trade_id": trade_id,
        "opportunity_id": "opp-1",
        "lane": lane,
        "lane_role": "AUTHORITATIVE" if lane == "OB" else "PAPER",
        "symbol": "QQQ",
        "contract_symbol": "QQQ260825C00570000",
        "captured_at": NOW,
        "source_timestamp": NOW,
        "trade_status": "OPEN",
        "quantity": 2,
        "entry_timestamp": NOW - timedelta(minutes=4),
        "entry_premium": 1.25,
        "latest_option_mark": 1.34,
        "latest_underlying": 570.4,
        "mark_timestamp": NOW,
        "time_in_trade_seconds": 240,
        "current_stop": 1.05,
        "target_1": 1.5,
        "exit_score": 42,
        "exit_label": "HOLD",
        "trade_coach_state": "THESIS_INTACT",
        "thesis_state": "INTACT",
        "management_reason": "STRUCTURE_HOLDING",
        "management_version": "test-v1",
        "management_source": "test.management",
        "unrealized_pnl": 18,
        "unrealized_return_pct": 7.2,
        "current_managed_risk": 40,
        "data_freshness": "fresh",
        "stale": False,
        "missing_data": ["target_2", "target_3"],
    }
    row.update(changes)
    return row


def test_schema_and_snapshot_round_trip_include_exact_identity_and_null_state(tmp_path):
    repository = TradeRepository(tmp_path / "management.db", database_url="")
    stored = repository.record_trade_management_snapshot(snapshot(
        exit_score=None, exit_label=None, trade_coach_state=None,
        missing_data=["exit_score", "exit_label", "trade_coach_state"],
    ))
    assert (stored["trade_id"], stored["opportunity_id"], stored["lane"]) == (
        "OB:paper-1", "opp-1", "OB")
    assert stored["contract_symbol"] == "QQQ260825C00570000"
    assert stored["exit_score"] is None and stored["exit_label"] is None
    assert stored["missing_data"] == ["exit_label", "exit_score", "trade_coach_state"]
    with repository.connection() as connection:
        columns = repository._table_columns(connection, "trade_management_snapshots")
    assert {"snapshot_id", "trade_id", "opportunity_id", "lane", "captured_at",
            "state_fingerprint", "payload_json"} <= columns


def test_refresh_only_changes_are_deduplicated_but_material_changes_append_history(tmp_path):
    repository = TradeRepository(tmp_path / "history.db", database_url="")
    first = repository.record_trade_management_snapshot(snapshot())
    duplicate = repository.record_trade_management_snapshot(snapshot(
        captured_at=NOW + timedelta(seconds=30), source_timestamp=NOW + timedelta(seconds=30),
        latest_option_mark=1.37, latest_underlying=570.6, unrealized_pnl=24,
        unrealized_return_pct=9.6, time_in_trade_seconds=270,
    ))
    changed = repository.record_trade_management_snapshot(snapshot(
        captured_at=NOW + timedelta(minutes=1), source_timestamp=NOW + timedelta(minutes=1),
        current_stop=1.25, breakeven_state="ACTIVE", stop_management_state="BREAKEVEN",
    ))
    assert duplicate["snapshot_id"] == first["snapshot_id"]
    assert changed["snapshot_id"] != first["snapshot_id"]
    history = repository.list_trade_management_snapshots("OB:paper-1", lane="ob")
    assert [row["snapshot_id"] for row in history] == [first["snapshot_id"], changed["snapshot_id"]]
    assert repository.latest_trade_management_snapshot(
        "OB:paper-1", lane="OB")["current_stop"] == 1.25


def test_exact_batch_lookup_isolates_same_symbol_multiple_trades_lanes_and_control(tmp_path):
    repository = TradeRepository(tmp_path / "identity.db", database_url="")
    rows = [
        snapshot("OB:paper-1", "OB", exit_label="HOLD"),
        snapshot("BROAD:paper-1", "BROAD", opportunity_id="opp-2", exit_label="WATCH"),
        snapshot("CONTROL:paper-1", "CONTROL_RESEARCH", opportunity_id="opp-3",
                 lane_role="RESEARCH_CONTROL", exit_label="EXIT"),
        snapshot("OB:paper-2", "OB", opportunity_id="opp-4", exit_label="REDUCE"),
    ]
    for row in rows:
        repository.record_trade_management_snapshot(row)
    latest = repository.latest_trade_management_snapshots([
        ("OB:paper-1", "OB"), ("BROAD:paper-1", "BROAD"),
        ("CONTROL:paper-1", "OB"), ("OB:paper-2", "OB"),
    ])
    assert latest[("OB:paper-1", "OB")]["exit_label"] == "HOLD"
    assert latest[("BROAD:paper-1", "BROAD")]["exit_label"] == "WATCH"
    assert latest[("OB:paper-2", "OB")]["exit_label"] == "REDUCE"
    assert ("CONTROL:paper-1", "OB") not in latest


@pytest.mark.parametrize("missing", ["trade_id", "opportunity_id", "lane", "symbol", "management_source"])
def test_snapshot_rejects_ambiguous_or_incomplete_identity(tmp_path, missing):
    repository = TradeRepository(tmp_path / f"missing-{missing}.db", database_url="")
    row = snapshot()
    row[missing] = None
    with pytest.raises(ValueError, match=missing):
        repository.record_trade_management_snapshot(row)


def test_read_methods_are_safe_before_additive_schema_is_initialized(tmp_path):
    class LegacyRepository(TradeRepository):
        def initialize(self):
            return None

    repository = LegacyRepository(tmp_path / "legacy.db", database_url="")
    assert repository.latest_trade_management_snapshot("OB:legacy", lane="OB") is None
    assert repository.latest_trade_management_snapshots([("OB:legacy", "OB")]) == {}
    assert repository.list_trade_management_snapshots("OB:legacy", lane="OB") == []
