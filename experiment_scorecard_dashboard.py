"""Compact read-only Streamlit presentation for experiment scorecards."""
import math
import pandas as pd
from experiment_scorecard import ExperimentScorecardRepository


def render_experiment_scorecard(st,repository):
    st.markdown("### Experiment Scorecard")
    if repository is None:
        st.caption("—")
        return None
    period=st.selectbox("Experiment period",("FORWARD TEST","DEVELOPMENT","ALL"),key="experiment_scorecard_period")
    window=st.selectbox("Session history",(5,10,20,"ALL"),index=1,key="experiment_scorecard_sessions")
    try: report=ExperimentScorecardRepository(repository).load(session_limit=None if window=="ALL" else window,period=period)
    except Exception:
        st.caption("Experiment scorecard data is unavailable.")
        return None
    if not report["daily"]:
        st.caption("No experiment sessions in this scope.")
        return report
    selected=st.selectbox("Selected session",list(reversed(report["sessions"])),key="experiment_scorecard_selected_session")
    day=next(item for item in report["daily"] if item["session"]==selected)
    st.dataframe(pd.DataFrame([{"Lane":lane,**{k:_display(v) for k,v in metrics.items()}} for lane,metrics in day["lanes"].items()]),use_container_width=True,hide_index=True)
    history=[]
    for item in reversed(report["daily"]):
        history.append({"Date":item["session"],**{f"{lane} P&L":_display(metrics["realized_pnl"]) for lane,metrics in item["lanes"].items()},
            **{f"{lane} Trades":metrics["closed"] for lane,metrics in item["lanes"].items()}})
    st.markdown("#### Session History")
    st.dataframe(pd.DataFrame(history),use_container_width=True,hide_index=True)
    with st.expander("Session detail",expanded=False):
        detail=[]
        for item in reversed(report["daily"]):
            for lane,metrics in item["lanes"].items():detail.append({"Date":item["session"],"Lane":lane,**{k:_display(metrics[k]) for k in ("win_rate","profit_factor","participation_rate","peak_capital","return_on_peak_capital")}})
        st.dataframe(pd.DataFrame(detail),use_container_width=True,hide_index=True)
    st.markdown("#### Cumulative Summary")
    st.dataframe(pd.DataFrame([{"Lane":lane,**{k:_display(v) for k,v in metrics.items()}} for lane,metrics in report["cumulative"].items()]),use_container_width=True,hide_index=True)
    with st.expander("FILTERED Spread Gate — SHADOW / COUNTERFACTUAL",expanded=False):
        st.dataframe(pd.DataFrame([{k:_display(v) for k,v in report["spread_gate"].items()}]),use_container_width=True,hide_index=True)
    with st.expander("Signal Age — observational only",expanded=False):
        st.dataframe(pd.DataFrame([{k:_display(v) for k,v in row.items()} for row in report["signal_age"]]),use_container_width=True,hide_index=True)
    st.caption(f'FILTERED governance: {report["governance"]}')
    return report


def _display(value):
    if value is None:return "—"
    if isinstance(value,float) and math.isinf(value):return "∞"
    return value
