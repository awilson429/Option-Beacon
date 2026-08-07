"""Read-only Streamlit presentation for the SPY / QQQ experimental lane."""

from __future__ import annotations

import json

import pandas as pd

from intraday_execution import IntradayRepository


def intraday_dashboard_model(repository):
    ledger = IntradayRepository(repository, initialize=False)
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
            "performance": ledger.performance(), "runtime": ledger.runtime_state()}


def render_intraday_page(repository, st_module=None):
    if st_module is None:
        import streamlit as st_module
    st_module.markdown("## SPY / QQQ Intraday")
    st_module.caption("Experimental paper-only lane · 0DTE + 1DTE · no live execution")
    try:
        model = intraday_dashboard_model(repository)
    except Exception as exc:
        st_module.warning(f"Intraday persistence is not available yet: {type(exc).__name__}")
        return
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
    st_module.markdown("### Active / Armed Setups")
    if model["setups"]:
        st_module.dataframe(pd.DataFrame([{ "Symbol": row["symbol"], "Direction": row["direction"],
            "Setup": row["setup"], "Confidence": row["confidence"], "Trigger": row["trigger_price"],
            "Current": row["underlying_price"], "Distance": abs(float(row["trigger_price"]) - float(row["underlying_price"])),
            "Session": row["session_bucket"], "Status": row["state"]} for row in model["setups"]]),
            use_container_width=True, hide_index=True)
    else: st_module.caption("No active setup is currently armed.")
    st_module.markdown("### Current Paper Positions")
    mirror, managed = st_module.columns(2)
    mirror.markdown("**INTRADAY MIRROR**")
    managed.markdown("**INTRADAY MANAGED**")
    mirror.dataframe(pd.DataFrame(model["mirror"]), use_container_width=True, hide_index=True) if model["mirror"] else mirror.caption("No open positions.")
    managed.dataframe(pd.DataFrame(model["managed"]), use_container_width=True, hide_index=True) if model["managed"] else managed.caption("No open positions.")
    st_module.markdown("### Today Performance")
    st_module.dataframe(pd.DataFrame([{"Exit model": key.replace("INTRADAY_", "").title(), **value}
                                      for key, value in model["performance"].items()]),
                        use_container_width=True, hide_index=True)
