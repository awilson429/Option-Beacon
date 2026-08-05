"""Pure presentation models for the compact, read-only Trade Desk."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
import math

from live_trade_activity import activity_rows, meaningful_events, relative_age


ACTIVITY_FILTERS = ("ALL", "ENTRIES", "EXITS", "SIGNALS")
ENTRY_EVENTS = {"TRADE_ENTERED"}
EXIT_EVENTS = {
    "TARGET_REACHED", "STOP_REACHED", "TRADE_CLOSED", "END_OF_DAY_EXIT",
    "MAX_HOLD_EXIT", "INVALIDATED",
}
SIGNAL_EVENTS = {"WATCH_CREATED", "ENTRY_READY"}


def status_strip_model(
    reliability_state, *, market_open, paper_active, configured_symbols=0,
    paper_profile=None, now=None,
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
    if severity == "healthy" and processed == 0:
        severity = "warning"
    elif severity == "healthy" and configured_symbols and processed < configured_symbols:
        severity = "warning"
    scan_time = state.get("last_success_at")
    scanner_label = (
        "SCANNER CURRENT" if severity == "healthy" else
        "SCANNER AWAITING DATA" if processed == 0 and scanner not in {"ERROR", "FAILED", "UNAVAILABLE"} else
        "SCANNER PARTIAL" if configured_symbols and 0 < processed < configured_symbols else
        f"SCANNER {scanner}"
    )
    profile = str(paper_profile or "").upper()
    return {
        "severity": severity,
        "market": "MARKET OPEN" if market_open else "MARKET CLOSED",
        "scanner": scanner_label,
        "paper": f"PAPER {profile} ACTIVE" if paper_active and profile else "PAPER ACTIVE" if paper_active else "PAPER DISABLED",
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


def dashboard_kpi_model(scorecard, paper_summary, config, *, paper_available):
    """Build the five non-duplicated top-line metrics from authoritative state."""
    today = today_summary_model(
        scorecard, paper_summary, paper_available=paper_available
    )
    if paper_available:
        return {
            "source": "PAPER",
            "current_equity": paper_summary["current_equity"],
            "today_pnl": paper_summary["today_pnl"],
            "open_positions": paper_summary["open_positions"],
            "max_open_positions": config.max_open_positions,
            "daily_loss_remaining": paper_summary["daily_loss_remaining"],
            "deployed_capital": paper_summary["deployed_capital"],
            "max_deployed_capital": config.max_total_deployed_capital,
        }
    return {
        "source": "AUTHORITATIVE",
        "current_equity": None,
        "today_pnl": None,
        "open_positions": today["open_positions"],
        "max_open_positions": None,
        "daily_loss_remaining": None,
        "deployed_capital": None,
        "max_deployed_capital": None,
    }


def risk_status_model(paper_summary, config, *, paper_available):
    if not paper_available:
        return {"available": False, "items": []}
    limits = (
        ("Daily Loss", max(0, -paper_summary["realized_pnl"]), config.max_daily_loss_dollars,
         f'${paper_summary["daily_loss_remaining"]:,.2f} remaining'),
        ("Capital Deployed", paper_summary["deployed_capital"], config.max_total_deployed_capital,
         f'${paper_summary["deployed_capital"]:,.2f} / ${config.max_total_deployed_capital:,.0f}'),
        ("Daily Trades", paper_summary["trades_today"], config.max_trades_per_day,
         f'{paper_summary["trades_today"]} / {config.max_trades_per_day}'),
        ("Open Positions", paper_summary["open_positions"], config.max_open_positions,
         f'{paper_summary["open_positions"]} / {config.max_open_positions}'),
    )
    items = []
    for label, used, maximum, display in limits:
        percent = min(100.0, max(0.0, used / maximum * 100)) if maximum else 0.0
        treatment = "danger" if percent >= 100 else "warning" if percent >= 80 else "healthy"
        items.append({
            "label": label, "used": used, "maximum": maximum,
            "display": display, "percent": percent, "treatment": treatment,
        })
    return {"available": True, "items": items}


def kpi_row_markup(model):
    def money(value, *, signed=False):
        if value is None:
            return "â€”"
        return f'${value:+,.2f}' if signed else f'${value:,.2f}'

    pnl = model["today_pnl"]
    pnl_treatment = "positive" if (pnl or 0) > 0 else "negative" if (pnl or 0) < 0 else "neutral"
    positions_detail = (
        f'of {model["max_open_positions"]} max'
        if model["max_open_positions"] is not None else model["source"]
    )
    deployed_detail = (
        f'of ${model["max_deployed_capital"]:,.0f} max'
        if model["max_deployed_capital"] is not None else model["source"]
    )
    cards = (
        ("CURRENT EQUITY", money(model["current_equity"]), model["source"], "neutral"),
        ("OPEN POSITIONS", str(model["open_positions"]), positions_detail, "neutral"),
        ("TODAY'S P&L", money(pnl, signed=True), "Realized + unrealized", pnl_treatment),
        ("DAILY LOSS LEFT", money(model["daily_loss_remaining"]), "Remaining", "neutral"),
        ("DEPLOYED CAPITAL", money(model["deployed_capital"]), deployed_detail, "neutral"),
    )
    body = "".join(
        f'<div class="ob-desk-kpi ob-value-{treatment}">'
        f'<div class="ob-desk-kpi-label">{escape(label)}</div>'
        f'<div class="ob-desk-kpi-value">{escape(value)}</div>'
        f'<div class="ob-desk-kpi-detail">{escape(detail)}</div></div>'
        for label, value, detail, treatment in cards
    )
    return f'<div class="ob-desk-kpis">{body}</div>'


def risk_panel_markup(model):
    if not model["available"]:
        return panel_markup("Risk Status", '<div class="ob-desk-empty">PAPER risk state unavailable.</div>')
    rows = "".join(
        f'<div class="ob-risk-row"><div class="ob-risk-line"><span>{escape(item["label"])}</span>'
        f'<span>{escape(item["display"])} <small>{item["percent"]:.0f}%</small></span></div>'
        f'<div class="ob-risk-track"><span class="ob-risk-fill ob-risk-{item["treatment"]}" '
        f'style="width:{item["percent"]:.1f}%"></span></div></div>'
        for item in model["items"]
    )
    return panel_markup("Risk Status", rows)


def performance_panel_markup(summary, paper_summary, *, paper_available):
    if paper_available:
        factor = paper_summary["profit_factor"]
        values = (
            ("Realized P&L", f'${paper_summary["realized_pnl"]:+,.2f}'),
            ("Unrealized P&L", f'${paper_summary["open_pnl"]:+,.2f}'),
            ("Win Rate", f'{paper_summary["win_rate"]:.1f}%'),
            ("Trades Closed", str(paper_summary["trades_closed_today"])),
            ("Profit Factor", "âˆž" if math.isinf(factor) else f'{factor:.2f}'),
        )
    else:
        score = summary or {}
        values = (
            ("Closed Trades", str(score.get("closed_trades", 0))),
            ("Win Rate", _percent_or_dash(score.get("win_rate"))),
            ("Average Return", _percent_or_dash(score.get("average_return"), signed=True)),
            ("Best Trade", _percent_or_dash(score.get("best_trade"), signed=True)),
            ("Profit Factor", _number_or_dash(score.get("profit_factor"))),
        )
    stats = "".join(
        f'<div class="ob-performance-stat"><span>{escape(label)}</span><strong>{escape(value)}</strong></div>'
        for label, value in values
    )
    return panel_markup("Today Performance", f'<div class="ob-performance-grid">{stats}</div>')


def paper_position_rows(positions, config, now):
    rows = []
    for position in sorted(
        (item for item in positions if item.status == "OPEN"),
        key=lambda item: item.entry_time, reverse=True,
    ):
        row = paper_active_row(position, now)
        rows.append({
            **row,
            "type": str(position.option_type or position.direction).upper(),
            "strike_exp": f'{position.strike:g} {position.expiration}',
            "stop": position.entry_mid * (1 + config.stop_loss_percent / 100),
            "target": position.entry_mid * (1 + config.profit_target_percent / 100),
            "score": position.scanner_score,
            "status": position.status,
        })
    return rows


def positions_table_markup(rows):
    if not rows:
        return panel_markup("Open Positions", '<div class="ob-desk-empty">No open positions.</div>')
    headers = ("SYMBOL", "TYPE", "CONTRACT", "ENTRY", "CURRENT", "P&L $", "P&L %", "HOLD", "STATUS", "DETAILS")
    head = "".join(f"<th>{escape(value)}</th>" for value in headers)
    body = []
    for row in rows:
        treatment = "positive" if row["pnl_dollars"] >= 0 else "negative"
        detail = (
            f'Qty {row["quantity"]} · Strike/expiry {row["strike_exp"]} · Stop ${row["stop"]:.2f} · '
            f'Target ${row["target"]:.2f} · MFE {row["mfe"]:+.2f}% · MAE {row["mae"]:+.2f}% · '
            f'Score {row["score"] if row["score"] is not None else "—"}'
        )
        body.append(
            '<tr>'
            f'<td><strong>{escape(row["symbol"])}</strong></td><td>{escape(row["type"])}</td>'
            f'<td>{escape(row["contract"])}</td><td>${row["entry"]:.2f}</td><td>${row["current"]:.2f}</td>'
            f'<td class="ob-value-{treatment}">${row["pnl_dollars"]:+,.2f}</td>'
            f'<td class="ob-value-{treatment}">{row["pnl_percent"]:+.2f}%</td>'
            f'<td>{escape(row["duration"])}</td><td><span class="ob-position-state">OPEN</span></td>'
            f'<td><details><summary>View</summary><div>{escape(detail)}</div></details></td></tr>'
        )
    table = f'<div class="ob-position-scroll"><table class="ob-position-table"><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'
    return panel_markup("Open Positions", table)


def activity_panel_markup(rows, *, show_title=True):
    title = "Recent Activity" if show_title else ""
    if not rows:
        return panel_markup(title, '<div class="ob-desk-empty">No meaningful activity recorded.</div>')
    items = "".join(
        f'<div class="ob-activity-row"><span class="ob-activity-time">{escape(str(row["Time"]))}</span>'
        f'<span class="ob-activity-tag ob-activity-{escape(str(row["Event"]).lower().replace(" ", "-"))}">{escape(str(row["Event"]))}</span>'
        f'<strong>{escape(str(row.get("Symbol") or "â€”"))}</strong>'
        f'<span>{escape(str(row.get("Contract") or "â€”"))}</span>'
        f'<span class="ob-activity-result">{escape(str(row.get("Price / Result") or "â€”"))}</span></div>'
        for row in rows
    )
    return panel_markup(title, items)


def panel_markup(title, body):
    heading = f'<h3>{escape(title)}</h3>' if title else ""
    return f'<section class="ob-desk-panel">{heading}{body}</section>'


def _percent_or_dash(value, *, signed=False):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "â€”"
    return f'{value:+.2f}%' if signed else f'{value:.1f}%'


def _number_or_dash(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "â€”"
    return "âˆž" if math.isinf(value) else f'{value:.2f}'


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
