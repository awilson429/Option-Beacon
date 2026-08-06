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
    reliability_state, *, market_open, paper_active,
    paper_profile=None, now=None,
):
    state = reliability_state or {}
    scanner = str(state.get("scanner_state") or "UNKNOWN").upper()
    market_data = str(state.get("market_data_state") or "UNKNOWN").upper()
    severity = "healthy"
    if scanner in {"ERROR", "FAILED", "UNAVAILABLE"} or market_data == "UNAVAILABLE":
        severity = "error"
    elif scanner in {"STALE", "WAITING", "NEVER RUN"} or market_data in {"PARTIAL", "UNKNOWN"}:
        severity = "warning"
    scanning = scanner == "SCANNING"
    processed = int(
        (state.get("current_symbols_attempted") if scanning else None)
        or (0 if scanning else state.get("last_symbols_processed") or 0)
    )
    total = state.get("current_symbol_count")
    progress = f"{processed}/{int(total)}" if total is not None else str(processed)
    scan_time = state.get("last_completed_at") or state.get("last_success_at")
    scanner_label = (
        f"SCANNING · {progress}" if scanning else
        f"SCANNER CURRENT · {progress}" if scanner == "CURRENT" else
        f"SCANNER STALE · {progress}" if scanner == "STALE" else
        "SCANNER WAITING" if scanner in {"WAITING", "NEVER RUN", "UNKNOWN"} else
        f"SCANNER {scanner}"
    )
    profile = str(paper_profile or "").upper()
    return {
        "severity": severity,
        "market": "MARKET OPEN" if market_open else "MARKET CLOSED",
        "scanner": scanner_label,
        "paper": f"PAPER {profile} ACTIVE" if paper_active and profile else "PAPER ACTIVE" if paper_active else "PAPER DISABLED",
        "last_scan": f"LAST COMPLETE {relative_age(scan_time, now).upper()}" if scan_time else "LAST COMPLETE —",
    }


def status_strip_markup(model):
    pills = "".join(
        f'<span class="ob-desk-status-pill">{escape(str(model[key]))}</span>'
        for key in ("market", "scanner", "paper", "last_scan")
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
        f'<strong>{item["percent"]:.0f}%</strong></div>'
        f'<div class="ob-risk-track"><span class="ob-risk-fill ob-risk-{item["treatment"]}" '
        f'style="width:{item["percent"]:.1f}%"></span></div></div>'
        for item in model["items"]
    )
    return panel_markup("Risk Status", rows)


def performance_panel_markup(summary, paper_summary, *, paper_available):
    if paper_available:
        factor = paper_summary["profit_factor"]
        total = paper_summary["today_pnl"]
        values = (
            ("Realized P&L", f'${paper_summary["realized_pnl"]:+,.2f}'),
            ("Unrealized P&L", f'${paper_summary["open_pnl"]:+,.2f}'),
            ("Win Rate", f'{paper_summary["win_rate"]:.1f}%'),
            ("Trades Closed", str(paper_summary["trades_closed_today"])),
            ("Profit Factor", "âˆž" if math.isinf(factor) else f'{factor:.2f}'),
        )
    else:
        score = summary or {}
        total = None
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
    total_value = f'${total:+,.2f}' if total is not None else "—"
    treatment = "positive" if (total or 0) > 0 else "negative" if (total or 0) < 0 else "neutral"
    anchor = (
        '<div class="ob-performance-anchor"><span>TOTAL P&amp;L</span>'
        f'<strong class="ob-value-{treatment}">{escape(total_value)}</strong>'
        '<div class="ob-performance-rule"></div></div>'
    )
    return panel_markup(
        "Today Performance",
        f'{anchor}<div class="ob-performance-grid">{stats}</div>',
        extra_class="ob-performance-panel",
    )


def more_stats_markup(scorecard, paper_summary, *, paper_available):
    score = scorecard or {}
    values = (
        ("Best Trade", _percent_or_dash(score.get("best_trade"), signed=True)),
        ("Worst Trade", _percent_or_dash(score.get("worst_trade"), signed=True)),
        ("Average Win", f'${paper_summary["average_winner"]:+,.2f}' if paper_available else "—"),
        ("Average Loss", f'${paper_summary["average_loser"]:+,.2f}' if paper_available else "—"),
        ("Average Hold", f'{score["average_hold_minutes"]:.0f}m' if score.get("average_hold_minutes") is not None else "—"),
    )
    rows = "".join(
        f'<div class="ob-stat-row"><span>{escape(label)}</span><strong>{escape(value)}</strong></div>'
        for label, value in values
    )
    return (
        '<details class="ob-more-stats"><summary>More Stats</summary>'
        f'<div class="ob-more-stats-grid">{rows}</div></details>'
    )


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
        return compact_empty_markup("Open Positions", "0")
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


