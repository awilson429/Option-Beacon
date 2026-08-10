"""Scheduled, broker-independent PAPER execution orchestration."""

from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from execution_config import ExecutionConfig
from execution_risk import EASTERN, daily_risk_state, evaluate_execution, position_dollar_pnl
from option_position_tracker import (
    OptionPositionStore,
    position_from_trade,
    refresh_option_positions,
)
from option_trade_engine import OptionTradeLedger, capture_qualified_signal
from signal_history import deserialize_trade_outcome


LOGGER = logging.getLogger(__name__)
DEFAULT_EXECUTION_JOURNAL = "paper_execution_journal.jsonl"


class AuthoritativeEntryProjectionError(RuntimeError):
    """Raised when a durable entry cannot be projected without inventing data."""


def pending_authoritative_entries(repository, latest_results, paper_repository, *, limit=5000):
    """Project durable TRADE_ENTERED events into PAPER candidates exactly once."""
    by_symbol = {
        str((result or {}).get("symbol") or symbol).upper(): result
        for symbol, result in (latest_results or {}).items()
    } if isinstance(latest_results, dict) else {
        str((result or {}).get("symbol") or "").upper(): result
        for result in latest_results or []
    }
    candidates = []
    dispositioned = paper_repository.dispositioned_source_signal_ids()
    events = repository.list_trade_event_summaries(
        limit=limit, event_type="TRADE_ENTERED"
    )
    for event in reversed(events):
        opportunity_id = event.get("opportunity_id") or event.get("trade_id")
        if not opportunity_id or opportunity_id in dispositioned:
            continue
        opportunity = repository.get_opportunity(opportunity_id=opportunity_id) or {}
        payload = (opportunity.get("metadata") or {}).get("trade_outcome")
        if not payload:
            raise AuthoritativeEntryProjectionError(
                f"Authoritative entry {opportunity_id} has no outcome payload."
            )
        try:
            record = deserialize_trade_outcome(payload)
        except Exception as exc:
            raise AuthoritativeEntryProjectionError(
                f"Authoritative entry {opportunity_id} has an invalid outcome payload."
            ) from exc
        result = dict(by_symbol.get(record.symbol.upper()) or {})
        result.update({
            "_authoritative_entry_id": opportunity_id,
            "_authoritative_event_id": event.get("id"),
            "symbol": record.symbol,
            "price": result.get("price") or event.get("underlying_price") or record.entry,
            "timestamp": record.entry_time or record.timestamp,
            "confidence": record.confidence,
            "score": event.get("rule_score") if event.get("rule_score") is not None else result.get("score"),
            "bias": record.direction,
            "trade_plan": {
                "direction": record.direction,
                "setup_type": record.setup,
                "trigger_price": record.entry,
                "technical_stop": record.stop,
                "target_1": record.target_1,
                "target_2": record.target_2,
                "target_3": record.target_3,
            },
            "entry_timing_reason": "Authoritative TRADE_ENTERED lifecycle transition.",
        })
        candidates.append(result)
    return candidates


class ExecutionJournal:
    def __init__(self, path=DEFAULT_EXECUTION_JOURNAL):
        self.path = Path(path)

    def append(self, *, checked_at, result, trade, decision, **context):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "timestamp": checked_at.isoformat(),
            "symbol": str((result or {}).get("symbol") or "").upper(),
            "source_signal_id": getattr(trade, "source_signal_id", None),
            "trade_id": getattr(trade, "trade_id", None),
            "eligible": decision.eligible,
            "reason": decision.reason,
            "position_size": decision.position_size,
            "maximum_cost": decision.maximum_cost,
            "paper_fill_price": decision.paper_fill_price,
            "execution_mode": "PAPER",
            "scanner_id": context.get("scanner_id"),
            "run_number": context.get("run_number"),
            "risk_state": context.get("risk_state") or {},
            "simulation_profile": getattr(context.get("execution_config"), "simulation_profile", None),
            "effective_min_score": getattr(context.get("execution_config"), "min_beacon_score", None),
            "journal_type": context.get("journal_type", "ENTRY_DECISION"),
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")

    def records(self):
        rows = []
        if not self.path.exists():
            return rows
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            try:
                if line.strip():
                    rows.append(json.loads(line))
            except Exception:
                LOGGER.warning("Skipping malformed execution journal row %s", line_number)
        return rows


