"""Read-only BROAD filter effectiveness analytics over persisted execution rows."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo


EASTERN = ZoneInfo("America/New_York")
MIN_CLASSIFICATION_SAMPLE = 10
PROTECTIVE_MAX_PROFIT_FACTOR = 0.80
COSTLY_MIN_PROFIT_FACTOR = 1.25
ACCEPTED_REASONS = {"ELIGIBLE", "ACCEPTED"}


def _number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _aware(value):
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result


def _session(value):
    try:
        return _aware(value).astimezone(EASTERN).date()
    except (TypeError, ValueError):
        return None


def _json(value):
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _profit_factor(values):
    gross_profit = sum(value for value in values if value > 0)
    gross_loss = abs(sum(value for value in values if value < 0))
    if not gross_loss:
        return math.inf if gross_profit else None
    return gross_profit / gross_loss


def effectiveness_label(*, realized_count, net_pnl, profit_factor):
    """Transparent outcome label; never a production-rule recommendation."""
    if realized_count < MIN_CLASSIFICATION_SAMPLE:
        return "INSUFFICIENT DATA"
    if net_pnl < 0 and profit_factor is not None and profit_factor <= PROTECTIVE_MAX_PROFIT_FACTOR:
        return "PROTECTIVE"
    if net_pnl > 0 and profit_factor is not None and profit_factor >= COSTLY_MIN_PROFIT_FACTOR:
        return "COSTLY FILTER"
    return "NEUTRAL / INCONCLUSIVE"


def _peak_capital(rows):
    events = []
    for row in rows:
        debit = _number(row.get("total_debit"))
        opened = row.get("opened_at")
        if debit is None or not opened:
            continue
        start = _aware(opened)
        end_value = row.get("exit_quote_at") or row.get("updated_at")
        end = _aware(end_value) if end_value else start
        events.extend(((start, 1, debit), (max(start, end), -1, debit)))
    capital = peak = 0.0
    for _, kind, debit in sorted(events, key=lambda item: (item[0], item[1])):
        capital += debit if kind == 1 else -debit
        peak = max(peak, capital)
    return peak


def _average(values):
    present = [value for value in values if value is not None]
    return sum(present) / len(present) if present else None


def _aggregate(label, trades, *, rejected):
    opened = [trade for trade in trades if trade.get("mirror_opened")]
    realized = [trade for trade in opened if trade.get("mirror_pnl") is not None]
    pnl = [trade["mirror_pnl"] for trade in realized]
    winners = [trade for trade in realized if trade["mirror_pnl"] > 0]
    losers = [trade for trade in realized if trade["mirror_pnl"] < 0]
    gross_profit = sum(trade["mirror_pnl"] for trade in winners)
    gross_loss = abs(sum(trade["mirror_pnl"] for trade in losers))
    profit_factor = _profit_factor(pnl)
    telemetry = [trade for trade in opened if trade.get("telemetry_available")]
    auth_closed = [trade for trade in trades if trade.get("authoritative_return") is not None]
    auth_winners = [trade for trade in trades if (trade.get("authoritative_return") or 0) > 0]
    auth_losers = [trade for trade in trades if trade.get("authoritative_return") is not None and trade["authoritative_return"] < 0]
    cumulative_debit = sum(trade.get("debit") or 0 for trade in opened)
    peak_capital = _peak_capital([trade["mirror_row"] for trade in opened])
    midpoint_pnl = [trade.get("midpoint_pnl") for trade in realized]
    fill_drag = [trade.get("fill_drag") for trade in realized]
    reversals = [trade for trade in telemetry if trade.get("profitable_to_final_loser")]
    result = {
        "reason": label, "rejected": rejected, "n": len(trades),
        "mirror_opened": len(opened), "mirror_realized": len(realized),
        "mirror_wins": len(winners), "mirror_losses": len(losers),
        "mirror_win_rate": len(winners) / len(realized) * 100 if realized else None,
        "gross_profit": gross_profit, "gross_loss": gross_loss,
        "net_pnl": sum(pnl),
        "average_winner": _average([trade["mirror_pnl"] for trade in winners]),
        "average_loser": _average([trade["mirror_pnl"] for trade in losers]),
        "profit_factor": profit_factor,
        "average_mirror_return": _average([trade.get("mirror_return") for trade in realized]),
        "average_authoritative_return": _average([trade.get("authoritative_return") for trade in auth_closed]),
        "authoritative_win_rate": sum(trade["authoritative_return"] > 0 for trade in auth_closed) / len(auth_closed) * 100 if auth_closed else None,
        "peak_capital": peak_capital, "cumulative_debit": cumulative_debit,
        "average_debit": _average([trade.get("debit") for trade in opened]),
        "average_dte": _average([_number(trade.get("dte")) for trade in opened]),
        "average_moneyness_percent": _average([trade.get("moneyness_percent") for trade in opened]),
        "average_delta": _average([trade.get("delta") for trade in opened]),
        "average_open_interest": _average([_number(trade.get("open_interest")) for trade in opened]),
        "average_volume": _average([_number(trade.get("volume")) for trade in opened]),
        "return_on_peak_capital": sum(pnl) / peak_capital * 100 if peak_capital else None,
        "return_on_cumulative_debit": sum(pnl) / cumulative_debit * 100 if cumulative_debit else None,
        "average_entry_spread_percent": _average([trade.get("entry_spread_percent") for trade in opened]),
        "average_exit_spread_percent": _average([trade.get("exit_spread_percent") for trade in realized]),
        "average_fill_drag": _average(fill_drag), "total_fill_drag": sum(value for value in fill_drag if value is not None),
        "midpoint_pnl": sum(value for value in midpoint_pnl if value is not None),
        "average_mfe": _average([trade.get("mfe") for trade in telemetry]),
        "average_mae": _average([trade.get("mae") for trade in telemetry]),
        "average_peak_return": _average([trade.get("peak_return") for trade in telemetry]),
        "average_final_return": _average([trade.get("mirror_return") for trade in telemetry]),
        "average_giveback": _average([trade.get("giveback") for trade in telemetry if trade.get("ever_profitable")]),
        "ever_profitable_count": sum(bool(trade.get("ever_profitable")) for trade in telemetry),
        "profitable_to_final_loser_count": len(reversals),
        "reversal_average_peak_return": _average([trade.get("peak_return") for trade in reversals]),
        "reversal_average_final_return": _average([trade.get("mirror_return") for trade in reversals]),
        "reversal_average_giveback": _average([trade.get("giveback") for trade in reversals]),
        "telemetry_coverage": len(telemetry) / len(opened) * 100 if opened else None,
        "delta_coverage": sum(trade.get("delta") is not None for trade in opened) / len(opened) * 100 if opened else None,
        "iv_coverage": sum(trade.get("iv") is not None for trade in opened) / len(opened) * 100 if opened else None,
        "authoritative_winners_rejected": len(auth_winners) if rejected else 0,
        "rejected_auth_winner_mirror_wins": sum((trade.get("mirror_pnl") or 0) > 0 for trade in auth_winners) if rejected else 0,
        "rejected_auth_winner_mirror_losses": sum(trade.get("mirror_pnl") is not None and trade["mirror_pnl"] < 0 for trade in auth_winners) if rejected else 0,
        "rejected_auth_winner_net_pnl": sum(trade.get("mirror_pnl") or 0 for trade in auth_winners) if rejected else 0,
        "authoritative_losers_rejected": len(auth_losers) if rejected else 0,
        "rejected_auth_loser_mirror_wins": sum((trade.get("mirror_pnl") or 0) > 0 for trade in auth_losers) if rejected else 0,
        "rejected_auth_loser_mirror_losses": sum(trade.get("mirror_pnl") is not None and trade["mirror_pnl"] < 0 for trade in auth_losers) if rejected else 0,
        "rejected_auth_loser_net_pnl": sum(trade.get("mirror_pnl") or 0 for trade in auth_losers) if rejected else 0,
        "trades": trades,
    }
    result["effectiveness"] = effectiveness_label(
        realized_count=len(realized), net_pnl=result["net_pnl"], profit_factor=profit_factor)
    result["low_sample"] = len(realized) < MIN_CLASSIFICATION_SAMPLE
    return result


def broad_filter_effectiveness(authoritative_events, broad_journal, broad_captures,
                               mirror_rows, mirror_marks, mirror_runtime, *,
                               window="ALL MIRROR EXPERIMENT", now=None):
    """Join exact durable IDs and produce read-only filter outcome analytics."""
    now = now or datetime.now(timezone.utc)
    entries, exits = {}, {}
    for event in authoritative_events:
        identity = event.get("opportunity_id") or event.get("trade_id")
        if not identity:
            continue
        if event.get("event_type") == "TRADE_ENTERED":
            entries.setdefault(str(identity), event)
        elif event.get("event_type") == "TRADE_CLOSED":
            exits[str(identity)] = event
    start_text = (mirror_runtime or {}).get("experiment_start_date")
    try:
        experiment_start = date.fromisoformat(str(start_text)) if start_text else None
    except ValueError:
        experiment_start = None
    sessions = sorted({session for event in entries.values() if (session := _session(event.get("event_timestamp")))
                       and (not experiment_start or session >= experiment_start)})
    today = now.astimezone(EASTERN).date()
    if window == "TODAY":
        selected = {today}
    elif window == "PREVIOUS SESSION":
        prior = [session for session in sessions if session < today]
        selected = {prior[-1]} if prior else set()
    elif window == "LAST 5 SESSIONS":
        selected = set(sessions[-5:])
    elif window == "LAST 10 SESSIONS":
        selected = set(sessions[-10:])
    else:
        selected = set(sessions)

    source_by_trade = {str(capture.trade_id): str(capture.source_signal_id) for capture in broad_captures}
    decisions = {}
    for row in sorted(broad_journal, key=lambda value: str(value.get("created_at") or "")):
        if _json(row.get("metadata_json")).get("journal_type", "ENTRY_DECISION") != "ENTRY_DECISION":
            continue
        source = source_by_trade.get(str(row.get("trade_id")))
        if source and source not in decisions:
            decisions[source] = row
    mirrors = {str(row.get("opportunity_id")): row for row in mirror_rows if row.get("opportunity_id")}
    marks_by_trade = defaultdict(list)
    for mark in mirror_marks:
        marks_by_trade[str(mark.get("mirror_trade_id"))].append(mark)

    details = []
    for identity, entry in entries.items():
        entry_session = _session(entry.get("event_timestamp"))
        if entry_session not in selected:
            continue
        decision, mirror, exit_event = decisions.get(identity), mirrors.get(identity), exits.get(identity)
        if decision is None:
            continue
        reason = str(decision.get("reason_code") or "UNKNOWN DISPOSITION")
        accepted = bool((decision or {}).get("accepted")) or reason in ACCEPTED_REASONS
        marks = marks_by_trade.get(str((mirror or {}).get("mirror_trade_id")), [])
        valid_marks = [mark for mark in marks if _number(mark.get("return_pct")) is not None
                       or (_number(mark.get("valid_mark_count")) or 0) > 0]
        peak_values = [_number(mark.get("peak_return_pct")) for mark in valid_marks]
        mfe_values = [_number(mark.get("mfe_pct")) for mark in valid_marks]
        mae_values = [_number(mark.get("mae_pct")) for mark in valid_marks]
        peak = max((value for value in peak_values if value is not None), default=None)
        mfe = max((value for value in mfe_values if value is not None), default=None)
        mae = min((value for value in mae_values if value is not None), default=None)
        final_return = _number((mirror or {}).get("realized_return_percent"))
        ever_profitable = peak is not None and peak > 0
        giveback = max(peak - final_return, 0) if ever_profitable and final_return is not None else None
        entry_mid, exit_mid = _number((mirror or {}).get("entry_mid")), _number((mirror or {}).get("exit_mid"))
        entry_fill, exit_fill = _number((mirror or {}).get("entry_fill")), _number((mirror or {}).get("exit_fill"))
        quantity = int((mirror or {}).get("quantity") or 1)
        multiplier = int((mirror or {}).get("contract_multiplier") or 100)
        midpoint_pnl = (exit_mid - entry_mid) * quantity * multiplier if entry_mid is not None and exit_mid is not None else None
        actual_pnl = _number((mirror or {}).get("realized_pnl"))
        fill_drag = midpoint_pnl - actual_pnl if midpoint_pnl is not None and actual_pnl is not None else None
        exit_bid, exit_ask = _number((mirror or {}).get("exit_bid")), _number((mirror or {}).get("exit_ask"))
        exit_spread_pct = ((exit_ask - exit_bid) / exit_mid * 100
                           if exit_bid is not None and exit_ask is not None and exit_mid else None)
        metadata = _json((mirror or {}).get("metadata_json"))
        strike = _number((mirror or {}).get("strike"))
        underlying_entry = _number((mirror or {}).get("underlying_entry_price"))
        details.append({
            "opportunity_id": identity, "session": entry_session.isoformat(),
            "symbol": entry.get("symbol"), "direction": entry.get("direction"),
            "broad_reason": "BROAD OPENED" if accepted else reason,
            "broad_accepted": accepted,
            "authoritative_return": _number((exit_event or {}).get("realized_return")),
            "mirror_contract": (mirror or {}).get("option_symbol"),
            "mirror_opened": bool((mirror or {}).get("opened_at")),
            "mirror_pnl": actual_pnl, "mirror_return": final_return,
            "mfe": mfe, "mae": mae, "peak_return": peak, "giveback": giveback,
            "ever_profitable": ever_profitable,
            "profitable_to_final_loser": bool(ever_profitable and final_return is not None and final_return < 0),
            "telemetry_available": bool(valid_marks),
            "debit": _number((mirror or {}).get("total_debit")),
            "entry_spread_percent": _number((mirror or {}).get("spread_percent")),
            "exit_spread_percent": exit_spread_pct,
            "midpoint_pnl": midpoint_pnl, "fill_drag": fill_drag,
            "dte": (mirror or {}).get("dte"), "strike": strike,
            "underlying_entry_price": underlying_entry,
            "moneyness_percent": ((strike / underlying_entry) - 1) * 100
            if strike is not None and underlying_entry else None,
            "delta": _number(metadata.get("delta")), "iv": _number(metadata.get("iv")),
            "open_interest": (mirror or {}).get("open_interest"),
            "volume": (mirror or {}).get("option_volume"),
            "mirror_row": mirror or {},
        })
    grouped = defaultdict(list)
    for trade in details:
        grouped[trade["broad_reason"]].append(trade)
    groups = [_aggregate(reason, trades, rejected=reason != "BROAD OPENED")
              for reason, trades in sorted(grouped.items())]
    benchmark = next((group for group in groups if group["reason"] == "BROAD OPENED"), None)
    rejected_trades = [trade for trade in details if not trade["broad_accepted"]]
    comparison = [group for group in groups if group["reason"] == "BROAD OPENED"]
    if rejected_trades:
        comparison.append(_aggregate("BROAD REJECTED", rejected_trades, rejected=True))
    classified = [group for group in groups if group["reason"] != "BROAD OPENED" and not group["low_sample"]]
    insights = {
        "most_protective": min((group for group in classified if group["effectiveness"] == "PROTECTIVE"),
                               key=lambda group: group["net_pnl"], default=None),
        "most_costly": max((group for group in classified if group["effectiveness"] == "COSTLY FILTER"),
                           key=lambda group: group["net_pnl"], default=None),
        "largest_sample": max((group for group in groups if group["reason"] != "BROAD OPENED"),
                              key=lambda group: group["mirror_realized"], default=None),
    }
    return {"window": window, "sessions": [session.isoformat() for session in sorted(selected)],
            "groups": groups, "benchmark": benchmark, "comparison": comparison,
            "insights": insights, "trades": details,
            "experiment_start_date": experiment_start.isoformat() if experiment_start else None}
