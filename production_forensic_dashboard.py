"""Query-on-demand Streamlit presentation for production forensic analytics."""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from analysis.production_forensic_access import database_fingerprint, run_production_audit
from dashboard_storage_config import dashboard_database_url


EASTERN = ZoneInfo("America/New_York")
AUDIT_RESULT_KEY = "post_run_forensic_audit_result"
SENSITIVE_KEY_PARTS = ("database_url", "connection_string", "password", "passwd", "secret", "api_key", "access_token", "authorization")


def forensic_export_payload(result):
    """Return a complete JSON export with sensitive fields recursively removed."""
    return _sanitize(result)


def forensic_export_json(result):
    return json.dumps(forensic_export_payload(result), indent=2, sort_keys=True, default=str)


def forensic_export_filename(now=None):
    value = now or datetime.now(EASTERN)
    if value.tzinfo is None:
        value = value.replace(tzinfo=EASTERN)
    return f"optionbeacon_forensic_audit_{value.astimezone(EASTERN).date().isoformat()}.json"


def _sanitize(value):
    if isinstance(value, dict):
        return {str(key): _sanitize(item) for key, item in value.items()
                if not any(part in str(key).lower() for part in SENSITIVE_KEY_PARTS)}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith(("{", "[")):
            try:
                return _sanitize(json.loads(stripped))
            except (TypeError, json.JSONDecodeError):
                pass
        if "://" in stripped and "@" in stripped:
            return "[REDACTED CONNECTION STRING]"
    return value


def render_production_forensic_audit(st, *, database_resolver=dashboard_database_url, audit_runner=run_production_audit):
    with st.expander("POST-RUN FORENSIC AUDIT", expanded=False):
        st.warning("READ ONLY — production analytics")
        st.caption("Queries run only after explicit confirmation. No provider calls, trading actions, or database writes.")
        clicked = st.button("Run production forensic audit", key="run_production_forensic_audit")
        result = st.session_state.get(AUDIT_RESULT_KEY)
        if clicked:
            url = database_resolver(st)
            if not url:
                st.error("Production database configuration is unavailable.")
                return None
            try:
                with st.spinner("Running read-only production forensic audit..."):
                    result = audit_runner(url, dashboard_fingerprint=database_fingerprint(url))
                st.session_state[AUDIT_RESULT_KEY] = result
            except Exception:
                st.error("Production forensic audit could not establish or complete its read-only database operation. Check sanitized server logs.")
                return None
        if result is None:
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
        st.download_button("Download Full Forensic Report", forensic_export_json(result),
                           file_name=forensic_export_filename(), mime="application/json",
                           key="download_full_forensic_report")
        return result
