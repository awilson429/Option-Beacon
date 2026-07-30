"""Pure dashboard reliability-state presentation helpers."""

from __future__ import annotations


def reliability_status_model(
    trade_state,
    *,
    market_open,
    latest_results=None,
    open_trade_count=0,
    commit="unknown",
):
    latest_results = latest_results or {}
    storage = trade_state.get("storage_state", "UNAVAILABLE")
    scanner = trade_state.get("scanner_state", "UNKNOWN")
    market_data = trade_state.get("market_data_state", "UNKNOWN")
    if storage == "UNAVAILABLE":
        severity = "error"
        summary = (
            "Trade storage is unavailable. Open-trade information may be incomplete."
        )
    elif scanner == "ERROR":
        severity = "error"
        summary = trade_state.get("message") or "The latest scanner run failed."
    elif scanner in {"STALE", "NEVER RUN", "UNKNOWN"}:
        severity = "warning"
        summary = trade_state.get("message") or "Scanner state is unknown."
    elif market_open and _market_data_unavailable(latest_results):
        severity = "warning"
        market_data = "UNAVAILABLE"
        summary = "Market data is unavailable. Scanner results may be incomplete."
    elif not market_open:
        severity = "neutral"
        summary = "Market is closed. The most recent successful scan is retained."
    elif open_trade_count:
        severity = "success"
        summary = (
            f"{open_trade_count} open "
            f"{'trade' if open_trade_count == 1 else 'trades'}. "
            + (trade_state.get("message") or "")
        ).strip()
    else:
        severity = "neutral"
        summary = "No open trades. " + (trade_state.get("message") or "")
    return {
        "severity": severity,
        "summary": summary.strip(),
        "last_success_at": trade_state.get("last_success_at"),
        "age_minutes": trade_state.get("age_minutes"),
        "scanner_state": scanner,
        "storage_state": storage,
        "market_data_state": market_data,
        "commit": commit,
    }


def _market_data_unavailable(results):
    if not results:
        return True
    return all(
        str((result or {}).get("signal") or "").upper() == "DATA UNAVAILABLE"
        for result in results.values()
    )
