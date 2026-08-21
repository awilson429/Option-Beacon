"""On-demand Streamlit surface for the whole-app value audit."""
from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from dashboard_storage_config import dashboard_database_url
from production_forensic_dashboard import _sanitize
from whole_app_audit import run_whole_app_audit

EASTERN=ZoneInfo("America/New_York")
RESULT_KEY="whole_app_audit_result"


def whole_app_audit_json(result):
    return json.dumps(_sanitize(result),indent=2,sort_keys=True,default=str)


def render_whole_app_audit(st, *, database_resolver=dashboard_database_url, audit_runner=run_whole_app_audit):
    with st.expander("WHOLE APP AUDIT",expanded=False):
        st.warning("READ ONLY — PRODUCT / STRATEGY VALUE REVIEW")
        st.caption("Runs only on explicit request. Recommendations do not hide, archive, retire, or change any system.")
        clicked=st.button("Run Whole App Audit",key="run_whole_app_audit")
        result=st.session_state.get(RESULT_KEY)
        if clicked:
            url=database_resolver(st)
            if not url:
                st.error("Production database configuration is unavailable.");return None
            try:
                with st.spinner("Reviewing whole-app evidence in a read-only transaction..."):
                    result=audit_runner(url)
                st.session_state[RESULT_KEY]=result
            except Exception:
                st.error("Whole App Audit could not complete. No application state was changed.");return None
        if result is None:return None
        st.markdown("#### Classification summary");st.json(result["classification_counts"])
        st.markdown("#### Recommendations");st.json(result["recommendations"])
        st.markdown("#### Complete component inventory");st.json(result["components"])
        filename=f'optionbeacon_whole_app_audit_{datetime.now(EASTERN).date().isoformat()}.json'
        st.download_button("Download Whole App Audit",whole_app_audit_json(result),file_name=filename,
            mime="application/json",key="download_whole_app_audit")
        return result
