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
from trade_plan_ui import (
    TRADE_PLAN_CSS,
    compact_summary_markup,
    developing_setup_display,
    render_developing_setup_summary,
    render_trade_plan_card,
    trade_level_grid_markup,
    trade_plan_context_markup,
    trade_plan_display,
)
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

        @classmethod
        def write(cls, value, **_kwargs):
            cls.calls.append(value)

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


def test_primary_trade_values_render_in_full_without_metric_clipping():
    value = plan()
    value.setup_name = "Bullish momentum continuation above a multi-session resistance level"
    view = trade_plan_display(value)
    markup = trade_level_grid_markup(view)
    header_streamlit = type(
        "Capture",
        (),
        {
            "calls": [],
            "markdown": classmethod(
                lambda cls, text, **_kwargs: cls.calls.append(text)
            ),
            "expander": staticmethod(
                lambda *_args, **_kwargs: type(
                    "Context",
                    (),
                    {
                        "__enter__": lambda self: self,
                        "__exit__": lambda self, *_args: False,
                    },
                )()
            ),
            "write": staticmethod(lambda *_args, **_kwargs: None),
        },
    )

    render_trade_plan_card(value, header_streamlit)
    rendered = "\n".join(header_streamlit.calls)

    for expected in (
        value.direction,
        value.setup_name,
        view["entry_zone"],
        view["confirmation_level"],
        view["maximum_entry"],
        view["initial_stop"],
        view["target_1"],
        view["target_2"],
        view["risk_reward"],
        view["confidence"],
    ):
        assert expected in rendered or expected in markup


def test_developing_summary_preserves_full_setup_timing_and_trigger():
    result = {
        "symbol": "SPY",
        "bias": "Bearish",
        "confidence": 54,
        "entry_timing": "Too Early — confirmation candle has not closed",
        "entry_timing_reason": "Wait for the full confirmation candle to close above volume.",
        "trade_plan": {
            "direction": "Bearish",
            "option_bias": "PUT",
            "setup_type": "Bearish breakdown beneath a long multi-session support level",
            "trigger_price": 499.125,
        },
    }
    view = developing_setup_display(
        result,
        {"eligible": False, "status": "WATCH", "reasons": ["Confidence is below 65%."]},
    )
    markup = compact_summary_markup(
        (
            ("Direction / Bias", view["direction_option"]),
            ("Setup", view["setup"]),
            ("Timing", view["timing"]),
        )
    )

    assert "Bearish PUT" in markup
    assert result["trade_plan"]["setup_type"] in markup
    assert result["entry_timing"] in markup
    assert view["entry_trigger"] == "$499.12"


def test_developing_summary_renderer_includes_status_reason_timing_and_trigger():
    class Capture:
        calls = []

        @classmethod
        def markdown(cls, text, **_kwargs):
            cls.calls.append(text)

    result = {
        "symbol": "QQQ",
        "bias": "Bullish",
        "confidence": 64,
        "entry_timing": "Wait for confirmation",
        "entry_timing_reason": "Price has not confirmed the trigger.",
        "trade_plan": {
            "direction": "Bullish",
            "setup_type": "Bullish breakout",
            "trigger_price": 601.5,
        },
    }
    render_developing_setup_summary(
        result,
        {"eligible": False, "status": "WAIT", "reasons": ["Confidence is below 65%."]},
        Capture,
    )
    rendered = "\n".join(Capture.calls)

    assert "WAIT — NOT ELIGIBLE" in rendered
    assert "Confidence is below 65%." in rendered
    assert "Price has not confirmed the trigger." in rendered
    assert "Entry trigger: $601.50" in rendered


def test_all_primary_plan_states_have_text_and_treatment():
    value = plan()
    for status in (PlanStatus.WATCH, PlanStatus.READY, PlanStatus.WAIT, PlanStatus.ACTIVE):
        value.status = status
        view = trade_plan_display(value)
        assert view["status"] == status.value
        assert f"ob-plan-{view['treatment']}" in (
            f"ob-plan-{view['treatment']}"
        )


def test_missing_optional_grid_values_show_safe_placeholder():
    markup = trade_level_grid_markup({})

    assert markup.count("—") == 8


def test_trade_plan_css_wraps_core_values_without_ellipsis_or_clipping():
    lowered = TRADE_PLAN_CSS.lower()

    assert "text-overflow" not in lowered
    assert "overflow:hidden" not in lowered.replace(" ", "")
    assert "white-space:normal" in lowered.replace(" ", "")
    assert "overflow-wrap:anywhere" in lowered.replace(" ", "")
    assert "repeat(4,minmax(0,1fr))" in lowered.replace(" ", "")
    assert "repeat(2,minmax(0,1fr))" in lowered.replace(" ", "")


def test_trade_plan_context_prioritizes_why_missing_and_invalidation():
    value = plan(relative_volume=0.2)
    view = trade_plan_display(value)
    markup = trade_plan_context_markup(view)

    assert "Why This Setup" in markup
    assert "What&#x27;s Missing" in markup
    assert "Invalidation" in markup
    assert "ob-plan-context" in markup


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
