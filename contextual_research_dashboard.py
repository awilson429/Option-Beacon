"""Compact on-demand Phase 2 contextual research UI."""
import math
import pandas as pd
from contextual_research import ContextualResearchRepository


def render_contextual_research(st, repository):
    st.markdown("### Contextual Decision & Position Research")
    st.caption("Shadow research only — cannot open, close, size, or modify a trade.")
    if repository is None:
        st.caption("Research storage unavailable."); return None
    scope=st.selectbox("Phase 2 scope",("FORWARD TEST","DEVELOPMENT","ALL"),key="phase2_scope")
    if not st.button("Load Phase 2 Research",key="load_phase2_research"):
        st.caption("On-demand only to keep Neon egress bounded."); return None
    try:report=ContextualResearchRepository(repository).load(scope=scope,limit=5000)
    except Exception:
        st.caption("Phase 2 research is unavailable.");return None
    st.metric("Context envelopes",report["contexts"]);st.metric("Position context marks",report["marks"])
    for title,key in (("Research Evidence Coverage","coverage"),("CONTEXT_SHADOW Decisions","context_shadow"),
        ("Setup Health","setup_health"),("Early vs Confirmed Timing","timing"),("Market Regimes","regimes"),
        ("Sector Relative Strength","relative_strength"),("Multi-Timeframe Alignment","multi_timeframe"),
        ("RelVol × Spread","relvol_spread"),("Options Execution Attribution","option_execution"),
        ("Predeclared Interactions","interactions"),("Pullback / Reclaim","structures"),("Discovery Provenance","provenance"),
        ("Entry → Current → Exit Deltas","deltas"),("Adaptive Exit Shadow Triggers","shadow_exits")):
        with st.expander(title,expanded=key=="coverage"):
            value=report.get(key)
            if isinstance(value,dict):value=[{"value":k,"N":v} for k,v in value.items()]
            st.dataframe(pd.DataFrame([_display(row) for row in (value or [])]),use_container_width=True,hide_index=True)
    st.caption("LLM synthesis: DISABLED — no existing low-cost integration was suitable; deterministic system remains final authority.")
    return report


def _display(row):
    return {key:"—" if value is None else "∞" if isinstance(value,float) and math.isinf(value) else value for key,value in row.items() if key not in {"entry","best","worst","exit"}}
