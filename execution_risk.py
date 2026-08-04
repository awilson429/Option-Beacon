"""Deterministic risk gate and daily state for paper execution."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from execution_config import ExecutionConfig


EASTERN = ZoneInfo("America/New_York")
MAX_AUTHORITATIVE_ENTRY_AGE_MINUTES = 60


@dataclass(frozen=True)
class DailyRiskState:
    trading_date: object
    trades_entered: int
    realized_pnl: float
    wins: int
    losses: int
    consecutive_losses: int
    open_exposure: float
    last_loss_time: datetime | None


@dataclass(frozen=True)
class ExecutionDecision:
    eligible: bool
    reason: str
    position_size: int = 0
    maximum_cost: float = 0.0
    paper_fill_price: float | None = None


def paper_fill_price(trade, config: ExecutionConfig) -> float | None:
    try:
        ask = float(trade.ask)
        mid = float(trade.mid)
    except (TypeError, ValueError):
        return None
    weight = min(1.0, max(0.0, config.entry_fill_toward_ask))
    return round(mid + (ask - mid) * weight, 4)


def daily_risk_state(positions, now=None) -> DailyRiskState:
    checked = _aware(now or datetime.now(timezone.utc)).astimezone(EASTERN)
    today = checked.date()
    entered = [p for p in positions if _aware(p.entry_time).astimezone(EASTERN).date() == today]
    closed = [p for p in entered if p.exit_time is not None]
    pnl_values = [position_dollar_pnl(p) for p in closed]
    pnl_values = [value for value in pnl_values if value is not None]
    losses = [p for p in closed if (position_dollar_pnl(p) or 0) < 0]
    consecutive = 0
    for position in sorted(closed, key=lambda p: _aware(p.exit_time), reverse=True):
        if (position_dollar_pnl(position) or 0) < 0:
            consecutive += 1
        else:
            break
    open_positions = [p for p in positions if p.status == "OPEN"]
    return DailyRiskState(
        trading_date=today,
        trades_entered=len(entered),
        realized_pnl=sum(pnl_values),
        wins=sum(value > 0 for value in pnl_values),
        losses=sum(value < 0 for value in pnl_values),
        consecutive_losses=consecutive,
        open_exposure=sum(float(getattr(p, "total_entry_cost", 0) or 0) for p in open_positions),
        last_loss_time=max((_aware(p.exit_time) for p in losses), default=None),
    )


def evaluate_execution(result, trade, positions, config, *, now=None, market_open=True):
    checked = _aware(now or datetime.now(timezone.utc))
    current_et = checked.astimezone(EASTERN)
    state = daily_risk_state(positions, checked)
    if config.mode != "PAPER":
        return ExecutionDecision(False, "MODE_NOT_CONFIGURED")
    if not config.trading_enabled:
        return ExecutionDecision(False, "TRADING_DISABLED")
    if not market_open or current_et.weekday() >= 5:
        return ExecutionDecision(False, "MARKET_CLOSED")
    if (result or {}).get("_authoritative_entry_id"):
        try:
            entered_at = _aware((result or {}).get("timestamp"))
        except (TypeError, ValueError):
            return ExecutionDecision(False, "AUTHORITATIVE_ENTRY_TIME_UNAVAILABLE")
        age_minutes = max(0.0, (checked - entered_at).total_seconds() / 60)
        if age_minutes > MAX_AUTHORITATIVE_ENTRY_AGE_MINUTES:
            return ExecutionDecision(False, "STALE_AUTHORITATIVE_ENTRY")
    if not config.earliest_entry_time <= current_et.time().replace(tzinfo=None) <= config.latest_entry_time:
        return ExecutionDecision(False, "OUTSIDE_ENTRY_WINDOW")
    score = _number(result.get("score") or result.get("confidence"))
    if score is None or score < config.min_beacon_score:
        return ExecutionDecision(False, "SCORE_TOO_LOW")
    symbol = str(result.get("symbol") or "").upper()
    if config.allowed_symbols and symbol not in config.allowed_symbols:
        return ExecutionDecision(False, "SYMBOL_NOT_ALLOWED")
    if any(p.status == "OPEN" and p.trade_id == trade.trade_id for p in positions):
        return ExecutionDecision(False, "DUPLICATE_SIGNAL")
    if sum(p.status == "OPEN" for p in positions) >= config.max_open_positions:
        return ExecutionDecision(False, "MAX_OPEN_POSITIONS")
    if state.trades_entered >= config.max_trades_per_day:
        return ExecutionDecision(False, "DAILY_TRADE_LIMIT")
    if state.realized_pnl <= -abs(config.max_daily_loss_dollars):
        return ExecutionDecision(False, "DAILY_LOSS_LIMIT")
    if state.consecutive_losses >= config.max_consecutive_losses:
        return ExecutionDecision(False, "CONSECUTIVE_LOSS_LIMIT")
    if state.last_loss_time and checked < state.last_loss_time + timedelta(minutes=config.loss_cooldown_minutes):
        return ExecutionDecision(False, "LOSS_COOLDOWN")
    if trade.status != "QUALIFIED" or not trade.entry_snapshot_complete:
        return ExecutionDecision(False, "CONTRACT_UNAVAILABLE")
    if trade.spread_percent is None or trade.spread_percent > config.max_spread_percent:
        return ExecutionDecision(False, "LIQUIDITY_REJECTED")
    if (trade.open_interest or 0) < config.min_open_interest or (trade.volume or 0) < config.min_volume:
        return ExecutionDecision(False, "LIQUIDITY_REJECTED")
    fill = paper_fill_price(trade, config)
    if fill is None:
        return ExecutionDecision(False, "CONTRACT_UNAVAILABLE")
    cost = fill * 100
    quantity = math.floor(config.max_dollars_per_trade / cost)
    if quantity < 1:
        return ExecutionDecision(False, "CONTRACT_TOO_EXPENSIVE", maximum_cost=config.max_dollars_per_trade, paper_fill_price=fill)
    return ExecutionDecision(True, "ELIGIBLE", quantity, round(quantity * cost, 2), fill)


def position_dollar_pnl(position):
    exit_mid = getattr(position, "exit_mid", None)
    if exit_mid is None:
        return None
    quantity = int(getattr(position, "quantity", 1) or 1)
    return round((float(exit_mid) - float(position.entry_mid)) * 100 * quantity, 2)


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _aware(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
