"""Unified, screenshot-matched featured setup card for the Trade Desk."""

from datetime import datetime, timezone
from html import escape
from types import SimpleNamespace

from trade_plan_models import PlanStatus
from trade_plan_ui import trade_plan_display


FEATURED_SETUP_CSS = """
<style>
.ob-featured {
  background:linear-gradient(135deg,#111820 0%,#0c1218 100%);
  border:1px solid #35404a;border-radius:11px;margin:26px 0 0;
  padding:31px 11px 31px 21px;
}
.ob-featured-label {
  color:#b8c1cb;font-size:.8rem;font-weight:800;letter-spacing:.045em;
  margin-bottom:1.15rem;text-transform:uppercase;
}
.ob-featured-layout {
  display:grid;gap:24px;grid-template-columns:170px minmax(0,1fr) 250px;
  min-height:310px;min-width:0;
}
.ob-featured-identity {
  border-right:1px solid rgba(255,255,255,.11);min-width:0;padding-right:1.2rem;
}
.ob-featured-symbol {color:#f5f7f9;font-size:clamp(2.45rem,4vw,3.25rem);font-weight:760;line-height:1;}
.ob-featured-direction {
  color:#ff5e61;font-size:clamp(1.15rem,2vw,1.45rem);font-weight:760;margin-top:.7rem;
}
.ob-featured-setup {color:#aeb7c2;font-size:clamp(.95rem,1.5vw,1.15rem);line-height:1.35;margin-top:.45rem;}
.ob-featured-state {align-items:center;display:flex;flex-wrap:wrap;gap:.7rem;margin-top:1.1rem;}
.ob-featured-badge {
  border:1px solid #d9ad25;border-radius:6px;color:#f3c838;font-size:.78rem;
  font-weight:850;letter-spacing:.025em;padding:.45rem .65rem;
}
.ob-featured-timing-inline {color:#e4e7eb;font-size:.9rem;}
.ob-featured-levels {display:grid;gap:0;grid-template-columns:repeat(3,minmax(0,1fr));min-width:0;}
.ob-featured-level {
  border-bottom:1px solid rgba(255,255,255,.1);border-right:1px solid rgba(255,255,255,.1);
  min-width:0;padding:.15rem 1rem 1rem;
}
.ob-featured-level:nth-child(3n) {border-right:0}
.ob-featured-level:nth-child(n+4) {padding-top:1rem}
.ob-featured-level:nth-child(n+7) {border-bottom:0;padding-bottom:.15rem}
.ob-featured-value {
  color:#f1f3f5;font-size:clamp(1.05rem,1.7vw,1.35rem);font-weight:540;
  line-height:1.25;margin-top:.35rem;overflow-wrap:anywhere;white-space:normal;
}
.ob-featured-value-stop {color:#ff5558}.ob-featured-value-target {color:#4bd16f}
.ob-featured-value-confidence {color:#f1c635;font-weight:760}
.ob-featured-reasoning {
  border:1px solid #35404a;border-left:4px solid #d9ad25;border-radius:8px;
  min-width:0;padding:1rem;
}
.ob-reason-block + .ob-reason-block {margin-top:1rem}
.ob-reason-title {color:#c2c9d1;font-size:.78rem;font-weight:800;text-transform:uppercase}
.ob-reason-text {color:#aeb7c2;font-size:.9rem;line-height:1.5;margin-top:.4rem;overflow-wrap:anywhere}
.ob-full-plan {margin:.9rem auto 0;max-width:48rem;text-align:center}
.ob-full-plan summary {
  color:#edf0f3;cursor:pointer;font-size:.9rem;list-style:none;padding:.45rem;
}
.ob-full-plan summary::-webkit-details-marker {display:none}
.ob-full-plan summary::after {content:"⌄";margin-left:.65rem}
.ob-full-plan[open] summary::after {content:"⌃"}
.ob-full-plan-body {
  border-top:1px solid rgba(255,255,255,.1);color:#aeb7c2;font-size:.83rem;
  line-height:1.5;margin-top:.4rem;padding:.8rem;text-align:left;
}
.ob-full-plan-grid {display:grid;gap:.8rem;grid-template-columns:repeat(2,minmax(0,1fr))}
.ob-full-plan-grid strong {color:#d9dee4}
@media (max-width:900px) {
  .ob-featured-layout {grid-template-columns:1fr 2fr}
  .ob-featured-reasoning {grid-column:1/-1}
}
@media (max-width:620px) {
  .ob-featured {padding:1rem}
  .ob-featured-layout {grid-template-columns:1fr}
  .ob-featured-identity {border-bottom:1px solid rgba(255,255,255,.1);border-right:0;padding:0 0 1rem}
  .ob-featured-levels {grid-template-columns:1fr}
  .ob-featured-level,.ob-featured-level:nth-child(3n),.ob-featured-level:nth-child(n+7) {
    border-bottom:1px solid rgba(255,255,255,.1);border-right:0;padding:.7rem 0;
  }
  .ob-featured-level:last-child {border-bottom:0}
  .ob-full-plan-grid {grid-template-columns:1fr}
}
</style>
"""


