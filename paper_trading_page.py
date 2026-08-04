"""Read-only view models for the authoritative SQL-backed PAPER workspace."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


EASTERN = ZoneInfo("America/New_York")


def paper_execution_funnel(authoritative_events, journal_rows, captures, now):
    """Reconcile today's durable authoritative entries with PAPER dispositions."""
    today = _aware(now).astimezone(EASTERN).date()
    entries = {
        event.get("opportunity_id") or event.get("trade_id")
        for event in authoritative_events
        if event.get("event_type") == "TRADE_ENTERED"
        and _same_eastern_date(event.get("event_timestamp"), today)
    }
    source_by_trade = {capture.trade_id: capture.source_signal_id for capture in captures}
    dispositions = {}
    decision_profiles = Counter()
    for row in journal_rows:
        if not _same_eastern_date(row.get("created_at"), today):
            continue
        metadata = _json(row.get("metadata_json"))
        if metadata.get("journal_type") not in (None, "ENTRY_DECISION"):
            continue
        source_id = source_by_trade.get(row.get("trade_id"))
        if source_id in entries and source_id not in dispositions:
            dispositions[source_id] = row
            profile = str(metadata.get("simulation_profile") or "LEGACY_UNLABELED")
            decision_profiles[profile] += 1
    opened = sum(bool(row.get("accepted")) for row in dispositions.values())
    rejected = len(dispositions) - opened
    reasons = Counter(
        str(row.get("reason_code") or "OTHER")
        for row in dispositions.values()
        if not bool(row.get("accepted"))
    )
    authoritative = len(entries)
    return {
        "authoritative_entries": authoritative,
        "evaluated": len(dispositions),
        "opened": opened,
        "rejected": rejected,
        "pending": max(0, authoritative - len(dispositions)),
        "participation_rate": opened / authoritative * 100 if authoritative else 0.0,
        "rejection_counts": dict(sorted(reasons.items())),
        "decisions_by_profile": dict(sorted(decision_profiles.items())),
        "reconciled": len(dispositions) + max(0, authoritative - len(dispositions)) == authoritative,
    }


def execution_status_model(positions, journal_rows, worker_health=None):
    latest = journal_rows[0] if journal_rows else None
    reason = str((latest or {}).get("reason_code") or "")
    if reason == "TRADING_DISABLED":
        trading = "DISABLED — NO NEW ENTRIES"
        treatment = "warning"
    elif reason == "MODE_NOT_CONFIGURED":
        trading = "NOT CONFIGURED"
        treatment = "warning"
    elif latest:
        trading = "ENABLED AT LAST DECISION"
        treatment = "active"
    elif (worker_health or {}).get("last_success_at"):
        trading = "ENABLED — WORKER ACTIVE"
        treatment = "active"
    else:
        trading = "AWAITING WORKER STATE"
        treatment = "neutral"
    modes = {str(getattr(position, "execution_mode", "PAPER")).upper() for position in positions}
    mode = next(iter(modes), "PAPER") if len(modes) <= 1 else "PAPER"
    return {
        "mode": mode,
        "trading": trading,
        "treatment": treatment,
        "writer": "RAILWAY",
        "ui_role": "READ ONLY",
    }


def open_paper_position_rows(positions, config, now):
    rows = []
    for position in positions:
        if position.status != "OPEN":
            continue
        quantity = int(position.quantity or 1)
        current_value = position.current_mid * 100 * quantity
        pnl = (position.current_mid - position.entry_mid) * 100 * quantity
        rows.append({
            "Underlying": position.ticker,
            "Contract": position.option_symbol,
            "Type": str(position.option_type or position.direction).upper(),
            "Strike": f"${position.strike:.2f}",
            "Expiration": position.expiration,
            "Qty": quantity,
            "Entry": f"${position.entry_mid:.2f}",
            "Current": f"${position.current_mid:.2f}",
            "Total Debit": f"${position.total_entry_cost:,.2f}",
            "Current Value": f"${current_value:,.2f}",
            "Unrealized P&L": f"${pnl:+,.2f}",
            "Return": f"{position.current_return_percent:+.2f}%",
            "MFE": f"{position.max_favorable_excursion_percent:+.2f}%",
            "MAE": f"{position.max_adverse_excursion_percent:+.2f}%",
            "Entered": _et(position.entry_time),
            "Hold": _duration(position.entry_time, now),
            "Stop": f"${position.entry_mid * (1 + config.stop_loss_percent / 100):.2f}",
            "Target": f"${position.entry_mid * (1 + config.profit_target_percent / 100):.2f}",
            "State": "MANAGED",
        })
    return rows


