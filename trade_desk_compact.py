"""Pure presentation models for the compact, read-only Trade Desk."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape

from live_trade_activity import activity_rows, meaningful_events, relative_age


ACTIVITY_FILTERS = ("ALL", "ENTRIES", "EXITS", "SIGNALS")
ENTRY_EVENTS = {"TRADE_ENTERED"}
EXIT_EVENTS = {
    "TARGET_REACHED", "STOP_REACHED", "TRADE_CLOSED", "END_OF_DAY_EXIT",
    "MAX_HOLD_EXIT", "INVALIDATED",
}
SIGNAL_EVENTS = {"WATCH_CREATED", "ENTRY_READY"}


def status_strip_model(
    reliability_state, *, market_open, paper_active, configured_symbols=0, now=None
):
    state = reliability_state or {}
    scanner = str(state.get("scanner_state") or "UNKNOWN").upper()
    market_data = str(state.get("market_data_state") or "UNKNOWN").upper()
    severity = "healthy"
    if scanner in {"ERROR", "FAILED", "UNAVAILABLE"} or market_data == "UNAVAILABLE":
        severity = "error"
    elif scanner in {"STALE", "NEVER RUN"} or market_data in {"PARTIAL", "UNKNOWN"}:
        severity = "warning"
    processed = int(state.get("last_symbols_processed") or 0)
    scan_time = state.get("last_success_at")
    return {
        "severity": severity,
        "market": "MARKET OPEN" if market_open else "MARKET CLOSED",
        "scanner": "SCANNER HEALTHY" if severity == "healthy" else f"SCANNER {scanner}",
        "paper": "PAPER ACTIVE" if paper_active else "PAPER DISABLED",
        "last_scan": f"LAST SCAN {relative_age(scan_time, now).upper()}" if scan_time else "LAST SCAN —",
        "symbols": f"{processed}/{configured_symbols} SYMBOLS" if configured_symbols else f"{processed} SYMBOLS",
    }


def status_strip_markup(model):
    pills = "".join(
        f'<span class="ob-desk-status-pill">{escape(str(model[key]))}</span>'
        for key in ("market", "scanner", "paper", "last_scan", "symbols")
    )
    return f'<div class="ob-desk-status ob-desk-status-{model["severity"]}">{pills}</div>'


def today_summary_model(scorecard, paper_summary=None, *, paper_available=False):
    if paper_available:
        paper = paper_summary or {}
        return {
            "source": "PAPER",
            "pnl": float(paper.get("today_pnl") or 0),
            "open_positions": int(paper.get("open_positions") or 0),
            "trades_today": int(paper.get("trades_today") or 0),
            "wins": int(paper.get("wins") or 0),
            "losses": int(paper.get("losses") or 0),
            "win_rate": float(paper.get("win_rate") or 0),
            "deployed_capital": float(paper.get("deployed_capital") or 0),
        }
    score = scorecard or {}
    return {
        "source": "AUTHORITATIVE",
        "pnl": None,
        "open_positions": int(score.get("open_positions") or 0),
        "trades_today": int(score.get("opened_alerts") or 0),
        "wins": int(score.get("winners") or 0),
        "losses": int(score.get("losers") or 0),
        "win_rate": score.get("win_rate"),
        "deployed_capital": None,
    }


def paper_active_row(position, now):
    quantity = int(position.quantity or 1)
    pnl = (position.current_mid - position.entry_mid) * 100 * quantity
    elapsed = max(0, int((now - position.entry_time).total_seconds()))
    minutes, seconds = divmod(elapsed, 60)
    return {
        "identity": position.trade_id,
        "symbol": position.ticker,
        "contract": position.option_symbol,
        "direction": position.direction,
        "state": "ACTIVE",
        "pnl_dollars": round(pnl, 2),
        "pnl_percent": position.current_return_percent,
        "duration": f"{minutes}m {seconds:02d}s",
        "entry": position.entry_mid,
        "current": position.current_mid,
        "quantity": quantity,
        "mfe": position.max_favorable_excursion_percent,
        "mae": position.max_adverse_excursion_percent,
        "opened_at": position.entry_time,
        "source": "PAPER",
    }


def paper_position_events(positions):
    events = []
    for position in positions:
        base = {
            "trade_id": position.trade_id,
            "symbol": position.ticker,
            "direction": position.direction,
            "option_symbol": position.option_symbol,
            "entry_price": position.entry_mid,
            "metadata": {"quantity": position.quantity},
        }
        events.append({
            **base, "event_type": "TRADE_ENTERED",
            "event_timestamp": position.entry_time,
            "underlying_price": position.entry_mid,
            "description": f"Entered {position.option_symbol}",
        })
        if position.exit_time is not None:
            events.append({
                **base, "event_type": "TRADE_CLOSED",
                "event_timestamp": position.exit_time,
                "underlying_price": position.exit_mid,
                "realized_return": position.exit_return_percent,
                "exit_reason": position.exit_reason,
                "description": f"Closed {position.option_symbol}: {position.exit_reason}",
            })
    return events


def filtered_activity_rows(events, *, selected="ALL", now=None, view_all=False, limit=8):
    selected = selected if selected in ACTIVITY_FILTERS else "ALL"
    ordered = sorted(
        events,
        key=lambda event: _timestamp(event.get("event_timestamp")),
        reverse=True,
    )
    if selected != "ALL":
        allowed = {
            "ENTRIES": ENTRY_EVENTS,
            "EXITS": EXIT_EVENTS,
            "SIGNALS": SIGNAL_EVENTS,
        }[selected]
        ordered = [event for event in ordered if event.get("event_type") in allowed]
    deduplicated, seen = [], set()
    for event in ordered:
        event_type = event.get("event_type")
        family = (
            "ENTRY" if event_type in ENTRY_EVENTS else
            "EXIT" if event_type in EXIT_EVENTS else
            "SIGNAL" if event_type in SIGNAL_EVENTS else event_type
        )
        event_timestamp = _timestamp(event.get("event_timestamp"))
        semantic_key = (
            str(event.get("symbol") or "").upper(),
            family,
            int(event_timestamp) if event_timestamp != float("-inf") else "missing",
        )
        if semantic_key in seen:
            continue
        seen.add(semantic_key)
        deduplicated.append(event)
    selected_events = meaningful_events(deduplicated, limit=1000 if view_all else limit)
    rows = activity_rows(
        selected_events,
        now=now,
        limit=1000 if view_all else limit,
    )
    for row, event in zip(rows, selected_events):
        row["Contract"] = event.get("option_symbol") or "—"
    return rows


def _timestamp(value):
    if not value:
        return float("-inf")
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(
        str(value).replace("Z", "+00:00")
    )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()
