"""Read-only authoritative-versus-PAPER Trade Desk comparison models."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from html import escape
from zoneinfo import ZoneInfo


EASTERN = ZoneInfo("America/New_York")


def available_session_dates(authoritative_events, now):
    today = _aware(now).astimezone(EASTERN).date()
    dates = sorted({
        _aware(event.get("event_timestamp")).astimezone(EASTERN).date()
        for event in authoritative_events
        if event.get("event_type") == "TRADE_ENTERED"
        and event.get("event_timestamp")
    }, reverse=True)
    previous = next((value for value in dates if value < today), None)
    return {"today": today, "previous": previous}


def trade_comparison_model(
    authoritative_events, journal_rows, captures, paper_positions, *, session_date
):
    """Join a session's authoritative entries to PAPER decisions by durable IDs."""
    events = [
        event for event in authoritative_events
        if event.get("event_timestamp")
        and _aware(event["event_timestamp"]).astimezone(EASTERN).date() == session_date
    ]
    entries = {}
    closes = {}
    latest = {}
    for event in sorted(events, key=lambda row: _aware(row["event_timestamp"])):
        identity = event.get("opportunity_id") or event.get("trade_id")
        if not identity:
            continue
        latest[identity] = event
        if event.get("event_type") == "TRADE_ENTERED":
            entries.setdefault(identity, event)
        elif event.get("event_type") == "TRADE_CLOSED":
            closes[identity] = event

    source_by_paper_trade = {
        str(capture.trade_id): str(capture.source_signal_id)
        for capture in captures
        if getattr(capture, "trade_id", None) and getattr(capture, "source_signal_id", None)
    }
    decisions = {}
    for journal in sorted(
        journal_rows, key=lambda row: _aware(row.get("created_at")), reverse=True
    ):
        metadata = _json(journal.get("metadata_json"))
        if metadata.get("journal_type") not in (None, "ENTRY_DECISION"):
            continue
        source_id = source_by_paper_trade.get(str(journal.get("trade_id")))
        if source_id in entries:
            decisions.setdefault(source_id, journal)

    positions_by_trade = {
        str(position.trade_id): position
        for position in paper_positions
        if getattr(position, "trade_id", None)
    }
    paper_trade_by_source = {
        source: trade_id for trade_id, source in source_by_paper_trade.items()
    }
    rows = []
    for identity, entry in sorted(
        entries.items(), key=lambda item: _aware(item[1]["event_timestamp"]), reverse=True
    ):
        close = closes.get(identity)
        current = close or latest.get(identity) or entry
        auth_return = (
            close.get("realized_return") if close
            else current.get("current_return")
        )
        auth_result = (
            "WIN" if close and _number(auth_return) > 0
            else "LOSS" if close and _number(auth_return) < 0
            else "FLAT" if close and auth_return is not None
            else "OPEN"
        )
        decision = decisions.get(identity)
        disposition = (
            "OPENED" if decision and bool(decision.get("accepted"))
            else "REJECTED" if decision
            else "PENDING"
        )
        paper_trade_id = paper_trade_by_source.get(identity)
        position = positions_by_trade.get(paper_trade_id)
        paper_pnl = _paper_pnl(position)
        metadata = _json((decision or {}).get("metadata_json"))
        risk_state = _json((decision or {}).get("risk_state_json"))
        rows.append({
            "authoritative_id": identity,
            "time": _aware(entry["event_timestamp"]).astimezone(EASTERN).strftime("%I:%M:%S %p"),
            "symbol": str(entry.get("symbol") or "—"),
            "direction": _direction(entry.get("direction")),
            "entry": entry.get("entry_price") if entry.get("entry_price") is not None else entry.get("underlying_price"),
            "exit_current": close.get("exit_price") if close else current.get("underlying_price"),
            "status": "CLOSED" if close else "OPEN",
            "auth_result": auth_result,
            "auth_return": auth_return,
            "paper_disposition": disposition,
            "paper_reason": (
                str(decision.get("reason_code") or "UNKNOWN")
                if disposition == "REJECTED" else "—"
            ),
            "paper_pnl": paper_pnl,
            "authoritative_score": entry.get("rule_score"),
            "simulation_profile": metadata.get("simulation_profile") or ("LEGACY_UNLABELED" if decision else "—"),
            "effective_min_score": metadata.get("effective_min_score"),
            "risk_state": risk_state,
        })

    closed = [row for row in rows if row["status"] == "CLOSED"]
    wins = [row for row in closed if row["auth_result"] == "WIN"]
    losses = [row for row in closed if row["auth_result"] == "LOSS"]
    opened = [row for row in rows if row["paper_disposition"] == "OPENED"]
    rejected = [row for row in rows if row["paper_disposition"] == "REJECTED"]
    evaluated = opened + rejected
    missed = [row for row in wins if row["paper_disposition"] != "OPENED"]
    paper_closed = [
        positions_by_trade.get(paper_trade_by_source.get(row["authoritative_id"]))
        for row in opened
    ]
    paper_closed = [item for item in paper_closed if item and item.status != "OPEN"]
    paper_matched = [
        positions_by_trade.get(paper_trade_by_source.get(row["authoritative_id"]))
        for row in opened
    ]
    paper_matched = [item for item in paper_matched if item]
    paper_wins = sum(_paper_pnl(item) > 0 for item in paper_closed)
    paper_losses = sum(_paper_pnl(item) < 0 for item in paper_closed)
    reasons = Counter(row["paper_reason"] for row in missed if row["paper_reason"] != "—")
    return {
        "session_date": session_date,
        "rows": rows,
        "authoritative": {
            "trades": len(rows), "closed": len(closed), "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / len(closed) * 100 if closed else 0.0,
            "average_return": _average([row["auth_return"] for row in closed]),
        },
        "paper": {
            "evaluated": len(evaluated), "opened": len(opened),
            "rejected": len(rejected), "pending": len(rows) - len(evaluated),
            "participation_rate": len(opened) / len(rows) * 100 if rows else 0.0,
            "closed": len(paper_closed), "wins": paper_wins, "losses": paper_losses,
            "pnl": sum(_paper_pnl(item) for item in paper_matched),
        },
        "missed_winners": {
            "count": len(missed),
            "average_return": _average([row["auth_return"] for row in missed]),
            "rejection_counts": dict(sorted(reasons.items(), key=lambda item: (-item[1], item[0]))),
            "rows": missed,
        },
    }


