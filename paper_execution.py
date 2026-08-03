"""Scheduled, broker-independent PAPER execution orchestration."""

from __future__ import annotations

import json
import logging
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


LOGGER = logging.getLogger(__name__)
DEFAULT_EXECUTION_JOURNAL = "paper_execution_journal.jsonl"


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
    LOGGER.info(json.dumps({"event": "paper_cycle_started", "scanner_id": scanner_id, "run_number": run_number}, sort_keys=True))
    positions = refreshed_positions
    if positions is None:
        positions = refresh_paper_positions(
            config=config, now=checked_at, quote_provider=quote_provider,
            trade_ledger=trade_ledger, position_store=position_store,
            journal=journal, scanner_id=scanner_id, run_number=run_number,
        )

    opened = []
    decisions = []
    values = latest_results.values() if isinstance(latest_results, dict) else latest_results
    for result in values or []:
        try:
            trade = capture_qualified_signal(
                result,
                repository=trade_ledger,
                provider=chain_provider,
                now=checked_at,
            )
            if trade is None:
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
            )
            decisions.append(decision)
            if not decision.eligible:
                LOGGER.info(json.dumps({
                    "event": "paper_entry_rejected", "scanner_id": scanner_id,
                    "run_number": run_number, "symbol": trade.ticker,
                    "option_symbol": trade.option_symbol, "decision_reason": decision.reason,
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
                    "event": "paper_entry_opened", "scanner_id": scanner_id,
                    "run_number": run_number, "position_id": position.trade_id,
                    "symbol": position.ticker, "option_symbol": position.option_symbol,
                    "quantity": position.quantity, "debit": position.total_entry_cost,
                }, sort_keys=True))
        except Exception:
            LOGGER.exception("Paper execution failed safely for %s", (result or {}).get("symbol"))
    position_store.save(positions)
    LOGGER.info(json.dumps({
        "event": "paper_cycle_completed", "scanner_id": scanner_id,
        "run_number": run_number, "opened": len(opened),
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
    closed_pnl = [position_dollar_pnl(position) or 0.0 for position in closed_today]
    open_pnl = sum(
        (position.current_mid - position.entry_mid) * 100 * position.quantity
        for position in open_positions
    )
    return {
        "mode": config.mode,
        "trading_enabled": config.trading_enabled,
        "account_size": config.account_size,
        "today_pnl": state.realized_pnl + open_pnl,
        "open_pnl": open_pnl,
        "realized_pnl": state.realized_pnl,
        "trades_today": state.trades_entered,
        "open_positions": len(open_positions),
        "daily_loss_remaining": max(0.0, config.max_daily_loss_dollars + state.realized_pnl),
        "deployed_capital": sum(position.total_entry_cost for position in open_positions),
        "wins": sum(value > 0 for value in closed_pnl),
        "losses": sum(value < 0 for value in closed_pnl),
        "win_rate": (sum(value > 0 for value in closed_pnl) / len(closed_pnl) * 100) if closed_pnl else 0.0,
        "average_winner": (sum(value for value in closed_pnl if value > 0) / sum(value > 0 for value in closed_pnl)) if any(value > 0 for value in closed_pnl) else 0.0,
        "average_loser": (sum(value for value in closed_pnl if value < 0) / sum(value < 0 for value in closed_pnl)) if any(value < 0 for value in closed_pnl) else 0.0,
    }
