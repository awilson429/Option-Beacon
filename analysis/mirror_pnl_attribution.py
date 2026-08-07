"""Read-only MIRROR P&L attribution from persisted lifecycle records."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


EASTERN = ZoneInfo("America/New_York")


def build_session_audit(
    authoritative_events, opportunities, mirror_rows, paper_trades, paper_journal,
    *, session_date,
):
    """Join a session strictly by opportunity ID and calculate persisted attribution."""
    events = [row for row in authoritative_events if _session(row.get("event_timestamp")) == session_date]
    entries = {}
    exits = {}
    for row in sorted(events, key=lambda item: _dt(item.get("event_timestamp"))):
        identity = str(row.get("opportunity_id") or "")
        if row.get("event_type") == "TRADE_ENTERED" and identity:
            entries.setdefault(identity, row)
        elif row.get("event_type") == "TRADE_CLOSED" and identity:
            exits[identity] = row
    opportunity_by_id = {str(row.get("id")): row for row in opportunities if row.get("id")}
    mirror_by_id = {str(row.get("opportunity_id")): row for row in mirror_rows if row.get("opportunity_id")}
    source_by_trade = {
        str(row.get("trade_id")): str(row.get("source_signal_id") or row.get("opportunity_id"))
        for row in paper_trades if row.get("trade_id")
    }
    broad_by_source = {}
    for row in sorted(paper_journal, key=lambda item: _dt(item.get("created_at")), reverse=True):
        metadata = _json(row.get("metadata_json"))
        if metadata.get("journal_type") not in (None, "ENTRY_DECISION"):
            continue
        source = source_by_trade.get(str(row.get("trade_id") or ""))
        if source:
            broad_by_source.setdefault(source, row)

    trades = []
    for identity, entry in sorted(entries.items(), key=lambda item: _dt(item[1].get("event_timestamp"))):
        exit_event = exits.get(identity, {})
        opportunity = opportunity_by_id.get(identity, {})
        mirror = mirror_by_id.get(identity, {})
        broad = broad_by_source.get(identity)
        quantity = _integer(mirror.get("quantity")) or 0
        multiplier = _integer(mirror.get("contract_multiplier")) or 100
        debit = _number(mirror.get("total_debit"))
        entry_mid = _number(mirror.get("entry_mid"))
        entry_fill = _number(mirror.get("entry_fill"))
        exit_mid = _number(mirror.get("exit_mid"))
        exit_fill = _number(mirror.get("exit_fill"))
        entry_penalty = _cost(entry_fill, entry_mid, quantity, multiplier)
        exit_penalty = _cost(exit_mid, exit_fill, quantity, multiplier)
        option_return = _number(mirror.get("realized_return_percent"))
        pnl = _number(mirror.get("realized_pnl"))
        underlying_entry = _number(entry.get("entry_price"))
        if underlying_entry is None:
            underlying_entry = _number(entry.get("underlying_price"))
        strike = _number(mirror.get("strike"))
        option_type = str(mirror.get("option_type") or "").upper()
        moneyness = _moneyness(option_type, strike, underlying_entry)
        entry_metadata = _json(mirror.get("metadata_json"))
        broad_disposition = "PENDING"
        broad_reason = "—"
        if broad:
            broad_disposition = "OPENED" if bool(broad.get("accepted")) else "REJECTED"
            broad_reason = str(broad.get("reason_code") or "UNKNOWN") if not bool(broad.get("accepted")) else "—"
        trades.append({
            "opportunity_id": identity,
            "symbol": entry.get("symbol"),
            "direction": _direction(entry.get("direction")),
            "authoritative_entry_at": entry.get("event_timestamp"),
            "authoritative_exit_at": exit_event.get("event_timestamp"),
            "underlying_entry": underlying_entry,
            "underlying_exit": _number(exit_event.get("exit_price")) or _number(exit_event.get("underlying_price")),
            "authoritative_return_percent": _number(exit_event.get("realized_return")),
            "authoritative_result": _result(_number(exit_event.get("realized_return"))),
            "confidence": _number(entry.get("rule_score")) if entry.get("rule_score") is not None else _number(opportunity.get("confidence")),
            "trigger": _number(opportunity.get("entry_reference")),
            "authoritative_hold_minutes": _minutes(entry.get("event_timestamp"), exit_event.get("event_timestamp")),
            "authoritative_exit_reason": exit_event.get("exit_reason"),
            "mirror_trade_id": mirror.get("mirror_trade_id"),
            "mirror_disposition": mirror.get("disposition_code") or "NOT_RECORDED",
            "option_symbol": mirror.get("option_symbol"),
            "expiration": mirror.get("expiration"),
            "dte": _integer(mirror.get("dte")),
            "strike": strike,
            "option_type": option_type or None,
            "quantity": quantity or None,
            "entry_bid": _number(mirror.get("entry_bid")),
            "entry_ask": _number(mirror.get("entry_ask")),
            "entry_mid": entry_mid,
            "entry_fill": entry_fill,
            "exit_bid": _number(mirror.get("exit_bid")),
            "exit_ask": _number(mirror.get("exit_ask")),
            "exit_mid": exit_mid,
            "exit_fill": exit_fill,
            "debit": debit,
            "option_return_percent": option_return,
            "option_pnl": pnl,
            "mirror_hold_minutes": _minutes(mirror.get("opened_at"), mirror.get("exit_quote_at")),
            "entry_fill_penalty": entry_penalty,
            "exit_fill_penalty": exit_penalty,
            "total_fill_penalty": _sum_known(entry_penalty, exit_penalty),
            "moneyness_status": moneyness[0],
            "moneyness_dollars": moneyness[1],
            "moneyness_percent": moneyness[2],
            "spread_dollars": _number(mirror.get("spread_dollars")),
            "spread_percent": _number(mirror.get("spread_percent")),
            "delta": _number(entry_metadata.get("delta")),
            "implied_volatility": _number(entry_metadata.get("implied_volatility")),
            "broad_disposition": broad_disposition,
            "broad_reason": broad_reason,
            "mirror_exit_reason": mirror.get("authoritative_exit_reason"),
            "mfe": None,
            "mae": None,
        })
    _capital_shares(trades)
    return {"session_date": str(session_date), "trades": trades, "summary": _summary(trades, mirror_rows)}


def _summary(trades, all_mirror_rows):
    mirror = [row for row in trades if row["mirror_trade_id"] and row["option_pnl"] is not None]
    winners = [row for row in mirror if row["option_pnl"] > 0]
    losers = [row for row in mirror if row["option_pnl"] < 0]
    gross_profit = sum(row["option_pnl"] for row in winners)
    gross_loss = sum(row["option_pnl"] for row in losers)
    cumulative = sum(row["debit"] or 0 for row in mirror)
    peak = _peak_capital([row for row in all_mirror_rows if str(row.get("opportunity_id")) in {item["opportunity_id"] for item in trades}])
    return {
        "authoritative_trades": len(trades),
        "authoritative_wins": sum(row["authoritative_result"] == "WIN" for row in trades),
        "authoritative_losses": sum(row["authoritative_result"] == "LOSS" for row in trades),
        "average_authoritative_return_percent": _average(row["authoritative_return_percent"] for row in trades),
        "mirror_trades": len(mirror), "mirror_wins": len(winners), "mirror_losses": len(losers),
        "gross_profit": gross_profit, "gross_loss": gross_loss, "net_pnl": gross_profit + gross_loss,
        "average_winner_dollars": _average(row["option_pnl"] for row in winners),
        "average_loser_dollars": _average(row["option_pnl"] for row in losers),
        "average_winner_percent": _average(row["option_return_percent"] for row in winners),
        "average_loser_percent": _average(row["option_return_percent"] for row in losers),
        "profit_factor": gross_profit / abs(gross_loss) if gross_loss else None,
        "largest_winner": max((row["option_pnl"] for row in winners), default=None),
        "largest_loser": min((row["option_pnl"] for row in losers), default=None),
        "cumulative_gross_debit": cumulative, "peak_simultaneous_debit": peak,
        "return_on_peak_percent": (gross_profit + gross_loss) / peak * 100 if peak else None,
        "return_on_cumulative_debit_percent": (gross_profit + gross_loss) / cumulative * 100 if cumulative else None,
        "total_identifiable_fill_penalty": _sum_values(row["total_fill_penalty"] for row in mirror),
        "average_option_return_percent": _average(row["option_return_percent"] for row in mirror),
    }


def _peak_capital(rows):
    points = []
    for row in rows:
        debit = _number(row.get("total_debit"))
        opened = _dt_or_none(row.get("opened_at"))
        closed = _dt_or_none(row.get("exit_quote_at"))
        if debit is None or opened is None:
            continue
        points.append((opened, 1, debit))
        if closed:
            points.append((closed, -1, debit))
    deployed = peak = 0.0
    for _, kind, debit in sorted(points, key=lambda item: (item[0], item[1])):
        deployed += debit * kind
        peak = max(peak, deployed)
    return peak


def _capital_shares(trades):
    total = sum(row["debit"] or 0 for row in trades)
    for row in trades:
        row["capital_share_percent"] = row["debit"] / total * 100 if total and row["debit"] is not None else None


def _moneyness(option_type, strike, underlying):
    if strike is None or not underlying or option_type not in {"CALL", "PUT"}:
        return (None, None, None)
    signed = underlying - strike if option_type == "CALL" else strike - underlying
    status = "ITM" if signed > 0 else "OTM" if signed < 0 else "ATM"
    return status, signed, signed / underlying * 100


def _cost(worse, better, quantity, multiplier):
    return (worse - better) * quantity * multiplier if None not in (worse, better) and quantity else None


def _minutes(start, end):
    first, last = _dt_or_none(start), _dt_or_none(end)
    return (last - first).total_seconds() / 60 if first and last else None


def _direction(value):
    value = str(value or "").upper()
    return "CALL" if value in {"BULLISH", "CALL"} else "PUT" if value in {"BEARISH", "PUT"} else None


def _result(value):
    return "WIN" if value is not None and value > 0 else "LOSS" if value is not None and value < 0 else "FLAT" if value is not None else "UNKNOWN"


def _session(value):
    parsed = _dt_or_none(value)
    return parsed.astimezone(EASTERN).date() if parsed else None


def _dt(value):
    return _dt_or_none(value) or datetime.min.replace(tzinfo=timezone.utc)


def _dt_or_none(value):
    if not value:
        return None
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
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
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _integer(value):
    number = _number(value)
    return int(number) if number is not None else None


def _average(values):
    known = [value for value in values if value is not None]
    return sum(known) / len(known) if known else None


def _sum_known(*values):
    return sum(values) if all(value is not None for value in values) else None


def _sum_values(values):
    known = [value for value in values if value is not None]
    return sum(known) if known else None
