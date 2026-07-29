"""Pure formatting and Streamlit rendering for structured Trade Plans."""

from datetime import datetime
from html import escape
import math

from trade_plan_models import PlanStatus, TradePlan


STATUS_TREATMENTS = {
    PlanStatus.WAIT: "wait",
    PlanStatus.WATCH: "watch",
    PlanStatus.READY: "ready",
    PlanStatus.ACTIVE: "active",
    PlanStatus.INVALIDATED: "invalidated",
    PlanStatus.EXPIRED: "expired",
    PlanStatus.CLOSED: "closed",
}

TRADE_PLAN_CSS = """
<style>
.ob-summary-grid,.ob-level-grid {
  display:grid; gap:.65rem; margin:.65rem 0;
}
.ob-summary-grid {grid-template-columns:repeat(6,minmax(0,1fr));}
.ob-level-grid {grid-template-columns:repeat(4,minmax(0,1fr));}
.ob-summary-item,.ob-level-item {
  min-width:0; min-height:4.5rem; box-sizing:border-box;
  border:1px solid #39414b; border-radius:10px; padding:.7rem .8rem;
  background:#11161c; color:#f2f5f7;
  white-space:normal; overflow:visible; overflow-wrap:anywhere; word-break:normal;
}
.ob-field-label {
  color:#aeb7c2; font-size:clamp(.78rem,1vw,.9rem); font-weight:700;
  letter-spacing:.035em; line-height:1.25; text-transform:uppercase;
}
.ob-field-value {
  margin-top:.28rem; color:#f7f8fa; font-size:clamp(1.15rem,2vw,1.7rem);
  font-weight:700; line-height:1.2; white-space:normal;
  overflow:visible; overflow-wrap:anywhere; word-break:normal;
}
.ob-summary-item .ob-field-value {font-size:clamp(1rem,1.5vw,1.35rem);}
.ob-plan-card {
  border:1px solid #39414b; border-radius:12px; padding:.72rem .9rem;
  background:#11161c; margin:.75rem 0 .5rem;
}
.ob-plan-heading {
  color:#f7f8fa; font-size:clamp(1.15rem,1.8vw,1.5rem); font-weight:750;
  line-height:1.3; white-space:normal; overflow-wrap:anywhere;
}
.ob-plan-status {
  margin-bottom:.2rem; font-size:.8rem; font-weight:800;
  letter-spacing:.08em; line-height:1.3; text-transform:uppercase;
}
.ob-plan-ready,.ob-plan-active {border-color:#5abf84;}
.ob-plan-ready .ob-plan-status,.ob-plan-active .ob-plan-status {color:#75d59d;}
.ob-plan-wait,.ob-plan-watch {border-color:#c8a84e;}
.ob-plan-wait .ob-plan-status,.ob-plan-watch .ob-plan-status {color:#e0c56f;}
.ob-plan-invalidated,.ob-plan-expired {border-color:#d65f5f;}
.ob-plan-invalidated .ob-plan-status,.ob-plan-expired .ob-plan-status {color:#ef8181;}
.ob-plan-closed {border-color:#68717d;}
.ob-plan-closed .ob-plan-status {color:#b8c0c9;}
.ob-status-message {
  border-left:3px solid #c8a84e; margin:.45rem 0 .8rem; padding:.45rem .75rem;
  background:#17191b; color:#dce1e6; font-size:clamp(.88rem,1.2vw,1rem);
  line-height:1.45; white-space:normal; overflow-wrap:anywhere;
}
.ob-status-message strong {color:#e0c56f;}
.ob-detail-grid {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.75rem 1.25rem;}
.ob-detail-grid section {min-width:0;overflow-wrap:anywhere;}
.ob-plan-context {
  display:grid;gap:.65rem;grid-template-columns:repeat(3,minmax(0,1fr));margin:.65rem 0;
}
.ob-context-panel {
  background:#10151b;border:1px solid #343c46;border-radius:10px;min-width:0;
  padding:.65rem .75rem;overflow-wrap:anywhere;
}
.ob-context-panel strong {color:#d9dee4;font-size:.8rem;letter-spacing:.04em;text-transform:uppercase;}
.ob-context-panel ul {color:#aeb7c2;font-size:.84rem;line-height:1.4;margin:.4rem 0 0;padding-left:1.05rem;}
@media (max-width:1050px) {
  .ob-summary-grid {grid-template-columns:repeat(3,minmax(0,1fr));}
  .ob-level-grid {grid-template-columns:repeat(2,minmax(0,1fr));}
}
@media (max-width:620px) {
  .ob-summary-grid,.ob-level-grid,.ob-detail-grid,.ob-plan-context {grid-template-columns:minmax(0,1fr);}
  .ob-summary-item,.ob-level-item {min-height:0;}
}
</style>
"""