def comparison_markup(model, *, has_previous=False, selected="TODAY"):
    auth, paper = model["authoritative"], model["paper"]
    selected = selected if selected in {"TODAY", "PREVIOUS"} else "TODAY"
    tabs = (
        f'<a class="ob-session-tab {"is-active" if selected == "TODAY" else ""}" href="?page=trade-desk&amp;desk_session=TODAY">Today</a>'
        + (f'<a class="ob-session-tab {"is-active" if selected == "PREVIOUS" else ""}" href="?page=trade-desk&amp;desk_session=PREVIOUS">Previous Session</a>' if has_previous else "")
    )
    metrics = (
        ("OPTIONBEACON", "Trades", auth["trades"], "Wins", auth["wins"], "Losses", auth["losses"], "Win Rate", f'{auth["win_rate"]:.1f}%', "Avg Auth Return", _percent(auth["average_return"])),
        ("PAPER", "Opened", paper["opened"], "Closed", paper["closed"], "Wins / Losses", f'{paper["wins"]} / {paper["losses"]}', "Participation", f'{paper["participation_rate"]:.1f}%', "Option P&L", _money(paper["pnl"])),
    )
    columns = "".join(
        '<div class="ob-compare-column"><h4>' + escape(str(values[0])) + '</h4>'
        + "".join(f'<div><span>{escape(str(values[index]))}</span><strong>{escape(str(values[index + 1]))}</strong></div>' for index in range(1, len(values), 2))
        + '</div>' for values in metrics
    )
    participation = (
        f'<div class="ob-participation"><span>Authoritative Entries <strong>{auth["trades"]}</strong></span>'
        f'<span>PAPER Evaluated <strong>{paper["evaluated"]}</strong></span>'
        f'<span>PAPER Opened <strong>{paper["opened"]}</strong></span>'
        f'<span>PAPER Rejected <strong>{paper["rejected"]}</strong></span>'
        f'<span>Participation <strong>{paper["participation_rate"]:.1f}%</strong></span></div>'
    )
    missed = model["missed_winners"]
    reasons = ", ".join(f'{key}: {value}' for key, value in missed["rejection_counts"].items()) or "None recorded"
    missed_block = (
        '<div class="ob-missed-summary"><span>MISSED AUTHORITATIVE WINNERS</span>'
        f'<strong>{missed["count"]}</strong><small>Avg auth underlying return {_percent(missed["average_return"])} · {escape(reasons)}</small></div>'
    )
    return (
        '<section class="ob-desk-panel"><div class="ob-compare-header"><h3>OptionBeacon vs PAPER</h3>'
        f'<nav class="ob-session-tabs">{tabs}</nav></div><div class="ob-compare-grid">{columns}</div>'
        f'{participation}{missed_block}</section>'
    )


