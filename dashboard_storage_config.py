"""Streamlit-only configuration adapter for authoritative trade storage."""

from __future__ import annotations

import os


def dashboard_database_url(st_module=None) -> str:
    """Resolve the dashboard URL without making it a worker-side fallback."""
    value = os.getenv("DATABASE_URL", "").strip()
    if value:
        return value
    try:
        if st_module is None:
            import streamlit as st_module
        return str(st_module.secrets.get("DATABASE_URL") or "").strip()
    except Exception:
        return ""