def _value(value, money=False):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(number):
        return "—"
    return f"${number:.2f}" if money else f"{number:.2f}"


def _text(value):
    return str(value).strip() if value not in (None, "") else "—"


def _field_markup(label, value, css_class):
    return (
        f'<div class="{css_class}">'
        f'<div class="ob-field-label">{escape(_text(label))}</div>'
        f'<div class="ob-field-value">{escape(_text(value))}</div>'
        "</div>"
    )


def compact_summary_markup(fields):
    """Return a responsive summary strip without Streamlit metric truncation."""
    items = "".join(_field_markup(label, value, "ob-summary-item") for label, value in fields)
    return f'<div class="ob-summary-grid">{items}</div>'


def trade_level_grid_markup(view):
    """Return the primary trade levels in a responsive, wrapping grid."""
    fields = (
        ("Entry Zone", view.get("entry_zone")),
        ("Confirmation", view.get("confirmation_level")),
        ("Maximum Entry", view.get("maximum_entry")),
        ("Initial Stop", view.get("initial_stop")),
        ("Target 1", view.get("target_1")),
        ("Target 2", view.get("target_2")),
        ("Risk / Reward", view.get("risk_reward")),
        ("Confidence", view.get("confidence")),
    )
    items = "".join(_field_markup(label, value, "ob-level-item") for label, value in fields)
    return f'<div class="ob-level-grid">{items}</div>'


def developing_setup_display(result, eligibility):
    """Build the compact, presentation-only summary for a developing setup."""
    plan = result.get("trade_plan") or {}
    direction = plan.get("direction") or result.get("bias")
    option_bias = plan.get("option_bias") or (
        "CALL" if direction == "Bullish" else "PUT" if direction == "Bearish" else None
    )
    confidence = result.get("confidence")
    try:
        confidence_text = f"{float(confidence):.0f}%" if math.isfinite(float(confidence)) else "—"
    except (TypeError, ValueError):
        confidence_text = "—"
    reasons = list(eligibility.get("reasons") or [])
    return {
        "symbol": _text(result.get("symbol")),
        "direction_option": " ".join(value for value in (_text(direction), _text(option_bias)) if value != "—") or "—",
        "setup": _text(plan.get("setup_type") or plan.get("setup")),
        "status": _text(eligibility.get("status") or "WATCH"),
        "confidence": confidence_text,
        "timing": _text(result.get("entry_timing") or result.get("timing_label")),
        "entry_trigger": _value(
            plan.get("trigger_price") or plan.get("entry_price") or plan.get("entry_zone_low"),
            money=True,
        ),
        "blocking_reason": reasons[0] if reasons else "Entry requirements are still developing.",
        "timing_explanation": _text(
            result.get("entry_timing_reason") or result.get("timing_explanation")
        ),
    }


def render_developing_setup_summary(result, eligibility, st_module=None):
    if st_module is None:
        import streamlit as st_module
    view = developing_setup_display(result, eligibility)
    fields = (
        ("Symbol", view["symbol"]),
        ("Direction / Bias", view["direction_option"]),
        ("Setup", view["setup"]),
        ("Status", view["status"]),
        ("Confidence", view["confidence"]),
        ("Timing", view["timing"]),
    )
    st_module.markdown(TRADE_PLAN_CSS, unsafe_allow_html=True)
    st_module.markdown(compact_summary_markup(fields), unsafe_allow_html=True)
    timing = (
        f'<br><span>Timing: {escape(view["timing_explanation"])}</span>'
        if view["timing_explanation"] != "—"
        else ""
    )
    st_module.markdown(
        '<div class="ob-status-message">'
        f'<strong>{escape(view["status"])} — NOT ELIGIBLE</strong><br>'
        f'{escape(view["blocking_reason"])}{timing}<br>'
        f'<span>Entry trigger: {escape(view["entry_trigger"])}</span>'
        "</div>",
        unsafe_allow_html=True,
    )
    return view


