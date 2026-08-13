"""Query-on-demand Streamlit presentation for production forensic analytics."""

from __future__ import annotations

import json

import pandas as pd

from analysis.production_forensic_access import database_fingerprint, run_production_audit
from dashboard_storage_config import dashboard_database_url


def render_production_forensic_audit(st, *, database_resolver=dashboard_database_url, audit_runner=run_production_audit):
    with st.expander("POST-RUN FORENSIC AUDIT", expanded=False):
        st.warning("READ ONLY — production analytics")
        st.caption("Queries run only after explicit confirmation. No provider calls, trading actions, or database writes.")
        if not st.button("Run production forensic audit", key="run_production_forensic_audit"):
            return None
        url = database_resolver(st)
        if not url:
            st.error("Production database configuration is unavailable.")
            return None
        try:
            with st.spinner("Running read-only production forensic audit..."):
                result = audit_runner(url, dashboard_fingerprint=database_fingerprint(url))
        except Exception:
            st.error("Production forensic audit could not establish or complete its read-only database operation. Check sanitized server logs.")
            return None
        identity = result["database"]
        st.caption(f'{identity["engine"]} · schema {identity["schema"]} · fingerprint {identity["fingerprint"]} · {identity["durability"]}')
        st.dataframe(pd.DataFrame([{"Table": table, **status} for table, status in identity["table_presence"].items()]),
                     use_container_width=True, hide_index=True)
        st.markdown("#### Live-dashboard reconciliation")
        st.json(result["reconciliation"])
        st.markdown("#### Sessions")
        st.json(result["sessions"])
        if result["status"] != "COMPLETED":
            st.error(f'Audit stopped: {result["reason"]}. No performance findings were generated.')
            return result
        st.markdown("#### Pairing")
        st.json(result["pairing"])
        st.markdown("#### Forensic report")
        st.json(result["report"])
        st.download_button("Download audit JSON", json.dumps(result, indent=2, default=str),
                           file_name="optionbeacon-production-forensic-audit.json", mime="application/json")
        return result