def authoritative_trades_markup(model, *, selected="TODAY"):
    auth = model["authoritative"]
    summary = (
        '<div class="ob-auth-summary">'
        f'<span>OptionBeacon Trades <strong>{auth["trades"]}</strong></span>'
        f'<span>Closed <strong>{auth["closed"]}</strong></span>'
        f'<span>Wins <strong>{auth["wins"]}</strong></span>'
        f'<span>Losses <strong>{auth["losses"]}</strong></span>'
        f'<span>Win Rate <strong>{auth["win_rate"]:.1f}%</strong></span>'
        f'<span>Avg Auth Return <strong>{_percent(auth["average_return"])}</strong></span></div>'
    )
    if not model["rows"]:
        body = '<div class="ob-desk-empty">No authoritative entries persisted for this session.</div>'
    else:
        rows = []
        missed_ids = {row["authoritative_id"] for row in model["missed_winners"]["rows"]}
        for row in model["rows"]:
            treatment = "positive" if row["auth_result"] == "WIN" else "negative" if row["auth_result"] == "LOSS" else "neutral"
            diagnostics = ""
            if row["authoritative_id"] in missed_ids:
                risk = row["risk_state"]
                details = (
                    f'Authoritative ID {row["authoritative_id"]} · Score {_value(row["authoritative_score"])} · '
                    f'Profile {row["simulation_profile"]} · Effective min score {_value(row["effective_min_score"])} · '
                    f'Max positions state {_risk_value(risk, "open_positions", "max_open_positions")} · '
                    f'Buying power {_risk_value(risk, "available_buying_power", "buying_power")} · '
                    f'Rejection {row["paper_reason"]}'
                )
                diagnostics = f'<details><summary>Why missed?</summary><div>{escape(details)}</div></details>'
            rows.append(
                '<tr>'
                f'<td>{escape(row["time"])}</td><td><strong>{escape(row["symbol"])}</strong></td>'
                f'<td>{escape(row["direction"])}</td><td>{_price(row["entry"])}</td><td>{_price(row["exit_current"])}</td>'
                f'<td class="ob-value-{treatment}">{escape(row["auth_result"])}</td>'
                f'<td class="ob-value-{treatment}">{_percent(row["auth_return"])}</td><td>{escape(row["status"])}</td>'
                f'<td>{escape(row["paper_disposition"])}</td><td>{escape(row["paper_reason"])}</td>'
                f'<td>{_money(row["paper_pnl"]) if row["paper_pnl"] is not None else "—"}{diagnostics}</td></tr>'
            )
        headers = ("TIME", "SYMBOL", "DIRECTION", "ENTRY", "EXIT / CURRENT", "RESULT", "AUTH RETURN", "STATUS", "PAPER", "PAPER REASON", "PAPER OPTION P&L")
        body = '<div class="ob-position-scroll"><table class="ob-position-table ob-auth-table"><thead><tr>' + "".join(f'<th>{value}</th>' for value in headers) + '</tr></thead><tbody>' + "".join(rows) + '</tbody></table></div>'
    title = "Today's OptionBeacon Trades" if selected == "TODAY" else "Previous Session OptionBeacon Trades"
    return f'<section class="ob-desk-panel"><h3>{title}</h3>{summary}{body}</section>'


def _paper_pnl(position):
    if position is None:
        return None
    quantity = int(position.quantity or 1)
    current = position.exit_mid if position.status != "OPEN" else position.current_mid
    return round((current - position.entry_mid) * 100 * quantity, 2)


def _aware(value):
    if isinstance(value, datetime):
        parsed = value
    elif value:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    else:
        return datetime.min.replace(tzinfo=timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _json(value):
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _average(values):
    numeric = [float(value) for value in values if value is not None]
    return sum(numeric) / len(numeric) if numeric else None


def _direction(value):
    value = str(value or "").upper()
    return "CALL" if value in {"BULLISH", "CALL"} else "PUT" if value in {"BEARISH", "PUT"} else "—"


def _percent(value):
    return f'{float(value):+.2f}%' if value is not None else "—"


def _money(value):
    return f'${float(value):+,.2f}' if value is not None else "—"


def _price(value):
    return f'${float(value):,.2f}' if value is not None else "—"


def _value(value):
    return str(value) if value is not None else "not recorded"


def _risk_value(risk, *keys):
    for key in keys:
        if risk.get(key) is not None:
            return str(risk[key])
    return "not recorded"
