"""Authoritative trade-event generation and compact Trade Desk view models."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from html import escape
from zoneinfo import ZoneInfo


EASTERN = ZoneInfo("America/New_York")
NOTIFICATION_SECONDS = 300
MEANINGFUL_EVENT_TYPES = {
    "WATCH_CREATED", "ENTRY_READY", "TRADE_ENTERED", "TARGET_REACHED",
    "STOP_REACHED", "EXIT_SIGNAL", "TRADE_CLOSED", "END_OF_DAY_EXIT",
    "MAX_HOLD_EXIT", "INVALIDATED",
}


def _aware(value):
    if value is None:
        return None
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(
        str(value).replace("Z", "+00:00")
    )
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def format_eastern_seconds(value) -> str:
    parsed = _aware(value)
    return parsed.astimezone(EASTERN).strftime("%I:%M:%S %p ET").lstrip("0") if parsed else "—"


def relative_age(value, now=None) -> str:
    parsed = _aware(value)
    checked = _aware(now) or datetime.now(timezone.utc)
    if parsed is None:
        return ""
    seconds = max(0, int((checked - parsed).total_seconds()))
    if seconds < 60:
        return f"{seconds} sec ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    return f"{seconds // 3600}h ago"


def format_hold_duration(opened_at, closed_at) -> str:
    opened, closed = _aware(opened_at), _aware(closed_at)
    if not opened or not closed:
        return "—"
    seconds = max(0, int((closed - opened).total_seconds()))
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes}m {seconds:02d}s"


def directional_return(direction, entry, current):
    try:
        result = (float(current) - float(entry)) / float(entry) * 100
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return result if str(direction) == "Bullish" else -result


def event_dedup_key(record, event_type, event_timestamp, marker=""):
    payload = [record.trade_id, event_type, _aware(event_timestamp).isoformat(), marker]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


def persist_outcome_transition(
    repository, before, record, *, underlying_price=None, rule_score=None
):
    """Append events for one already-authoritative lifecycle transition."""
    events = []
    is_new = before is None
    entered = record.entry_time is not None and (before is None or before.entry_time is None)
    closed = record.exit_time is not None and (before is None or before.exit_time is None)
    updated = before is not None and not entered and not closed

    def add(event_type, timestamp, description, *, marker=""):
        if timestamp is None:
            return
        exit_price = None
        if record.exit_reason == "STOP":
            exit_price = record.stop
        elif str(record.exit_reason or "").startswith("TARGET_"):
            exit_price = getattr(record, str(record.exit_reason).lower(), None)
        elif record.exit_time is not None:
            exit_price = underlying_price
        event = repository.record_trade_event(
            dedup_key=event_dedup_key(record, event_type, timestamp, marker),
            trade_id=record.trade_id if record.entry_time else None,
            opportunity_id=record.trade_id,
            symbol=record.symbol,
            direction=record.direction,
            setup=record.setup,
            event_type=event_type,
            event_timestamp=timestamp,
            underlying_price=underlying_price,
            entry_price=record.entry,
            exit_price=exit_price,
            current_return=directional_return(record.direction, record.entry, underlying_price),
            realized_return=record.realized_return,
            exit_reason=record.exit_reason,
            rule_score=rule_score if rule_score is not None else record.confidence,
            description=description,
            metadata={
                "hold_minutes": record.hold_minutes,
                "stop": record.stop,
                "target_1": record.target_1,
                "target_2": record.target_2,
                "target_3": record.target_3,
            },
        )
        events.append(event)

    if is_new:
        add("WATCH_CREATED", record.timestamp, f"{record.symbol} watch created")
        add("ENTRY_READY", record.timestamp, f"{record.symbol} entry level is ready", marker="ready")
    if entered:
        add("TRADE_ENTERED", record.entry_time, f"Entered {record.symbol} at ${record.entry:.2f}")
    elif updated and record.entry_time is None and record.exit_time is None:
        add("WATCH_UPDATED", record.timestamp, f"{record.symbol} watch updated", marker=str(underlying_price))
    elif updated and record.entry_time is not None and record.exit_time is None:
        add("POSITION_UPDATED", datetime.now(timezone.utc), f"{record.symbol} active position updated", marker=str(underlying_price))
    if closed:
        reason = str(record.exit_reason or "CLOSED")
        if reason.startswith("TARGET_"):
            add("TARGET_REACHED", record.exit_time, f"{record.symbol} reached {reason.replace('_', ' ').title()}")
        elif reason == "STOP":
            add("STOP_REACHED", record.exit_time, f"{record.symbol} stop reached")
        elif reason == "END_OF_DAY":
            add("END_OF_DAY_EXIT", record.exit_time, f"{record.symbol} exited at end of day")
        elif reason == "TIME_EXIT":
            add("MAX_HOLD_EXIT", record.exit_time, f"{record.symbol} maximum hold exit")
        elif reason == "NEVER_TRIGGERED":
            add("INVALIDATED", record.exit_time, f"{record.symbol} watch invalidated")
        if record.entry_time is not None:
            add("EXIT_SIGNAL", record.exit_time, f"Exit {record.symbol}: {reason}", marker="signal")
            add("TRADE_CLOSED", record.exit_time, f"{record.symbol} trade closed: {reason}", marker="closed")
    return events


def meaningful_events(events, limit=20):
    selected, previous = [], None
    for event in events:
        if event.get("event_type") not in MEANINGFUL_EVENT_TYPES:
            continue
        material = (
            event.get("opportunity_id") or event.get("trade_id"),
            event.get("event_type"), event.get("underlying_price"),
            event.get("exit_reason"),
        )
        if material == previous:
            continue
        selected.append(event)
        previous = material
        if len(selected) >= limit:
            break
    return selected


def priority_notification(events, now=None):
    checked = _aware(now) or datetime.now(timezone.utc)
    for event in events:
        if event.get("event_type") not in {"TRADE_ENTERED", "TRADE_CLOSED"}:
            continue
        age = (checked - _aware(event.get("event_timestamp"))).total_seconds()
        if 0 <= age <= NOTIFICATION_SECONDS:
            return event
    return None


def recently_closed_rows(trades, now=None, limit=10):
    checked = (_aware(now) or datetime.now(timezone.utc)).astimezone(EASTERN)
    closed = [trade for trade in trades if trade.get("closed_at") and _aware(trade["closed_at"]).astimezone(EASTERN).date() == checked.date()]
    closed.sort(key=lambda trade: _aware(trade["closed_at"]), reverse=True)
    return [{
        "Symbol": _trade_outcome_payload(trade).get("symbol") or "—",
        "Direction": "CALL" if _trade_direction(trade) == "Bullish" else "PUT" if _trade_direction(trade) == "Bearish" else "—",
        "Result": _signed_percent(trade.get("realized_result")),
        "Exit Reason": str(trade.get("exit_reason") or "—").replace("_", " "),
        "Hold Time": format_hold_duration(trade.get("opened_at"), trade.get("closed_at")),
        "Closed Time": format_eastern_seconds(trade.get("closed_at")),
    } for trade in closed[:limit]]


def _trade_direction(trade):
    return _trade_outcome_payload(trade).get("direction")


def _trade_outcome_payload(trade):
    payload = (trade.get("metadata") or {}).get("trade_outcome")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            payload = {}
    return payload or {}


def _signed_percent(value):
    try:
        return f"{float(value):+.2f}%"
    except (TypeError, ValueError):
        return "—"


def activity_rows(events, now=None, limit=20):
    labels = {
        "WATCH_CREATED": "WATCH", "ENTRY_READY": "READY",
        "TRADE_ENTERED": "ENTER", "TARGET_REACHED": "TARGET",
        "STOP_REACHED": "STOP", "TRADE_CLOSED": "EXIT",
        "END_OF_DAY_EXIT": "EOD EXIT", "MAX_HOLD_EXIT": "TIME EXIT",
        "INVALIDATED": "INVALID",
    }
    rows = []
    for event in meaningful_events(events, limit=limit):
        direction = "CALL" if event.get("direction") == "Bullish" else "PUT" if event.get("direction") == "Bearish" else ""
        rows.append({
            "Time": format_eastern_seconds(event.get("event_timestamp")),
            "Age": relative_age(event.get("event_timestamp"), now),
            "Event": labels.get(event.get("event_type"), event.get("event_type", "").replace("_", " ")),
            "Symbol": event.get("symbol"),
            "Direction": direction,
            "Price / Result": _signed_percent(event.get("realized_return")) if event.get("event_type") == "TRADE_CLOSED" else f"${float(event['underlying_price']):.2f}" if event.get("underlying_price") is not None else "—",
            "Detail": event.get("description") or "",
            "Priority": "critical" if event.get("event_type") in {"TRADE_ENTERED", "TRADE_CLOSED"} else "standard",
        })
    return rows


def notification_model(event, now=None):
    if not event:
        return None
    closed = event.get("event_type") == "TRADE_CLOSED"
    result = event.get("realized_return")
    winner = closed and result is not None and float(result) > 0
    loser = closed and result is not None and float(result) < 0
    metadata = event.get("metadata") or {}
    hold_minutes = metadata.get("hold_minutes")
    hold_text = "—"
    if hold_minutes is not None:
        total_seconds = max(0, int(float(hold_minutes) * 60))
        minutes, seconds = divmod(total_seconds, 60)
        hold_text = f"{minutes}m {seconds:02d}s"
    return {
        "title": "TRADE CLOSED — WINNER" if winner else "TRADE CLOSED — LOSER" if loser else "TRADE CLOSED" if closed else "NEW ENTRY",
        "treatment": "winning" if winner else "losing" if loser else "entry",
        "symbol": event.get("symbol") or "—",
        "direction": "CALL" if event.get("direction") == "Bullish" else "PUT" if event.get("direction") == "Bearish" else "—",
        "result": _signed_percent(result) if closed else None,
        "timestamp": format_eastern_seconds(event.get("event_timestamp")),
        "age": relative_age(event.get("event_timestamp"), now),
        "entry": event.get("entry_price"),
        "exit": event.get("exit_price"),
        "exit_reason": str(event.get("exit_reason") or "—").replace("_", " "),
        "score": event.get("rule_score"),
        "stop": metadata.get("stop"),
        "target": metadata.get("target_1"),
        "hold_time": hold_text,
        "description": event.get("description") or "",
    }


def notification_markup(model):
    if not model:
        return ""
    result = f'<strong class="ob-live-result">{escape(model["result"])}</strong>' if model.get("result") else ""
    if model["title"].startswith("TRADE CLOSED"):
        entry = f'${float(model["entry"]):.2f}' if model.get("entry") is not None else "—"
        exit_price = f'${float(model["exit"]):.2f}' if model.get("exit") is not None else "—"
        detail = f'Exit reason: {escape(model["exit_reason"])} · Held: {escape(model["hold_time"])} · Entry: {escape(entry)} · Exit: {escape(exit_price)}'
    else:
        stop = f'${float(model["stop"]):.2f}' if model.get("stop") is not None else "—"
        target = f'${float(model["target"]):.2f}' if model.get("target") is not None else "—"
        detail = f'Rule Score: {escape(str(model.get("score") or "—"))} · Stop: {escape(stop)} · Target: {escape(target)}'
    return (
        f'<section class="ob-live-notice ob-live-{escape(model["treatment"])}">'
        f'<div class="ob-live-kicker">{escape(model["title"])}</div>'
        f'<div class="ob-live-symbol">{escape(model["symbol"])} {escape(model["direction"])}</div>'
        f'{result}<div class="ob-live-detail">{escape(detail)} · {escape(model["timestamp"])} · {escape(model["age"])}</div>'
        f'</section>'
    )
