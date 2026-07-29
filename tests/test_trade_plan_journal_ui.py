import json
from datetime import datetime, timezone

from developer_tools import verify_trade_plan_engine
from trade_plan_engine import build_structured_trade_plan
from trade_plan_journal import (
    load_legacy_trade_outcomes,
    load_trade_plan_journal,
    paper_journal_row,
    save_trade_plan,
)
from trade_plan_lifecycle import update_trade_plan
from trade_plan_models import PlanStatus
from trade_plan_ui import render_trade_plan_card, trade_plan_display
from signal_history import create_trade_record, serialize_trade_outcome


NOW = datetime(2026, 7, 29, 14, 0, tzinfo=timezone.utc)


def plan(**overrides):
    values = {
        "symbol": "SPY",
        "bias": "Bullish",
        "price": 501,
        "support": 498,
        "resistance": 500.5,
        "atr": 2,
        "relative_volume": 1.5,
        "confidence": 82,
        "confirmation_reached": True,
        "timestamp": NOW,
        "last_candle_at": NOW,
    }
    values.update(overrides)
    return build_structured_trade_plan(values, evaluation_timestamp=NOW)


def test_new_journal_round_trip_and_duplicate_update(tmp_path):
    path = tmp_path / "journal.jsonl"
    value = plan()
    save_trade_plan(value, path)
    save_trade_plan(value, path)

    loaded = load_trade_plan_journal(path)
    assert loaded == [value]
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_legacy_and_malformed_rows_are_safe(tmp_path):
    legacy = tmp_path / "legacy.jsonl"
    legacy.write_text(json.dumps({"trade_id": "legacy"}) + "\nnot-json\n", encoding="utf-8")

    assert load_trade_plan_journal(legacy) == []
    assert load_legacy_trade_outcomes(tmp_path / "missing.jsonl") == []


def test_legacy_trade_outcome_adapter(tmp_path):
    legacy = tmp_path / "signal_history.jsonl"
    outcome = create_trade_record(
        symbol="SPY",
        direction="Bullish",
        setup="Legacy",
        confidence=70,
        entry=100,
        stop=98,
        target_1=102,
        target_2=104,
        timestamp=NOW,
    )
    legacy.write_text(serialize_trade_outcome(outcome) + "\n", encoding="utf-8")

    assert load_legacy_trade_outcomes(legacy) == [outcome]


def test_paper_journal_contains_expanded_fields():
    row = paper_journal_row(plan())

    for field in (
        "trade_id", "trade_plan_id", "symbol", "option_bias", "setup_name",
        "signal_timestamp", "ready_timestamp", "initial_stop", "final_stop",
        "target_1", "target_2", "breakeven_trigger", "trailing_stop_method",
        "confidence_score", "late_entry_risk", "risk_reward_target_1",
        "risk_reward_target_2", "original_trade_plan_snapshot",
        "lifecycle_events", "created_at", "updated_at",
    ):
        assert field in row


def test_wait_ready_active_and_closed_display_shapes():
    ready = plan()
    wait = plan(relative_volume=0.2)
    assert trade_plan_display(ready)["status"] == "READY"
    assert trade_plan_display(wait)["status"] in {"WAIT", "WATCH"}
    assert trade_plan_display(ready)["entry_zone"] != "—"
    assert trade_plan_display(ready)["treatment"] == "ready"


def test_wait_ready_active_and_closed_cards_render():
    class Column:
        def metric(self, *_args, **_kwargs):
            return None

    class Expander:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class FakeStreamlit:
        calls = []

        @classmethod
        def markdown(cls, value, **_kwargs):
            cls.calls.append(value)

        @staticmethod
        def columns(count):
            return [Column() for _ in range(count)]

        @staticmethod
        def caption(*_args, **_kwargs):
            return None

        @staticmethod
        def write(*_args, **_kwargs):
            return None

        @staticmethod
        def expander(*_args, **_kwargs):
            return Expander()

    ready = plan()
    wait = plan(relative_volume=0.2)
    active = plan()
    update_trade_plan(active, current_price=active.confirmation_level, current_timestamp=NOW)
    closed = plan()
    update_trade_plan(closed, current_price=closed.confirmation_level, current_timestamp=NOW)
    update_trade_plan(closed, current_price=closed.target_2, current_timestamp=NOW)

    for value in (wait, ready, active, closed):
        rendered = render_trade_plan_card(value, FakeStreamlit)
        assert rendered["status"] == value.status.value

    assert any("ob-plan-card" in call for call in FakeStreamlit.calls)


def test_no_secret_values_are_serialized_or_displayed():
    secret = "secret-value-that-must-not-render"
    value = plan(api_key=secret, token=secret, headers={"Authorization": secret})

    assert secret not in json.dumps(value.to_dict())
    assert secret not in json.dumps(trade_plan_display(value))


def test_trade_plan_diagnostic_passes_without_network_or_production_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = verify_trade_plan_engine(now=NOW)

    assert result["overall_result"] == "PASS"
    assert all(check["status"] == "PASS" for check in result["checks"])
    assert result["provider_mode"] == "DETERMINISTIC MOCK"
    assert not list(tmp_path.iterdir())


def test_status_treatments_cover_every_lifecycle_state():
    value = plan()
    treatments = {}
    for status in PlanStatus:
        value.status = status
        treatments[status.value] = trade_plan_display(value)["treatment"]

    assert set(treatments) == {status.value for status in PlanStatus}
    assert len(set(treatments.values())) == len(PlanStatus)