def run_paper_execution(
    latest_results,
    *,
    config=None,
    now=None,
    market_open=True,
    chain_provider=None,
    quote_provider=None,
    trade_ledger=None,
    position_store=None,
    journal=None,
    scanner_id=None,
    run_number=None,
    refreshed_positions=None,
):
    """Refresh exits first, then evaluate and persist new PAPER entries."""
    config = config or ExecutionConfig.from_environment()
    checked_at = now or datetime.now(timezone.utc)
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=timezone.utc)
    trade_ledger = trade_ledger or OptionTradeLedger()
    position_store = position_store or OptionPositionStore()
    journal = journal or ExecutionJournal()
    values = list(latest_results.values()) if isinstance(latest_results, dict) else list(latest_results or [])
    LOGGER.info(json.dumps({
        "event": "paper_cycle_started", "scanner_id": scanner_id,
        "run_number": run_number, "candidates_received": len(values),
    }, sort_keys=True))
    positions = refreshed_positions
    if positions is None:
        positions = refresh_paper_positions(
            config=config, now=checked_at, quote_provider=quote_provider,
            trade_ledger=trade_ledger, position_store=position_store,
            journal=journal, scanner_id=scanner_id, run_number=run_number,
        )

    opened = []
    decisions = []
    rejected = 0
    for result in values:
        try:
            trade = capture_qualified_signal(
                result,
                repository=trade_ledger,
                provider=chain_provider,
                now=checked_at,
            )
            if trade is None:
                LOGGER.info(json.dumps({
                    "event": "broad_authoritative_handoff", "scanner_id": scanner_id,
                    "run_number": run_number,
                    "opportunity_id": result.get("_authoritative_entry_id"),
                    "symbol": str((result or {}).get("symbol") or "").upper(),
                    "disposition": "SKIPPED",
                    "reason": "NOT_AUTHORITATIVE_OR_NOT_QUALIFIED",
                }, sort_keys=True))
                continue
            decision = evaluate_execution(
                result, trade, positions, config, now=checked_at, market_open=market_open
            )
            risk_state = asdict(daily_risk_state(positions, checked_at))
            risk_state["trading_date"] = str(risk_state["trading_date"])
            if risk_state["last_loss_time"] is not None:
                risk_state["last_loss_time"] = risk_state["last_loss_time"].isoformat()
            journal.append(
                checked_at=checked_at, result=result, trade=trade, decision=decision,
                scanner_id=scanner_id, run_number=run_number, risk_state=risk_state,
                execution_config=config,
            )
            decisions.append(decision)
            if not decision.eligible:
                rejected += 1
                LOGGER.info(json.dumps({
                    "event": "broad_authoritative_handoff", "scanner_id": scanner_id,
                    "run_number": run_number, "symbol": trade.ticker,
                    "opportunity_id": result.get("_authoritative_entry_id"),
                    "option_symbol": trade.option_symbol, "disposition": "REJECTED",
                    "reason": decision.reason,
                }, sort_keys=True))
                continue
            position = position_from_trade(
                trade,
                execution_time=checked_at,
                fill_price=decision.paper_fill_price,
                quantity=decision.position_size,
                scanner_score=result.get("score") or result.get("confidence"),
            )
            if position is not None:
                positions.append(position)
                opened.append(position)
                position_store.save(positions)
                LOGGER.info(json.dumps({
                    "event": "broad_authoritative_handoff", "scanner_id": scanner_id,
                    "run_number": run_number, "position_id": position.trade_id,
                    "opportunity_id": result.get("_authoritative_entry_id"),
                    "symbol": position.ticker, "option_symbol": position.option_symbol,
                    "quantity": position.quantity, "debit": position.total_entry_cost,
                    "disposition": "OPENED", "reason": "ELIGIBLE",
                }, sort_keys=True))
        except Exception as exc:
            LOGGER.exception(json.dumps({
                "event": "broad_authoritative_handoff", "scanner_id": scanner_id,
                "run_number": run_number,
                "opportunity_id": (result or {}).get("_authoritative_entry_id"),
                "symbol": str((result or {}).get("symbol") or "").upper(),
                "disposition": "FAILED", "reason": type(exc).__name__,
            }, sort_keys=True))
    position_store.save(positions)
    LOGGER.info(json.dumps({
        "event": "paper_cycle_completed", "scanner_id": scanner_id,
        "run_number": run_number, "opened": len(opened),
        "candidates_received": len(values), "candidates_evaluated": len(decisions),
        "candidates_rejected": rejected, "candidates_accepted": len(opened),
        "candidates_opened": len(opened),
        "open_positions": sum(p.status == "OPEN" for p in positions),
    }, sort_keys=True))
    return {"positions": positions, "opened": opened, "decisions": decisions}