def activity_rows_markup(rows):
    """Rows-only markup for controls contained by the keyed activity panel."""
    if not rows:
        return '<div class="ob-desk-empty">No meaningful activity recorded.</div>'
    items = []
    for row in rows:
        if row.get("Lifecycle Detail"):
            items.append(
                f'<div class="ob-activity-row ob-activity-lifecycle"><span class="ob-activity-time">{escape(str(row["Time"]))}</span>'
                f'<span class="ob-activity-tag ob-activity-{escape(str(row["Event"]).lower().replace(" ", "-"))}">{escape(str(row["Event"]))}</span>'
                f'<strong>{escape(str(row.get("Symbol") or "—"))}</strong>'
                f'<b>{escape(str(row.get("Direction") or "—"))}</b>'
                f'<span class="ob-activity-state">{escape(str(row.get("Lifecycle State") or "—"))}</span>'
                f'<div class="ob-activity-market">{escape(str(row["Lifecycle Detail"]))}</div>'
                f'<div class="ob-activity-meta">{escape(str(row.get("Lifecycle Meta") or "—"))}</div>'
                f'{_activity_details_markup(row)}</div>'
            )
        else:
            items.append(
                f'<div class="ob-activity-row"><span class="ob-activity-time">{escape(str(row["Time"]))}</span>'
                f'<span class="ob-activity-tag ob-activity-{escape(str(row["Event"]).lower().replace(" ", "-"))}">{escape(str(row["Event"]))}</span>'
                f'<strong>{escape(str(row.get("Symbol") or "—"))}</strong>'
                f'<span>{escape(str(row.get("Display Detail") or "—"))}</span>'
                f'<span class="ob-activity-result">{escape(str(row.get("Display Result") or "—"))}</span></div>'
            )
    return "".join(items)


def _activity_details_markup(row):
    detail = row.get("Lifecycle Diagnostics")
    if not detail:
        return ""
    return (
        '<details class="ob-activity-details"><summary>Details</summary>'
        f'<div>{escape(str(detail))}</div></details>'
    )


def dashboard_shell_markup(
    *, status, kpis, risk, best_trade, positions, comparison,
    authoritative_trades, activity_rows, activity_filter, view_all, more_stats,
):
    """Compose the complete deterministic Trade Desk CSS-grid body."""
    filters = "".join(
        f'<a class="ob-activity-filter {"is-active" if value == activity_filter else ""}" '
        f'href="?page=trade-desk&amp;desk_activity={value}&amp;desk_all={1 if view_all else 0}">{value}</a>'
        for value in ACTIVITY_FILTERS
    )
    view_href = (
        f'?page=trade-desk&amp;desk_activity={activity_filter}&amp;desk_all={0 if view_all else 1}'
    )
    activity = (
        '<section class="ob-desk-panel ob-grid-activity">'
        '<div class="ob-activity-header"><h3>Recent Activity</h3>'
        f'<nav class="ob-activity-filters" aria-label="Activity filter">{filters}</nav>'
        f'<a class="ob-activity-view" href="{view_href}">{"Latest" if view_all else "View all"}</a>'
        f'</div>{activity_rows}</section>'
    )
    return (
        '<div class="ob-trade-dashboard">'
        '<header class="ob-grid-header"><div><h2>Trade Desk</h2>'
        '<p>Monitor positions, manage risk, and track performance in real time.</p>'
        f'</div>{status}</header>'
        f'<div class="ob-grid-kpis">{kpis}</div>'
        f'<aside class="ob-grid-risk"><div class="ob-risk-stack">{risk}{best_trade}'
        '</div></aside>'
        f'<div class="ob-grid-positions">{positions}</div>'
        f'<div class="ob-grid-comparison">{comparison}</div>'
        f'<div class="ob-grid-authoritative">{authoritative_trades}</div>'
        f'{activity}'
        f'<div class="ob-grid-more">{more_stats}</div>'
        '</div>'
    )


