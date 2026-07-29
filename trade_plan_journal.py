"""Schema-versioned persistence isolated from legacy OptionBeacon journals."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import tempfile

from trade_plan_models import TradePlan


DEFAULT_TRADE_PLAN_JOURNAL = "trade_plan_journal.jsonl"
LOGGER = logging.getLogger(__name__)


def load_trade_plan_journal(path=DEFAULT_TRADE_PLAN_JOURNAL) -> list[TradePlan]:
    """Load new plans and skip legacy/unknown rows without deleting them."""
    journal = Path(path)
    if not journal.exists():
        return []
    plans = []
    with journal.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                if "trade_plan_id" not in payload:
                    LOGGER.info("Legacy journal row retained but not adapted at %s:%s", journal, line_number)
                    continue
                plans.append(TradePlan.from_dict(payload))
            except Exception:
                LOGGER.exception("Could not load trade-plan journal row %s:%s", journal, line_number)
    return plans


def rewrite_trade_plan_journal(plans, path=DEFAULT_TRADE_PLAN_JOURNAL):
    journal = Path(path)
    journal.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=journal.parent,
            prefix=f".{journal.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            for plan in plans:
                handle.write(json.dumps(plan.to_dict(), sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, journal)
    except Exception:
        if temporary:
            temporary.unlink(missing_ok=True)
        LOGGER.exception("Could not write trade-plan journal %s", journal)
        raise
    return journal


def save_trade_plan(plan, path=DEFAULT_TRADE_PLAN_JOURNAL):
    """Insert or update current state while preserving the frozen original snapshot."""
    plans = load_trade_plan_journal(path)
    for index, existing in enumerate(plans):
        if existing.trade_plan_id == plan.trade_plan_id:
            if existing.original_signal_snapshot != plan.original_signal_snapshot:
                raise ValueError("original signal snapshot cannot be changed")
            plans[index] = plan
            break
    else:
        plans.append(plan)
    rewrite_trade_plan_journal(plans, path)
    return plan


def load_legacy_trade_outcomes(path="signal_history.jsonl"):
    """Compatibility adapter that delegates to the existing tolerant loader."""
    from signal_history import load_trade_outcomes

    return load_trade_outcomes(path)


def paper_journal_row(plan: TradePlan) -> dict:
    """Return the expanded journal schema without changing legacy records."""
    status = plan.current_status
    outcome = plan.final_outcome
    ready_event = next(
        (event for event in plan.lifecycle_events if event.event_type.value == "ENTRY_READY"),
        None,
    )
    return {
        "schema_version": plan.schema_version,
        "trade_id": plan.trade_plan_id,
        "trade_plan_id": plan.trade_plan_id,
        "symbol": plan.symbol,
        "direction": plan.direction,
        "option_bias": plan.option_bias,
        "setup_name": plan.setup_name,
        "signal_timestamp": plan.signal_timestamp.isoformat(),
        "ready_timestamp": ready_event.timestamp.isoformat() if ready_event else None,
        "entry_timestamp": status.get("entry_timestamp"),
        "exit_timestamp": outcome.exit_timestamp.isoformat() if outcome else None,
        "signal_underlying_price": plan.underlying_price_at_signal,
        "entry_underlying_price": status.get("entry_underlying_price"),
        "exit_underlying_price": outcome.exit_underlying_price if outcome else None,
        "initial_stop": plan.initial_stop,
        "final_stop": plan.current_stop,
        "target_1": plan.target_1,
        "target_2": plan.target_2,
        "breakeven_trigger": plan.breakeven_trigger,
        "trailing_stop_method": plan.trailing_stop_method,
        "confidence_score": plan.confidence_score,
        "late_entry_risk": plan.late_entry_risk.value,
        "risk_reward_target_1": plan.risk_reward_target_1,
        "risk_reward_target_2": plan.risk_reward_target_2,
        "exit_reason": outcome.exit_reason.value if outcome else None,
        "maximum_favorable_excursion": outcome.maximum_favorable_excursion if outcome else status.get("mfe"),
        "maximum_adverse_excursion": outcome.maximum_adverse_excursion if outcome else status.get("mae"),
        "hold_time_minutes": outcome.hold_time_minutes if outcome else None,
        "hold_time_candles": outcome.hold_time_candles if outcome else status.get("hold_candles"),
        "final_result": plan.status.value,
        "return_percentage": outcome.realized_return_estimate if outcome else None,
        "original_trade_plan_snapshot": plan.to_dict()["original_signal_snapshot"],
        "lifecycle_events": plan.to_dict()["lifecycle_events"],
        "created_at": plan.signal_timestamp.isoformat(),
        "updated_at": plan.market_timestamp.isoformat(),
    }