def _items(values, fallback):
    items = list(values or [])[:2]
    return " ".join(str(value) for value in items) if items else fallback


def featured_setup_markup(plan, timing=None):
    """Return one unified card populated exclusively from an existing TradePlan."""
    view = trade_plan_display(plan)
    timing_text = str(timing or "—")
    levels = (
        ("Entry Zone", view["entry_zone"], ""),
        ("Confirmation", view["confirmation_level"], ""),
        ("Max Entry", view["maximum_entry"], ""),
        ("Stop", view["initial_stop"], " ob-featured-value-stop"),
        ("Target 1", view["target_1"], " ob-featured-value-target"),
        ("Target 2", view["target_2"], " ob-featured-value-target"),
        ("Confidence", view["confidence"], " ob-featured-value-confidence"),
        ("Risk / Reward", view["risk_reward"], ""),
        ("Timing", timing_text, ""),
    )
    level_markup = "".join(
        '<div class="ob-featured-level">'
        f'<div class="ob-field-label">{escape(label)}</div>'
        f'<div class="ob-featured-value{treatment}">{escape(value)}</div></div>'
        for label, value, treatment in levels
    )
    why = _items(view["reasons_for_trade"], "The directional setup is still developing.")
    missing = _items(view["missing_requirements"], "No entry blocker remains.")
    invalidation = _items(
        view["invalidation_conditions"],
        f"Price violates the planned stop at {view['initial_stop']}.",
    )
    details = (
        '<div class="ob-full-plan-grid">'
        f'<div><strong>Activation conditions</strong><br>{escape(_items(view["activation_requirements"], "All entry requirements are satisfied."))}</div>'
        f'<div><strong>Lifecycle</strong><br>Latest event: {escape(view["latest_event"])}<br>Maximum hold: {escape(view["maximum_hold"])}</div>'
        f'<div><strong>Monitoring</strong><br>{escape(view["breakeven_rule"])}<br>{escape(view["trailing_rule"])}</div>'
        f'<div><strong>Diagnostics</strong><br>Late-entry risk: {escape(view["late_entry_risk"])}<br>Signal: {escape(view["signal_time"])}</div>'
        "</div>"
    )
    return (
        '<section class="ob-featured">'
        '<div class="ob-featured-label">Best Developing Setup</div>'
        '<div class="ob-featured-layout">'
        '<div class="ob-featured-identity">'
        f'<div class="ob-featured-symbol">{escape(view["symbol"])}</div>'
        f'<div class="ob-featured-direction">{escape(view["direction"])} {escape(view["option_bias"])}</div>'
        f'<div class="ob-featured-setup">{escape(view["setup_name"])}</div>'
        '<div class="ob-featured-state">'
        f'<span class="ob-featured-badge">{escape(view["status"])}</span>'
        f'<span class="ob-featured-timing-inline">{escape(timing_text)}</span></div></div>'
        f'<div class="ob-featured-levels">{level_markup}</div>'
        '<aside class="ob-featured-reasoning">'
        f'<div class="ob-reason-block"><div class="ob-reason-title">Why This Setup</div><div class="ob-reason-text">{escape(why)}</div></div>'
        f'<div class="ob-reason-block"><div class="ob-reason-title">What’s Missing</div><div class="ob-reason-text">{escape(missing)}</div></div>'
        f'<div class="ob-reason-block"><div class="ob-reason-title">Invalidation</div><div class="ob-reason-text">{escape(invalidation)}</div></div>'
        "</aside></div>"
        '<details class="ob-full-plan"><summary>View full trade plan</summary>'
        f'<div class="ob-full-plan-body">{details}</div></details></section>'
    )