def closed_paper_trade_rows(positions, *, now, today_only=True):
    today = now.astimezone(EASTERN).date()
    closed = [position for position in positions if position.status != "OPEN" and position.exit_time]
    if today_only:
        closed = [position for position in closed if position.exit_time.astimezone(EASTERN).date() == today]
    closed.sort(key=lambda position: position.exit_time, reverse=True)
    rows = []
    for position in closed:
        quantity = int(position.quantity or 1)
        pnl = ((position.exit_mid or position.entry_mid) - position.entry_mid) * 100 * quantity
        rows.append({
            "Underlying": position.ticker,
            "Contract": position.option_symbol,
            "Direction": str(position.option_type or position.direction).upper(),
            "Qty": quantity,
            "Entered": _et(position.entry_time),
            "Exited": _et(position.exit_time),
            "Entry": f"${position.entry_mid:.2f}",
            "Exit": f"${position.exit_mid:.2f}" if position.exit_mid is not None else "—",
            "Total Debit": f"${position.total_entry_cost:,.2f}",
            "Realized P&L": f"${pnl:+,.2f}",
            "Return": f"{(position.exit_return_percent or 0):+.2f}%",
            "Hold": _duration(position.entry_time, position.exit_time),
            "MFE": f"{position.max_favorable_excursion_percent:+.2f}%",
            "MAE": f"{position.max_adverse_excursion_percent:+.2f}%",
            "Exit Reason": position.exit_reason or "—",
        })
    return rows


def execution_journal_rows(rows, captures=()):
    scores = {capture.trade_id: capture.scanner_score for capture in captures}
    result = []
    for row in rows:
        reason = str(row.get("reason_code") or "—")
        accepted = bool(row.get("accepted"))
        risk = _json(row.get("risk_state_json"))
        metadata = _json(row.get("metadata_json"))
        result.append({
            "Timestamp": _et(row.get("created_at")),
            "Symbol": row.get("symbol") or "—",
            "Contract": row.get("option_symbol") or "—",
            "Decision": "ACCEPTED" if accepted else "REJECTED",
            "Reason": reason,
            "Profile": metadata.get("simulation_profile") or "LEGACY_UNLABELED",
            "Effective Min Score": metadata.get("effective_min_score") or "—",
            "Score": scores.get(row.get("trade_id")) or "—",
            "Allocation": f"${float(row.get('allocation_dollars') or 0):,.2f}",
            "Quantity": int(row.get("quantity") or 0),
            "Liquidity": "REJECTED" if reason in {
                "LIQUIDITY_REJECTED", "SPREAD_TOO_WIDE",
                "INSUFFICIENT_OPEN_INTEREST", "INSUFFICIENT_VOLUME",
            } else "PASSED" if accepted else "NOT RECORDED",
            "Cooldown": "BLOCKED" if reason == "LOSS_COOLDOWN" else "PASSED" if accepted else "NOT RECORDED",
            "Duplicate": "BLOCKED" if reason == "DUPLICATE_SIGNAL" else "PASSED" if accepted else "NOT RECORDED",
            "Daily Risk": json.dumps(risk, sort_keys=True) if risk else "—",
        })
    return result


def _json(value):
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value or "{}")
    except Exception:
        return {}


def _aware(value):
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _same_eastern_date(value, expected):
    try:
        return _aware(value).astimezone(EASTERN).date() == expected
    except (TypeError, ValueError):
        return False


def _et(value):
    if not value:
        return "—"
    local = _aware(value).astimezone(EASTERN)
    hour = local.strftime("%I").lstrip("0") or "12"
    return f"{local:%b} {local.day}, {local.year} {hour}:{local:%M:%S %p} ET"


def _duration(start, end):
    seconds = max(0, int((_aware(end) - _aware(start)).total_seconds()))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m" if hours else f"{minutes}m {seconds:02d}s"
