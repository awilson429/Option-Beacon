"""Compact, read-only Opportunity Context Attribution UI."""
import math
import pandas as pd
from opportunity_context import OpportunityContextAnalyticsRepository


def render_opportunity_context_attribution(st, repository):
    st.markdown("### Opportunity Context Attribution")
    st.caption("Deterministic research only — context does not alter any trading decision.")
    if repository is None:
        st.caption("Context storage unavailable.")
        return None
    scope = st.selectbox("Context analysis scope", ("FORWARD TEST", "DEVELOPMENT", "ALL"), key="context_scope")
    if not st.button("Load Opportunity Context Attribution", key="load_context_attribution"):
        st.caption("Load on demand to keep database egress bounded.")
        return None
    try:
        report = OpportunityContextAnalyticsRepository(repository).load(scope=scope, limit=5000)
    except Exception:
        st.caption("Opportunity context analytics are unavailable.")
        return None
    with st.expander("Opportunity Context Coverage", expanded=True):
        st.dataframe(pd.DataFrame([_display(row) for row in report["coverage"]]), use_container_width=True, hide_index=True)
    with st.expander("Context Attribution", expanded=False):
        st.dataframe(pd.DataFrame([_display(row) for row in report["factors"]]), use_container_width=True, hide_index=True)
    with st.expander("Predeclared Interaction Tests", expanded=False):
        st.dataframe(pd.DataFrame([_display(row) for row in report["interactions"]]), use_container_width=True, hide_index=True)
    st.caption("INSUFFICIENT DATA / UNSTABLE / PROMISING use chronological development-to-forward validation; no finding is promoted automatically.")
    return report


def _display(row):
    return {key: "—" if value is None else "∞" if isinstance(value, float) and math.isinf(value) else value for key, value in row.items()}