def authoritative_positions_markup(rows):
    if not rows:
        return compact_empty_markup("Open Positions", "0")
    headers = ("SYMBOL", "TYPE", "ENTRY", "CURRENT", "P&L %", "STATUS")
    head = "".join(f'<th>{value}</th>' for value in headers)
    body = "".join(
        '<tr>'
        f'<td><strong>{escape(str(row.get("Symbol") or "—"))}</strong></td>'
        f'<td>{escape(str(row.get("Direction") or "—"))}</td>'
        f'<td>{escape(str(row.get("Entry") or "—"))}</td>'
        f'<td>{escape(str(row.get("Current Price") or "—"))}</td>'
        f'<td>{escape(str(row.get("Open Return") or "—"))}</td>'
        f'<td><span class="ob-position-state">{escape(str(row.get("Status") or "OPEN"))}</span></td>'
        '</tr>'
        for row in rows
    )
    return panel_markup(
        "Open Positions",
        f'<div class="ob-position-scroll"><table class="ob-position-table">'
        f'<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>',
    )


def panel_markup(title, body, *, extra_class=""):
    heading = f'<h3>{escape(title)}</h3>' if title else ""
    classes = f'ob-desk-panel {extra_class}'.strip()
    return f'<section class="{classes}">{heading}{body}</section>'


def compact_empty_markup(label, value):
    return (
        '<section class="ob-compact-empty">'
        f'<span>{escape(str(label))}</span><strong>{escape(str(value))}</strong>'
        '</section>'
    )


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
    if selected == "ALL":
        ordered = [
            event for event in ordered
            if event.get("event_type") != "INVALIDATED"
        ]
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
        contract = event.get("option_symbol") or "—"
        row["Contract"] = contract
        row["Display Detail"] = (
            contract if contract != "—" else row.get("Detail") or "—"
        )
        value = str(row.get("Price / Result") or "—")
        if value != "—" and event.get("event_type") == "TRADE_ENTERED":
            value = f"{value} entry"
        elif value != "—" and event.get("event_type") != "TRADE_CLOSED":
            value = f"{value} underlying"
        row["Display Result"] = value
        presentation = event.get("_authoritative_activity") or {}
        if presentation:
            row.update(presentation)
    return rows


def enrich_authoritative_activity_events(events, opportunities, funnel_rows, *, now=None):
    """Join read-only lifecycle context strictly by immutable opportunity ID."""
    checked_at = _datetime(now) or datetime.now(timezone.utc)
    opportunity_by_id = {
        str(row.get("id")): row for row in opportunities or [] if row.get("id")
    }
    funnel_by_id = {
        str(row.get("opportunity_id")): row
        for row in funnel_rows or [] if row.get("opportunity_id")
    }
    enriched = []
    for source in events:
        event = dict(source)
        identity = str(event.get("opportunity_id") or "")
        opportunity = opportunity_by_id.get(identity)
        if not opportunity:
            enriched.append(event)
            continue
        funnel = funnel_by_id.get(identity)
        event["_authoritative_activity"] = _authoritative_activity_presentation(
            event, opportunity, funnel, checked_at
        )
        enriched.append(event)
    return enriched


def _authoritative_activity_presentation(event, opportunity, funnel, now):
    event_type = str(event.get("event_type") or "")
    direction = "CALL" if opportunity.get("direction") == "Bullish" else "PUT" if opportunity.get("direction") == "Bearish" else "—"
    trigger = _activity_number(opportunity.get("entry_reference"))
    confidence = _activity_number(opportunity.get("confidence"))
    current = (
        _activity_number(event.get("underlying_price"))
        if event_type == "TRADE_ENTERED"
        else _activity_number((funnel or {}).get("current_price"))
    )
    current_label = "Entry" if event_type == "TRADE_ENTERED" else "Current"
    if current is None:
        current = _activity_number(event.get("underlying_price"))
        current_label = "Reference"
    state = _activity_lifecycle_state(event_type, opportunity, funnel)
    distance = _activity_trigger_distance(direction, current, trigger)
    market = []
    if current is not None:
        market.append(f"{current_label} ${current:.2f}")
    if trigger is not None:
        market.append(f"Trigger ${trigger:.2f}")
    if distance:
        market.append(distance)
    if event_type == "TRADE_CLOSED":
        market = _exit_market_detail(event)
    meta = []
    if confidence is not None:
        meta.append(f"Confidence {confidence:g}")
    age = _activity_candidate_age(opportunity, event, state, now)
    if age is not None:
        meta.append(f"Age {age}")
    reason = _activity_reason(event, opportunity, funnel, distance)
    if reason:
        meta.append(reason)
    details = [
        f"Opportunity ID {identity}" for identity in [event.get("opportunity_id")] if identity
    ]
    details.extend([
        f"Created {opportunity.get('signal_timestamp') or '—'}",
        f"Persisted trigger {_activity_price(trigger)}",
        f"{current_label} price {_activity_price(current)}",
        f"Confidence {confidence:g}" if confidence is not None else "Confidence —",
        f"Lifecycle state {state}",
        f"Disposition {str((funnel or {}).get('authoritative_disposition') or reason or 'Awaiting lifecycle evaluation').replace('_', ' ')}",
        f"Authoritative confidence qualified {'YES' if confidence is not None and confidence >= 65 else 'NO' if confidence is not None else '—'}",
        f"Visible setup qualified {'YES' if (funnel or {}).get('visible_setup_qualified') else 'NO' if funnel else '—'}",
    ])
    return {
        "Direction": direction,
        "Lifecycle State": state,
        "Lifecycle Detail": " · ".join(market) if market else "—",
        "Lifecycle Meta": " · ".join(meta) if meta else "—",
        "Lifecycle Diagnostics": " · ".join(details),
    }


