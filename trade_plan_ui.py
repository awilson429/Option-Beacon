"""Pure formatting and Streamlit rendering for structured Trade Plans."""

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


def _value(value, money=False):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(number):
        return "—"
    return f"${number:.2f}" if money else f"{number:.2f}"


def trade_plan_display(plan: TradePlan) -> dict:
    hold_minutes = None
    entry_timestamp = plan.current_status.get("entry_timestamp")
    if entry_timestamp:
        from datetime import datetime

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


def render_trade_plan_card(plan: TradePlan, st_module=None):
    if st_module is None:
        import streamlit as st_module
    view = trade_plan_display(plan)
    st_module.markdown(
        """
        <style>
        .ob-plan-card {border:1px solid #39414b;border-radius:12px;padding:1rem;background:#11161c;margin:.75rem 0;}
        .ob-plan-status {font-size:.78rem;font-weight:800;letter-spacing:.08em;text-transform:uppercase;}
        .ob-plan-ready,.ob-plan-active {border-color:#5abf84;}
        .ob-plan-wait,.ob-plan-watch {border-color:#c8a84e;}
        .ob-plan-invalidated,.ob-plan-expired {border-color:#d65f5f;}
        .ob-plan-closed {border-color:#68717d;}
        </style>
        """,
        unsafe_allow_html=True,
    )
    st_module.markdown(
        f'<div class="ob-plan-card ob-plan-{view["treatment"]}">'
        f'<div class="ob-plan-status">{escape(view["status"])}</div>'
        f'<strong>{escape(view["symbol"])} · {escape(view["direction"])} · '
        f'{escape(view["option_bias"])}</strong><br>{escape(view["setup_name"])}</div>',
        unsafe_allow_html=True,
    )
    columns = st_module.columns(4)
    fields = (
        ("Entry Zone", view["entry_zone"]),
        ("Confirmation", view["confirmation_level"]),
        ("Maximum Entry", view["maximum_entry"]),
        ("Initial Stop", view["initial_stop"]),
        ("Target 1", view["target_1"]),
        ("Target 2", view["target_2"]),
        ("Risk / Reward", view["risk_reward"]),
        ("Confidence", view["confidence"]),
    )
    for index, (label, value) in enumerate(fields):
        columns[index % 4].metric(label, value)
    st_module.caption(
        f"Late-entry risk: {view['late_entry_risk']} · "
        f"Current hold: {view['hold_time']} · Maximum hold: {view['maximum_hold']} · "
        f"Signal: {view['signal_time']}"
    )
    st_module.write(f"**Breakeven:** {view['breakeven_rule']}")
    st_module.write(f"**Trailing stop:** {view['trailing_rule']}")
    if plan.status in {PlanStatus.WAIT, PlanStatus.WATCH}:
        st_module.markdown("**What needs to happen next**")
        for item in view["missing_requirements"] or ["Setup confirmation is still developing"]:
            st_module.write(f"- {item}")
        st_module.markdown("**Activate if**")
        for item in view["activation_requirements"] or ["All confirmation and risk requirements are satisfied"]:
            st_module.write(f"- {item}")
    with st_module.expander("Trade Plan Details"):
        for title, items in (
            ("Why now", view["reasons_for_trade"]),
            ("Reasons to avoid", view["reasons_to_avoid"]),
            ("Invalidate if", view["invalidation_conditions"]),
        ):
            st_module.markdown(f"**{title}**")
            for item in items or ["None identified"]:
                st_module.write(f"- {item}")
        st_module.caption(f"Latest lifecycle event: {view['latest_event']}")
        if plan.status == PlanStatus.CLOSED:
            st_module.write(f"**Final outcome:** {view['final_outcome']}")
    return view
