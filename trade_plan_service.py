"""Safe scanner integration for paper-only Trade Plan lifecycle persistence."""

from __future__ import annotations

import logging

from trade_plan_engine import SUPPORTED_SYMBOLS, build_structured_trade_plan
from trade_plan_journal import (
    DEFAULT_TRADE_PLAN_JOURNAL,
    load_trade_plan_journal,
    save_trade_plan,
)
from trade_plan_lifecycle import update_trade_plan
from trade_plan_models import PlanStatus


LOGGER = logging.getLogger(__name__)
TERMINAL_STATUSES = {
    PlanStatus.INVALIDATED,
    PlanStatus.EXPIRED,
    PlanStatus.CLOSED,
}


def process_scanner_trade_plan(result, path=DEFAULT_TRADE_PLAN_JOURNAL):
    """Create or advance one SPY/QQQ paper plan without disrupting scanning."""
    result = dict(result or {})
    symbol = str(result.get("symbol") or "").upper()
    if symbol not in SUPPORTED_SYMBOLS:
        return None
    try:
        evaluation = build_structured_trade_plan(
            result,
            evaluation_timestamp=result.get("timestamp"),
        )
        open_plans = [
            plan
            for plan in load_trade_plan_journal(path)
            if plan.symbol == evaluation.symbol
            and plan.direction == evaluation.direction
            and plan.setup_name == evaluation.setup_name
            and plan.status not in TERMINAL_STATUSES
        ]
        if not open_plans:
            save_trade_plan(evaluation, path)
            return evaluation
        plan = open_plans[-1]
        plan.current_status["latest_evaluation"] = {
            "status": evaluation.status.value,
            "missing_requirements": evaluation.missing_requirements,
            "late_entry_risk": evaluation.late_entry_risk.value,
            "market_data_freshness": evaluation.market_data_freshness,
        }
        candles = int(plan.current_status.get("hold_candles") or 0) + 1
        if plan.status == PlanStatus.ACTIVE:
            update_trade_plan(
                plan,
                current_price=evaluation.current_underlying_price,
                current_timestamp=evaluation.market_data_freshness["evaluation_timestamp"],
                market_timestamp=evaluation.market_timestamp,
                candles_elapsed=candles,
            )
        elif evaluation.status == PlanStatus.INVALIDATED:
            update_trade_plan(
                plan,
                current_price=evaluation.current_underlying_price,
                current_timestamp=evaluation.market_data_freshness["evaluation_timestamp"],
                market_timestamp=evaluation.market_timestamp,
                candles_elapsed=candles,
                technical_valid=False,
            )
        elif evaluation.status == PlanStatus.EXPIRED:
            update_trade_plan(
                plan,
                current_price=evaluation.current_underlying_price,
                current_timestamp=evaluation.market_data_freshness["evaluation_timestamp"],
                market_timestamp=evaluation.market_timestamp,
                candles_elapsed=plan.maximum_hold_candles,
            )
        elif evaluation.status == PlanStatus.READY:
            update_trade_plan(
                plan,
                current_price=evaluation.current_underlying_price,
                current_timestamp=evaluation.market_data_freshness["evaluation_timestamp"],
                market_timestamp=evaluation.market_timestamp,
                candles_elapsed=candles,
            )
        else:
            plan.status = evaluation.status
            plan.current_status["state"] = evaluation.status.value
            plan.current_underlying_price = evaluation.current_underlying_price
            plan.market_timestamp = evaluation.market_timestamp
        save_trade_plan(plan, path)
        return plan
    except Exception:
        LOGGER.exception("Trade Plan Engine update failed for %s", symbol or "unknown")
        return None