def render_featured_setup_card(plan, timing=None, st_module=None):
    if st_module is None:
        import streamlit as st_module
    st_module.markdown(FEATURED_SETUP_CSS, unsafe_allow_html=True)
    st_module.markdown(
        featured_setup_markup(plan, timing),
        unsafe_allow_html=True,
    )
    return trade_plan_display(plan)


def scanner_result_plan_adapter(result, status="WATCH"):
    """Adapt existing scanner fields for presentation without recalculating them."""
    result = dict(result or {})
    source = result.get("trade_plan") or {}
    direction = source.get("direction") or result.get("bias") or "—"
    option_bias = source.get("option_bias") or (
        "CALL" if direction == "Bullish" else "PUT" if direction == "Bearish" else "—"
    )
    timestamp = result.get("timestamp") or result.get("signal_timestamp")
    if not isinstance(timestamp, datetime):
        try:
            timestamp = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            timestamp = datetime.now(timezone.utc)
    try:
        plan_status = PlanStatus(str(status))
    except ValueError:
        plan_status = PlanStatus.WATCH
    return SimpleNamespace(
        status=plan_status,
        symbol=result.get("symbol") or "—",
        direction=direction,
        option_bias=option_bias,
        setup_name=source.get("setup_type") or source.get("setup") or result.get("setup") or "—",
        signal_timestamp=timestamp,
        market_timestamp=timestamp,
        current_underlying_price=result.get("price"),
        entry_zone_low=source.get("entry_zone_low") or source.get("entry_price") or source.get("trigger_price"),
        entry_zone_high=source.get("entry_zone_high") or source.get("entry_price") or source.get("trigger_price"),
        confirmation_level=source.get("confirmation_level") or source.get("trigger_price"),
        maximum_acceptable_entry=source.get("maximum_acceptable_entry") or source.get("max_entry_price") or source.get("max_entry") or source.get("entry_zone_high"),
        initial_stop=source.get("technical_stop") or source.get("stop") or source.get("initial_stop"),
        target_1=source.get("target_1"),
        target_2=source.get("target_2"),
        risk_reward_target_1=source.get("risk_reward_target_1"),
        risk_reward_target_2=source.get("risk_reward_target_2") or source.get("risk_reward"),
        confidence_score=result.get("confidence"),
        late_entry_risk=SimpleNamespace(value=result.get("late_entry_risk") or "—"),
        breakeven_trigger=source.get("breakeven_trigger"),
        trailing_stop_method=source.get("trailing_stop_method") or "trailing stop",
        trailing_stop_activation=source.get("trailing_stop_activation"),
        maximum_hold_minutes=source.get("maximum_hold_minutes") or 0,
        maximum_hold_candles=source.get("maximum_hold_candles") or 0,
        current_status={},
        reasons_for_trade=source.get("reasons_for_trade") or result.get("reasons") or [],
        reasons_to_avoid=source.get("reasons_to_avoid") or [],
        missing_requirements=source.get("missing_requirements") or result.get("missing_requirements") or [],
        activation_requirements=source.get("activation_requirements") or [],
        invalidation_conditions=source.get("invalidation_conditions") or (
            [source["invalidation_condition"]] if source.get("invalidation_condition") else []
        ),
        lifecycle_events=[],
        final_outcome=None,
    )


def render_scanner_featured_setup(result, eligibility, st_module=None):
    status = eligibility.get("status") or "WATCH"
    adapted_result = dict(result or {})
    if eligibility.get("reasons"):
        adapted_result["missing_requirements"] = eligibility["reasons"]
    adapter = scanner_result_plan_adapter(adapted_result, status)
    timing = result.get("entry_timing") or result.get("timing_label") or "—"
    return render_featured_setup_card(adapter, timing, st_module)
