"""Explicit, cached Streamlit surface for the production strategic audit."""
from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from analysis.production_forensic_access import database_fingerprint
from analysis.production_strategic_audit import StrategicAuditFailure, run_production_strategic_audit
from dashboard_storage_config import dashboard_database_url
from production_forensic_dashboard import _sanitize

EASTERN = ZoneInfo("America/New_York")
RESULT_KEY = "production_spy_qqq_strategic_audit_result"


def strategic_export_json(result):
    return json.dumps(_sanitize(result), indent=2, sort_keys=True, default=str)


def strategic_export_filename(now=None):
    value = now or datetime.now(EASTERN)
    if value.tzinfo is None: value = value.replace(tzinfo=EASTERN)
    return f"optionbeacon_spy_qqq_strategic_audit_{value.astimezone(EASTERN).date().isoformat()}.json"


def render_production_strategic_audit(st, *, database_resolver=dashboard_database_url,
                                      audit_runner=run_production_strategic_audit):
    with st.expander("SPY / QQQ STRATEGIC AUDIT", expanded=False):
        st.warning("READ ONLY — production analytics")
        st.caption("Runs only on explicit request against the same database resolver as the live dashboard.")
        clicked = st.button("Run Production SPY / QQQ Strategic Audit", key="run_production_spy_qqq_strategic_audit")
        result = st.session_state.get(RESULT_KEY)
        if clicked:
            url = database_resolver(st)
            if not url:
                st.error("Production database configuration is unavailable.")
                return None
            try:
                with st.spinner("Running read-only production strategic audit..."):
                    result = audit_runner(url, dashboard_fingerprint=database_fingerprint(url))
                st.session_state[RESULT_KEY] = result
            except StrategicAuditFailure as error:
                st.error(str(error))
                return None
            except Exception:
                st.error("Production strategic audit could not complete. Check sanitized server logs.")
                return None
        if result is None: return None
        st.caption(f'postgresql · schema public · fingerprint {result["database"]["fingerprint"]} · DURABLE')
        st.markdown("#### Production reconciliation")
        st.json(result["reconciliation"])
        st.markdown("#### Eastern sessions")
        st.json(result["sessions"])
        if result["status"] != "COMPLETED":
            st.error(f'Audit stopped: {result["reason"]}. No strategic conclusion was generated.')
            return result
        st.markdown("#### Strategic report")
        st.json(result["report"])
        st.download_button("Download Full Strategic Audit", strategic_export_json(result),
            file_name=strategic_export_filename(), mime="application/json", key="download_full_strategic_audit")
        return result
