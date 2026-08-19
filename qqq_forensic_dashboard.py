"""Explicit, cached Streamlit surface for production QQQ forensics."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from analysis.production_forensic_access import database_fingerprint
from analysis.production_qqq_forensic_audit import QQQForensicAuditFailure, run_production_qqq_forensic_audit
from dashboard_storage_config import dashboard_database_url
from production_forensic_dashboard import _sanitize

EASTERN=ZoneInfo("America/New_York")
RESULT_KEY="production_qqq_winner_dna_exit_forensics_result"

def qqq_forensic_export_json(result): return json.dumps(_sanitize(result),indent=2,sort_keys=True,default=str,allow_nan=False)
def qqq_forensic_export_filename(now=None):
    value=now or datetime.now(EASTERN)
    if value.tzinfo is None: value=value.replace(tzinfo=EASTERN)
    return f"optionbeacon_qqq_winner_dna_exit_forensics_{value.astimezone(EASTERN).date().isoformat()}.json"

def render_production_qqq_forensic_audit(st, *, database_resolver=dashboard_database_url, audit_runner=run_production_qqq_forensic_audit):
    with st.expander("QQQ WINNER DNA / EXIT FORENSICS",expanded=False):
        st.warning("READ ONLY — PRODUCTION ANALYTICS")
        st.caption("Runs only on explicit request against the live dashboard database.")
        clicked=st.button("Run Production QQQ Forensic Audit",key="run_production_qqq_forensic_audit")
        result=st.session_state.get(RESULT_KEY)
        if clicked:
            url=database_resolver(st)
            if not url: st.error("Production database configuration is unavailable."); return None
            try:
                with st.spinner("Running read-only production QQQ forensic audit..."):
                    result=audit_runner(url,dashboard_fingerprint=database_fingerprint(url))
                st.session_state[RESULT_KEY]=result
            except QQQForensicAuditFailure as error: st.error(str(error)); return None
            except Exception: st.error("Production QQQ forensic audit could not complete. Check sanitized server logs."); return None
        if result is None: return None
        st.caption(f'postgresql · schema public · fingerprint {result["database"]["fingerprint"]} · DURABLE')
        st.markdown("#### Production reconciliation"); st.json(result["reconciliation"])
        if result["status"] != "COMPLETED": st.error(f'Audit stopped: {result["reason"]}.'); return result
        st.markdown("#### QQQ winner DNA / exit forensic report"); st.json(result["report"])
        st.download_button("Download Full QQQ Forensic Report",qqq_forensic_export_json(result),file_name=qqq_forensic_export_filename(),mime="application/json",key="download_full_qqq_forensic_audit")
        return result