def trade_plan_display(plan: TradePlan) -> dict:
    hold_minutes = None
    entry_timestamp = plan.current_status.get("entry_timestamp")
    if entry_timestamp:
        entered = datetime.fromisoformat(str(entry_timestamp).replace("Z", "+00:00"))
        hold_minutes = max(0.0, (plan.market_timestamp - entered).total_seconds() / 60)
    return {
        "status": plan.status.value,
        "treatment": STATUS_TREATMENTS[plan.status],
        "symbol": plan.symbol,
        "direction": plan.direction,
        "option_bias": plan.option_bias,
        "setup_name": plan.setup_name,
        "signal_time": plan.signal_timestamp.isoformat(),
        "underlying_price": _value(plan.current_underlying_price, money=True),
        "entry_zone": f"{_value(plan.entry_zone_low, True)} – {_value(plan.entry_zone_high, True)}",
        "confirmation_level": _value(plan.confirmation_level, True),
        "maximum_entry": _value(plan.maximum_acceptable_entry, True),
        "initial_stop": _value(plan.initial_stop, True),
        "target_1": _value(plan.target_1, True),
        "target_2": _value(plan.target_2, True),
        "risk_reward": f"{plan.risk_reward_target_1:.2f}:1 / {plan.risk_reward_target_2:.2f}:1",
        "confidence": f"{plan.confidence_score:.0f}/100",
        "late_entry_risk": plan.late_entry_risk.value,
        "breakeven_rule": f"Move stop to breakeven at {_value(plan.breakeven_trigger, True)}",
        "trailing_rule": f"Activate {plan.trailing_stop_method} at {_value(plan.trailing_stop_activation, True)}",
        "maximum_hold": f"{plan.maximum_hold_minutes} minutes / {plan.maximum_hold_candles} candles",
        "hold_time": f"{hold_minutes:.0f} minutes" if hold_minutes is not None else "—",
        "reasons_for_trade": plan.reasons_for_trade,
        "reasons_to_avoid": plan.reasons_to_avoid,
        "missing_requirements": plan.missing_requirements,
        "activation_requirements": plan.activation_requirements,
        "invalidation_conditions": plan.invalidation_conditions,
        "latest_event": plan.lifecycle_events[-1].event_type.value if plan.lifecycle_events else "—",
        "final_outcome": plan.final_outcome.exit_reason.value if plan.final_outcome else "—",
    }


def _detail_list(items, fallback):
    values = items or [fallback]
    return "<ul>" + "".join(f"<li>{escape(_text(item))}</li>" for item in values) + "</ul>"


def trade_plan_context_markup(view):
    """Render concise decision context while keeping full detail on demand."""
    panels = (
        ("Why This Setup", view.get("reasons_for_trade"), "No supporting reason is available."),
        ("What's Missing", view.get("missing_requirements"), "No entry blocker remains."),
        ("Invalidation", view.get("invalidation_conditions"), "No invalidation detail is available."),
    )
    body = "".join(
        '<section class="ob-context-panel">'
        f"<strong>{escape(title)}</strong>{_detail_list((items or [])[:5], fallback)}</section>"
        for title, items, fallback in panels
    )
    return f'<div class="ob-plan-context">{body}</div>'


def render_trade_plan_card(plan: TradePlan, st_module=None):
    if st_module is None:
        import streamlit as st_module
    view = trade_plan_display(plan)
    st_module.markdown(TRADE_PLAN_CSS, unsafe_allow_html=True)
    st_module.markdown(
        f'<div class="ob-plan-card ob-plan-{view["treatment"]}">'
        f'<div class="ob-plan-status">{escape(view["status"])}</div>'
        f'<div class="ob-plan-heading">{escape(view["symbol"])} · {escape(view["direction"])} · '
        f'{escape(view["option_bias"])} · {escape(view["setup_name"])}</div></div>',
        unsafe_allow_html=True,
    )
    st_module.markdown(trade_level_grid_markup(view), unsafe_allow_html=True)
    st_module.markdown(trade_plan_context_markup(view), unsafe_allow_html=True)
    with st_module.expander("View Full Trade Plan"):
        detail_html = (
            '<div class="ob-detail-grid">'
            f'<section><strong>Why This Setup</strong>{_detail_list(view["reasons_for_trade"], "None identified")}</section>'
            f'<section><strong>What Is Missing</strong>{_detail_list(view["missing_requirements"], "Nothing required")}</section>'
            f'<section><strong>Activation Conditions</strong>{_detail_list(view["activation_requirements"], "All requirements are satisfied")}</section>'
            f'<section><strong>Invalidation</strong>{_detail_list(view["invalidation_conditions"], "None identified")}</section>'
            f'<section><strong>Lifecycle</strong><p>Latest event: {escape(view["latest_event"])}<br>'
            f'Current hold: {escape(view["hold_time"])}<br>Maximum hold: {escape(view["maximum_hold"])}</p></section>'
            f'<section><strong>Diagnostics</strong><p>Late-entry risk: {escape(view["late_entry_risk"])}<br>'
            f'Signal: {escape(view["signal_time"])}<br>{escape(view["breakeven_rule"])}<br>'
            f'{escape(view["trailing_rule"])}</p></section>'
            "</div>"
        )
        st_module.markdown(detail_html, unsafe_allow_html=True)
        if plan.status == PlanStatus.CLOSED:
            st_module.write(f"**Final outcome:** {view['final_outcome']}")
    return view
