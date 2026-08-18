from datetime import datetime, timezone
from pathlib import Path

from featured_setup_card import (
    FEATURED_SETUP_CSS,
    featured_setup_markup,
    scanner_result_plan_adapter,
)
from trade_plan_engine import build_structured_trade_plan


NOW = datetime(2026, 7, 29, 14, 0, tzinfo=timezone.utc)


def structured_plan():
    return build_structured_trade_plan(
        {
            "symbol": "SPY",
            "bias": "Bearish",
            "price": 600,
            "support": 598,
            "resistance": 602,
            "atr": 2,
            "relative_volume": 1.3,
            "confidence": 82,
            "confirmation_reached": True,
            "timestamp": NOW,
            "last_candle_at": NOW,
        },
        evaluation_timestamp=NOW,
    )


def scanner_result():
    return {
        "symbol": "TSLA",
        "bias": "Bearish",
        "confidence": 46,
        "timestamp": NOW,
        "entry_timing": "Too early",
        "trade_plan": {
            "direction": "Bearish",
            "setup_type": "Bearish breakdown",
            "entry_zone_low": 301.58,
            "entry_zone_high": 301.88,
            "trigger_price": 301.73,
            "max_entry_price": 301.35,
            "technical_stop": 305.85,
            "target_1": 297.20,
            "target_2": 292.30,
            "risk_reward": 2.05,
            "invalidation_condition": "Price above $302.90.",
        },
        "missing_requirements": [
            "Breakdown confirmation and increased selling volume."
        ],
        "reasons": ["Price is below key support with weak momentum."],
    }


def test_unified_featured_card_contains_every_core_value():
    markup = featured_setup_markup(structured_plan(), "Too early")

    for label in (
        "Best Developing Setup",
        "Entry Zone",
        "Confirmation",
        "Max Entry",
        "Stop",
        "Target 1",
        "Target 2",
        "Confidence",
        "Risk / Reward",
        "Timing",
        "Why This Setup",
        "What’s Missing",
        "Invalidation",
        "View full trade plan",
    ):
        assert label in markup
    assert markup.count('class="ob-featured"') == 1
    assert markup.count("Confidence") == 1
    assert markup.count('class="ob-featured-levels"') == 1


def test_single_stock_scanner_result_uses_existing_values_without_engine_rebuild():
    adapter = scanner_result_plan_adapter(scanner_result(), "WATCH")
    markup = featured_setup_markup(adapter, "Too early")

    for value in (
        "TSLA",
        "Bearish PUT",
        "Bearish breakdown",
        "$301.58 – $301.88",
        "$301.73",
        "$301.35",
        "$305.85",
        "$297.20",
        "$292.30",
        "46%",
        "2.05:1",
        "Price above $302.90.",
    ):
        assert value in markup


def test_full_trade_plan_is_native_details_and_collapsed_by_default():
    markup = featured_setup_markup(structured_plan(), "Ready")

    assert '<details class="ob-full-plan">' in markup
    assert '<details class="ob-full-plan" open>' not in markup


def test_featured_css_has_no_ellipsis_or_clipped_core_values():
    compact = FEATURED_SETUP_CSS.lower().replace(" ", "")

    assert "text-overflow:ellipsis" not in compact
    assert "overflow:hidden" not in compact
    assert "overflow-wrap:anywhere" in compact


def test_default_trade_desk_delegates_to_approved_journal_renderer():
    source = Path("app.py").read_text(encoding="utf-8")
    start = source.index('elif active_page == "Trade Desk":')
    end = source.index('elif active_page == "Strategy Lab":')
    body = source[start:end]

    assert "render_outcome_trade_journal(" in body
    assert "st.metric(" not in body
    assert "st.selectbox(" not in body