def refresh_paper_positions(
    *, config, now, quote_provider=None, trade_ledger=None, position_store, journal=None,
    scanner_id=None, run_number=None,
):
    """Restore and refresh durable positions before the underlying scan starts."""
    previous = {position.trade_id: position for position in position_store.load()}
    LOGGER.info(json.dumps({
        "event": "paper_state_restored", "scanner_id": scanner_id,
        "run_number": run_number,
        "open_positions": sum(p.status == "OPEN" for p in previous.values()),
    }, sort_keys=True))
    positions = refresh_option_positions(
        position_store=position_store,
        trade_ledger=trade_ledger,
        provider=quote_provider,
        current_time=now,
        profit_target_percent=config.profit_target_percent,
        stop_loss_percent=config.stop_loss_percent,
        max_hold_minutes=config.max_hold_minutes,
        force_close_end_of_day=config.force_close_end_of_day,
        synchronize_new_captures=False,
        quote_failure_callback=(
            lambda position, reason: journal.append_refresh_failure(
                position=position, reason=reason, checked_at=now,
                scanner_id=scanner_id, run_number=run_number,
            )
        ) if journal is not None and hasattr(journal, "append_refresh_failure") else None,
    )
    LOGGER.info(json.dumps({
        "event": "paper_positions_refreshed", "scanner_id": scanner_id,
        "run_number": run_number, "open_positions": sum(p.status == "OPEN" for p in positions),
    }, sort_keys=True))
    for position in positions:
        prior = previous.get(position.trade_id)
        if prior is not None and prior.status == "OPEN" and position.status != "OPEN":
            event = {
                "scanner_id": scanner_id, "run_number": run_number,
                "position_id": position.trade_id, "symbol": position.ticker,
                "option_symbol": position.option_symbol, "decision_reason": position.exit_reason,
                "realized_pnl": position_dollar_pnl(position),
                "duration_minutes": int((position.exit_time - position.entry_time).total_seconds() / 60),
            }
            LOGGER.info(json.dumps({"event": "paper_exit_processed", **event}, sort_keys=True))
            LOGGER.info(json.dumps({"event": "paper_trade_closed", **event}, sort_keys=True))
    return positions


def paper_account_summary(positions, *, config=None, now=None):
    config = config or ExecutionConfig.from_environment()
    state = daily_risk_state(positions, now)
    open_positions = [position for position in positions if position.status == "OPEN"]
    closed_today = [
        position for position in positions
        if position.exit_time is not None
        and position.exit_time.astimezone(EASTERN).date() == state.trading_date
    ]
    closed_positions = [position for position in positions if position.exit_time is not None]
    closed_pnl = [position_dollar_pnl(position) or 0.0 for position in closed_today]
    all_closed_pnl = [position_dollar_pnl(position) or 0.0 for position in closed_positions]
    open_pnl = sum(
        (position.current_mid - position.entry_mid) * 100 * position.quantity
        for position in open_positions
    )
    total_realized = sum(all_closed_pnl)
    total_pnl = total_realized + open_pnl
    winners = [value for value in all_closed_pnl if value > 0]
    losers = [value for value in all_closed_pnl if value < 0]
    peak_deployed = _peak_deployed_capital(positions)
    intraday_drawdown = _intraday_drawdown(closed_today, open_pnl)
    return {
        "mode": config.mode,
        "simulation_profile": config.simulation_profile,
        "trading_enabled": config.trading_enabled,
        "account_size": config.account_size,
        "starting_balance": config.account_size,
        "current_equity": config.account_size + total_pnl,
        "total_pnl": total_pnl,
        "total_return_percent": total_pnl / config.account_size * 100 if config.account_size else 0.0,
        "today_pnl": state.realized_pnl + open_pnl,
        "open_pnl": open_pnl,
        "realized_pnl": state.realized_pnl,
        "total_realized_pnl": total_realized,
        "trades_today": state.trades_entered,
        "trades_closed_today": len(closed_today),
        "trades_closed_total": len(closed_positions),
        "open_positions": len(open_positions),
        "daily_loss_remaining": max(0.0, config.max_daily_loss_dollars + state.realized_pnl),
        "deployed_capital": sum(position.total_entry_cost for position in open_positions),
        "peak_deployed_capital": peak_deployed,
        "max_intraday_drawdown": intraday_drawdown,
        "wins": len(winners),
        "losses": len(losers),
        "win_rate": len(winners) / len(all_closed_pnl) * 100 if all_closed_pnl else 0.0,
        "average_winner": sum(winners) / len(winners) if winners else 0.0,
        "average_loser": sum(losers) / len(losers) if losers else 0.0,
        "profit_factor": sum(winners) / abs(sum(losers)) if losers else math.inf if winners else 0.0,
    }


def _peak_deployed_capital(positions):
    events = []
    for position in positions:
        cost = float(position.total_entry_cost or 0.0)
        events.append((position.entry_time, 1, cost))
        if position.exit_time is not None:
            events.append((position.exit_time, 0, -cost))
    deployed = peak = 0.0
    for _, _, change in sorted(events, key=lambda item: (item[0], item[1])):
        deployed += change
        peak = max(peak, deployed)
    return peak


def _intraday_drawdown(closed_today, open_pnl):
    running = peak = drawdown = 0.0
    for position in sorted(closed_today, key=lambda item: item.exit_time):
        running += position_dollar_pnl(position) or 0.0
        peak = max(peak, running)
        drawdown = max(drawdown, peak - running)
    running += open_pnl
    peak = max(peak, running)
    return max(drawdown, peak - running)
