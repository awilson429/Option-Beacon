"""Read-only Streamlit presentation for the SPY / QQQ experimental lane."""

from __future__ import annotations

import json
import logging
import os

import pandas as pd

from intraday_execution import IntradayRepository
from optionbeacon.worker.database_diagnostics import sanitize_database_diagnostic_text


LOGGER = logging.getLogger(__name__)


def intraday_dashboard_model(repository):
    ledger = IntradayRepository(repository, initialize=False)
    status = ledger.table_status()
    if not status["initialized"]:
        return {"symbols": {"SPY": None, "QQQ": None}, "setups": [],
                "mirror": [], "managed": [], "performance": {}, "runtime": None,
                "persistence_state": "NOT_INITIALIZED", **status}
    signals = ledger.list_signals()
    open_trades = ledger.list_trades(status="OPEN")
    latest = {}
    for signal in signals:
        latest.setdefault(signal["symbol"], signal)
        try: signal["reasons"] = json.loads(signal.get("reasons_json") or "[]")
        except (TypeError, ValueError): signal["reasons"] = []
    return {"symbols": {symbol: latest.get(symbol) for symbol in ("SPY", "QQQ")},
            "setups": [row for row in signals if row.get("state") in {"SETUP_DETECTED", "ARMED", "TRIGGERED"}],
            "mirror": [row for row in open_trades if row.get("variant") == "INTRADAY_MIRROR"],
            "managed": [row for row in open_trades if row.get("variant") == "INTRADAY_MANAGED"],
            "performance": ledger.performance(), "runtime": ledger.runtime_state(),
            "persistence_state": "AVAILABLE", **status}


def render_intraday_page(repository, st_module=None):
    if st_module is None:
        import streamlit as st_module
    st_module.markdown("## SPY / QQQ Intraday")
    st_module.caption("Experimental paper-only lane · 0DTE + 1DTE · no live execution")
    try:
        model = intraday_dashboard_model(repository)
    except Exception as exc:
        cause = exc.__cause__ or exc
        record = {
            "event": "intraday_repository_unavailable",
            "failure_stage": "read_probe",
            "exception_class": type(cause).__name__,
            "sanitized_message": sanitize_database_diagnostic_text(str(cause))[:240],
            "database_url_present": bool(os.getenv("DATABASE_URL", "").strip()),
            "repository_construction_succeeded": repository is not None,
            "schema_read_probe_succeeded": False,
        }
        LOGGER.exception(json.dumps(record, sort_keys=True))
        st_module.warning("Intraday persistence is temporarily unavailable. See sanitized application logs.")
        return
    if model["persistence_state"] == "NOT_INITIALIZED":
        LOGGER.info(json.dumps({
            "event": "intraday_repository_not_initialized",
            "database_url_present": bool(os.getenv("DATABASE_URL", "").strip()),
            "repository_construction_succeeded": repository is not None,
            "schema_read_probe_succeeded": True,
            "missing_tables": model["missing_tables"],
        }, sort_keys=True))
        st_module.info("Intraday storage has not been initialized by the worker yet.")
    columns = st_module.columns(2)
    for column, symbol in zip(columns, ("SPY", "QQQ")):
        row = model["symbols"].get(symbol)
        column.markdown(f"### {symbol}")
        if not row:
            column.caption("Waiting for the intraday worker.")
            continue
        column.metric("Price", f"${float(row['underlying_price']):,.2f}")
        column.caption(f"{row['regime']} · {row['session_bucket']} · {row['state']}")
        column.markdown(f"**{row['direction']} · {row['setup']}** — Confidence {row['confidence']}")
        reasons = json.loads(row.get("reasons_json") or "[]")
        if reasons: column.markdown("Why: " + " · ".join(f"✓ {reason}" for reason in reasons))
    st_module.markdown("### Active Setup")
    if model["setups"]:
        st_module.dataframe(pd.DataFrame([{ "Symbol": row["symbol"], "Direction": row["direction"],
            "Setup": row["setup"], "Confidence": row["confidence"], "Trigger": row["trigger_price"],
            "Current": row["underlying_price"], "Distance": abs(float(row["trigger_price"]) - float(row["underlying_price"])),
            "Session": row["session_bucket"], "Status": row["state"]} for row in model["setups"]]),
            use_container_width=True, hide_index=True)
    else: st_module.caption("No active setup is currently armed.")
    st_module.markdown("### Open Positions")
    positions=[{"Lane":"MIRROR",**row} for row in model["mirror"]]+[{"Lane":"MANAGED",**row} for row in model["managed"]]
    if positions:
        visible=[{key:value for key,value in row.items() if key not in {"trade_id","opportunity_id","metadata_json"}} for row in positions]
        st_module.dataframe(pd.DataFrame(visible),use_container_width=True,hide_index=True)
    else:
        st_module.caption("No open SPY/QQQ positions.")
    st_module.markdown("### Performance")
    st_module.dataframe(pd.DataFrame([{"Exit model": key.replace("INTRADAY_", "").title(), **value}
                                      for key, value in model["performance"].items()]),
                        use_container_width=True, hide_index=True)
    if callable(getattr(st_module,"expander",None)):
        with st_module.expander("Advanced / Runtime",expanded=False):
            st_module.json(model.get("runtime") or {"status":"Unavailable"})