def _activity_trigger_distance(direction, current, trigger):
    if current is None or trigger in (None, 0) or direction not in {"CALL", "PUT"}:
        return None
    crossed = current >= trigger if direction == "CALL" else current <= trigger
    absolute = abs(current - trigger)
    percent = absolute / abs(trigger) * 100
    if absolute < 1e-9:
        return "TRIGGER REACHED"
    return (
        f"TRIGGER REACHED · ${absolute:.2f} beyond trigger ({percent:.2f}%)"
        if crossed else f"${absolute:.2f} away ({percent:.2f}%)"
    )


def _activity_lifecycle_state(event_type, opportunity, funnel):
    if event_type == "TRADE_ENTERED":
        return "ENTERED"
    if event_type in EXIT_EVENTS:
        return "CLOSED" if event_type == "TRADE_CLOSED" else event_type.replace("_", " ")
    funnel_state = str((funnel or {}).get("state") or "").upper()
    if funnel_state and funnel_state != "UNAVAILABLE":
        return funnel_state
    if event_type == "ENTRY_READY":
        return "READY"
    if event_type == "WATCH_CREATED":
        return "WATCHING"
    return str(opportunity.get("state") or "—").replace("_", " ").upper()


def _activity_reason(event, opportunity, funnel, distance):
    event_type = str(event.get("event_type") or "")
    if event_type == "TRADE_ENTERED":
        return "Entered"
    if event_type == "TRADE_CLOSED":
        return str(event.get("exit_reason") or "Closed").replace("_", " ")
    blocker = str((funnel or {}).get("primary_blocker") or "")
    reasons = {
        "TRIGGER_NOT_REACHED": "Waiting for trigger",
        "ENTRY_CONFIDENCE_BELOW_MINIMUM": "Confidence below 65",
        "ENTRY_WINDOW": "Entry window closed",
        "SETUP_INVALIDATED": "Invalidated",
        "DO_NOT_CHASE": "Extended / do not chase",
        "AWAITING_AUTHORITATIVE_LIFECYCLE": "Awaiting lifecycle evaluation",
    }
    if blocker:
        return reasons.get(blocker, blocker.replace("_", " ").title())
    if str(opportunity.get("state") or "").upper() == "NEVER_TRIGGERED":
        return "Candidate expired"
    if distance and "away" in distance:
        return "Waiting for trigger"
    return "Awaiting lifecycle evaluation"


def _activity_candidate_age(opportunity, event, state, now):
    created = _datetime(opportunity.get("signal_timestamp"))
    if created is None:
        return None
    endpoint = now if state in {"READY", "WATCHING", "ARMED", "DEVELOPING", "CANDIDATE"} else _datetime(event.get("event_timestamp")) or now
    minutes = max(0, int((endpoint - created).total_seconds() // 60))
    return f"{minutes}m" if minutes < 60 else f"{minutes // 60}h {minutes % 60}m"


def _exit_market_detail(event):
    values = []
    if event.get("entry_price") is not None:
        values.append(f'Entry {_activity_price(event.get("entry_price"))}')
    if event.get("exit_price") is not None:
        values.append(f'Exit {_activity_price(event.get("exit_price"))}')
    if event.get("realized_return") is not None:
        values.append(f'Return {float(event["realized_return"]):+.2f}%')
    metadata = event.get("metadata") or {}
    if metadata.get("hold_minutes") is not None:
        values.append(f'Hold {int(float(metadata["hold_minutes"]))}m')
    return values


def _activity_number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _activity_price(value):
    number = _activity_number(value)
    return f"${number:.2f}" if number is not None else "—"


def _datetime(value):
    if value is None:
        return None
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _timestamp(value):
    if not value:
        return float("-inf")
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(
        str(value).replace("Z", "+00:00")
    )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()
