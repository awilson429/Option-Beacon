"""Deterministic, broker-free OB/BROAD simulated-capital policy.

The module is intentionally pure. It does not query providers, submit orders, or
change signal/exit logic. Persisted worker inputs are evaluated as if each lane
owned a separate paper brokerage account.
"""

from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum


CONTRACT_MULTIPLIER = 100
LANES = ("OB", "BROAD")


class DecisionState(StrEnum):
    TAKE = "TAKE"
    PASS = "PASS"
    BLOCKED = "BLOCKED"
    NO_CAPITAL = "NO_CAPITAL"
    RISK_LIMIT = "RISK_LIMIT"
    DATA_UNSAFE = "DATA_UNSAFE"


class DrawdownState(StrEnum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    REDUCED_RISK = "REDUCED_RISK"
    HALTED = "HALTED"


class ReadinessStatus(StrEnum):
    NOT_READY = "NOT_READY"
    EARLY_RESEARCH = "EARLY_RESEARCH"
    DEVELOPING = "DEVELOPING"
    PAPER_VALIDATED = "PAPER_VALIDATED"
    LIVE_CANDIDATE = "LIVE_CANDIDATE"


@dataclass(frozen=True)
class LaneCapitalConfig:
    lane: str
    starting_capital: float
    risk_per_trade_pct: float
    max_total_open_risk_pct: float = 1.5
    max_concurrent_positions: int = 3
    max_daily_loss_pct: float = 2.0
    drawdown_warning_pct: float = 5.0
    drawdown_reduced_pct: float = 8.0
    drawdown_halt_pct: float = 12.0
    reduced_risk_multiplier: float = 0.5
    max_spread_pct: float = 20.0
    min_open_interest: int = 50
    min_volume: int = 0
    stale_after_seconds: int = 300
    commission_per_contract: float = 0.65
    entry_slippage_fraction: float = 0.25
    exit_slippage_fraction: float = 0.25
    contract_multiplier: int = CONTRACT_MULTIPLIER

    @classmethod
    def for_lane(cls, lane: str, environ=None):
        env = os.environ if environ is None else environ
        lane = str(lane).upper()
        if lane not in LANES:
            raise ValueError(f"Unsupported capital lane: {lane}")
        defaults = {
            "OB": {"starting": 25_000, "risk": 0.50, "positions": 3},
            "BROAD": {"starting": 25_000, "risk": 0.25, "positions": 6},
        }[lane]
        prefix = f"{lane}_"
        return cls(
            lane=lane,
            starting_capital=_env_float(env, prefix + "STARTING_CAPITAL", defaults["starting"]),
            risk_per_trade_pct=_env_float(env, prefix + "RISK_PER_TRADE_PCT", defaults["risk"]),
            max_total_open_risk_pct=_env_float(env, prefix + "MAX_TOTAL_OPEN_RISK_PCT", 1.5),
            max_concurrent_positions=_env_int(env, prefix + "MAX_CONCURRENT_POSITIONS", defaults["positions"]),
            max_daily_loss_pct=_env_float(env, prefix + "MAX_DAILY_LOSS_PCT", 2.0),
            drawdown_warning_pct=_env_float(env, prefix + "DRAWDOWN_WARNING_PCT", 5.0),
            drawdown_reduced_pct=_env_float(env, prefix + "DRAWDOWN_REDUCED_PCT", 8.0),
            drawdown_halt_pct=_env_float(env, prefix + "DRAWDOWN_HALT_PCT", 12.0),
            reduced_risk_multiplier=_env_float(env, prefix + "REDUCED_RISK_MULTIPLIER", 0.5),
            max_spread_pct=_env_float(env, prefix + "MAX_SPREAD_PCT", 20.0),
            min_open_interest=_env_int(env, prefix + "MIN_OPEN_INTEREST", 50),
            min_volume=_env_int(env, prefix + "MIN_VOLUME", 0),
            stale_after_seconds=_env_int(env, prefix + "STALE_AFTER_SECONDS", 300),
            commission_per_contract=_env_float(env, prefix + "COMMISSION_PER_CONTRACT", 0.65),
            entry_slippage_fraction=_env_float(env, prefix + "ENTRY_SLIPPAGE_FRACTION", 0.25),
            exit_slippage_fraction=_env_float(env, prefix + "EXIT_SLIPPAGE_FRACTION", 0.25),
        )


@dataclass(frozen=True)
class AccountSnapshot:
    lane: str
    starting_equity: float
    current_equity: float
    cash_available: float
    capital_committed: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    fees: float = 0.0
    slippage: float = 0.0
    peak_equity: float = 0.0
    current_drawdown_pct: float = 0.0
    maximum_drawdown_pct: float = 0.0
    daily_starting_equity: float = 0.0
    daily_pnl: float = 0.0
    open_risk: float = 0.0
    open_positions: int = 0
    duplicate_exposures: tuple[str, ...] = ()


@dataclass(frozen=True)
class CapitalCandidate:
    opportunity_id: str
    symbol: str
    direction: str
    observed_at: datetime
    option_symbol: str | None = None
    expiration: str | None = None
    strike: float | None = None
    dte: int | None = None
    bid: float | None = None
    ask: float | None = None
    midpoint: float | None = None
    stop_price: float | None = None
    open_interest: int | None = None
    volume: int | None = None
    underlying_price: float | None = None
    maximum_chase: float | None = None
    data_complete: bool = True
    provider_healthy: bool = True
    opportunity_expired: bool = False


@dataclass(frozen=True)
class CapitalDecision:
    state: str
    reason_code: str
    explanation: str
    timestamp: datetime
    lane: str
    opportunity_id: str
    symbol: str
    direction: str
    proposed_contract: str | None = None
    proposed_quantity: int = 0
    proposed_capital_required: float = 0.0
    proposed_dollar_risk: float = 0.0
    proposed_account_risk_pct: float = 0.0
    theoretical_entry: float | None = None
    realistic_entry: float | None = None
    stop_fill: float | None = None
    risk_per_contract: float | None = None
    drawdown_state: str = DrawdownState.NORMAL

    def to_dict(self):
        values = asdict(self)
        values["timestamp"] = self.timestamp.isoformat()
        return values


def lane_configs(environ=None):
    return {lane: LaneCapitalConfig.for_lane(lane, environ) for lane in LANES}


def drawdown_state(account: AccountSnapshot, config: LaneCapitalConfig) -> DrawdownState:
    value = max(0.0, float(account.current_drawdown_pct or 0.0))
    if value >= config.drawdown_halt_pct:
        return DrawdownState.HALTED
    if value >= config.drawdown_reduced_pct:
        return DrawdownState.REDUCED_RISK
    if value >= config.drawdown_warning_pct:
        return DrawdownState.WARNING
    return DrawdownState.NORMAL


def realistic_entry_fill(candidate: CapitalCandidate, config: LaneCapitalConfig):
    bid, ask, midpoint = _quote(candidate)
    if bid is None:
        return None
    return round(midpoint + (ask - bid) * config.entry_slippage_fraction, 4)


def realistic_exit_fill(*, bid, ask, midpoint=None, config: LaneCapitalConfig):
    bid, ask = _finite(bid), _finite(ask)
    if bid is None or ask is None or bid < 0 or ask <= 0 or bid > ask:
        return None
    midpoint = _finite(midpoint)
    midpoint = midpoint if midpoint is not None else (bid + ask) / 2
    return round(max(0.0, midpoint - (ask - bid) * config.exit_slippage_fraction), 4)


def evaluate_capital_candidate(candidate: CapitalCandidate, account: AccountSnapshot,
                               config: LaneCapitalConfig, *, now=None) -> CapitalDecision:
    now = _aware(now or datetime.now(timezone.utc))
    state = drawdown_state(account, config)
    common = dict(timestamp=now, lane=config.lane, opportunity_id=candidate.opportunity_id,
                  symbol=str(candidate.symbol).upper(), direction=candidate.direction,
                  proposed_contract=candidate.option_symbol, drawdown_state=state)
    if account.lane != config.lane:
        return _decision(DecisionState.DATA_UNSAFE, "LANE_ATTRIBUTION_MISMATCH",
                         "Account state does not belong to this lane.", common)
    if not candidate.provider_healthy:
        return _decision(DecisionState.BLOCKED, "PROVIDER_OR_SYSTEM_DEGRADED",
                         "Provider or system health is degraded.", common)
    if not candidate.data_complete or not candidate.option_symbol:
        return _decision(DecisionState.DATA_UNSAFE, "REQUIRED_DATA_UNAVAILABLE",
                         "Required contract or risk data is unavailable.", common)
    age = max(0.0, (now - _aware(candidate.observed_at)).total_seconds())
    if age > config.stale_after_seconds:
        return _decision(DecisionState.DATA_UNSAFE, "DATA_STALE",
                         "The contract snapshot is too stale for capital deployment.", common)
    if candidate.opportunity_expired:
        return _decision(DecisionState.PASS, "OPPORTUNITY_EXPIRED",
                         "The opportunity expired before capital could be assigned.", common)
    quote = _quote(candidate)
    if quote[0] is None:
        return _decision(DecisionState.DATA_UNSAFE, "REQUIRED_DATA_UNAVAILABLE",
                         "A valid bid/ask quote is required.", common)
    bid, ask, midpoint = quote
    spread_pct = (ask - bid) / midpoint * 100 if midpoint else math.inf
    if spread_pct - config.max_spread_pct > 1e-9:
        return _decision(DecisionState.PASS, "CONTRACT_SPREAD_TOO_WIDE",
                         f"Contract spread {spread_pct:.1f}% exceeds the {config.max_spread_pct:.1f}% limit.", common)
    if candidate.open_interest is None or candidate.open_interest < config.min_open_interest:
        return _decision(DecisionState.PASS, "CONTRACT_LIQUIDITY_TOO_LOW",
                         "Contract open interest is below the lane minimum.", common)
    if candidate.volume is None or candidate.volume < config.min_volume:
        return _decision(DecisionState.PASS, "CONTRACT_LIQUIDITY_TOO_LOW",
                         "Contract volume is below the lane minimum.", common)
    entry_fill = realistic_entry_fill(candidate, config)
    stop = _finite(candidate.stop_price)
    if entry_fill is None or stop is None or stop <= 0 or stop >= entry_fill:
        return _decision(DecisionState.DATA_UNSAFE, "INVALID_STOP",
                         "A positive option stop below the realistic entry fill is required.", common)
    if candidate.maximum_chase is not None and candidate.underlying_price is not None:
        chased = (candidate.direction.upper() in {"CALL", "BULLISH"}
                  and candidate.underlying_price > candidate.maximum_chase) or (
                      candidate.direction.upper() in {"PUT", "BEARISH"}
                      and candidate.underlying_price < candidate.maximum_chase)
        if chased:
            return _decision(DecisionState.PASS, "ENTRY_BEYOND_MAXIMUM_CHASE",
                             "Entry exceeds the persisted maximum-chase boundary.", common)
    exposure_key = f"{candidate.symbol.upper()}:{candidate.direction.upper()}"
    if exposure_key in account.duplicate_exposures:
        return _decision(DecisionState.BLOCKED, "DUPLICATE_EXPOSURE",
                         "The lane already owns equivalent symbol and direction exposure.", common)
    daily_limit = account.daily_starting_equity * config.max_daily_loss_pct / 100
    if account.daily_pnl <= -daily_limit:
        return _decision(DecisionState.BLOCKED, "DAILY_LOSS_LIMIT_REACHED",
                         "No new capital: the lane daily loss limit has been reached.", common)
    if state == DrawdownState.HALTED:
        return _decision(DecisionState.BLOCKED, "DRAWDOWN_HALT",
                         "No new capital: the lane drawdown halt is active.", common)
    if account.open_positions >= config.max_concurrent_positions:
        return _decision(DecisionState.BLOCKED, "MAXIMUM_CONCURRENT_POSITIONS",
                         "The lane maximum concurrent-position limit is active.", common)

    stop_fill = max(0.0, stop - (ask - bid) * config.exit_slippage_fraction)
    round_trip_fees = config.commission_per_contract * 2
    risk_per_contract = ((entry_fill - stop_fill) * config.contract_multiplier
                         + round_trip_fees)
    risk_multiplier = config.reduced_risk_multiplier if state == DrawdownState.REDUCED_RISK else 1.0
    trade_budget = account.current_equity * config.risk_per_trade_pct / 100 * risk_multiplier
    total_open_limit = account.current_equity * config.max_total_open_risk_pct / 100
    open_risk_remaining = max(0.0, total_open_limit - account.open_risk)
    permitted_risk = min(trade_budget, open_risk_remaining)
    if account.open_risk > 0 and open_risk_remaining + 1e-9 < risk_per_contract:
        return _decision(DecisionState.RISK_LIMIT, "MAXIMUM_OPEN_RISK_REACHED",
                         "Remaining lane open-risk capacity cannot support one contract.", common,
                         theoretical_entry=midpoint, realistic_entry=entry_fill,
                         stop_fill=stop_fill, risk_per_contract=risk_per_contract)
    risk_quantity = math.floor(permitted_risk / risk_per_contract)
    if risk_quantity < 1:
        return _decision(DecisionState.RISK_LIMIT, "MINIMUM_POSITION_EXCEEDS_RISK_BUDGET",
                         "One contract exceeds the permitted account-risk budget.", common,
                         theoretical_entry=midpoint, realistic_entry=entry_fill,
                         stop_fill=stop_fill, risk_per_contract=risk_per_contract)
    capital_per_contract = entry_fill * config.contract_multiplier + config.commission_per_contract
    cash_quantity = math.floor(max(0.0, account.cash_available) / capital_per_contract)
    if cash_quantity < 1:
        return _decision(DecisionState.NO_CAPITAL, "INSUFFICIENT_BUYING_POWER",
                         "Available lane cash cannot fund one contract and its entry fee.", common,
                         theoretical_entry=midpoint, realistic_entry=entry_fill,
                         stop_fill=stop_fill, risk_per_contract=risk_per_contract)
    quantity = min(risk_quantity, cash_quantity)
    capital = round(quantity * capital_per_contract, 2)
    risk = round(quantity * risk_per_contract, 2)
    account_risk = risk / account.current_equity * 100 if account.current_equity else 0.0
    return _decision(DecisionState.TAKE, "ALL_RISK_CONTROLS_PASSED",
                     "Setup qualifies and all simulated-capital risk controls passed.", common,
                     proposed_quantity=quantity, proposed_capital_required=capital,
                     proposed_dollar_risk=risk, proposed_account_risk_pct=account_risk,
                     theoretical_entry=midpoint, realistic_entry=entry_fill,
                     stop_fill=stop_fill, risk_per_contract=risk_per_contract)


def execution_outcome(*, quantity, theoretical_entry, realistic_entry, exit_bid,
                      exit_ask, config: LaneCapitalConfig):
    exit_mid = (_finite(exit_bid) + _finite(exit_ask)) / 2 if _finite(exit_bid) is not None and _finite(exit_ask) is not None else None
    exit_fill = realistic_exit_fill(bid=exit_bid, ask=exit_ask, midpoint=exit_mid, config=config)
    if exit_fill is None:
        return None
    quantity = int(quantity)
    theoretical = round((exit_mid - theoretical_entry) * config.contract_multiplier * quantity, 2)
    gross_realistic = (exit_fill - realistic_entry) * config.contract_multiplier * quantity
    fees = round(config.commission_per_contract * 2 * quantity, 2)
    realistic = round(gross_realistic - fees, 2)
    slippage = round(max(0.0, theoretical - gross_realistic), 2)
    return {"theoretical_exit": round(exit_mid, 4), "realistic_exit": exit_fill,
            "theoretical_pnl": theoretical, "realistic_pnl": realistic,
            "fees": fees, "slippage": slippage}


def capital_efficiency(net_pnl, average_capital_deployed):
    deployed = _finite(average_capital_deployed)
    return float(net_pnl) / deployed * 100 if deployed and deployed > 0 else None


def classify_readiness(metrics) -> ReadinessStatus:
    trades = int(metrics.get("trades") or 0)
    sessions = int(metrics.get("sessions") or 0)
    expectancy = _finite(metrics.get("expectancy"))
    profit_factor = _finite(metrics.get("profit_factor"))
    drawdown = _finite(metrics.get("maximum_drawdown_pct"))
    completeness = _finite(metrics.get("data_completeness")) or 0.0
    execution = _finite(metrics.get("execution_evidence")) or 0.0
    regimes = int(metrics.get("regimes") or 0)
    risk_coverage = bool(metrics.get("risk_control_coverage"))
    stable = bool(metrics.get("stable_across_regimes"))
    if not risk_coverage or completeness < 0.80 or (trades >= 20 and (expectancy is None or expectancy <= 0)):
        return ReadinessStatus.NOT_READY
    if trades < 30 or sessions < 10:
        return ReadinessStatus.EARLY_RESEARCH
    developing = (expectancy is not None and expectancy > 0 and profit_factor is not None
                  and profit_factor > 1 and drawdown is not None and drawdown <= 12
                  and completeness >= 0.90 and execution >= 0.80)
    if not developing:
        return ReadinessStatus.NOT_READY
    if trades < 100 or sessions < 30:
        return ReadinessStatus.DEVELOPING
    validated = (profit_factor >= 1.20 and drawdown <= 10 and completeness >= 0.95
                 and execution >= 0.95 and regimes >= 3)
    if not validated:
        return ReadinessStatus.DEVELOPING
    if trades < 250 or sessions < 60:
        return ReadinessStatus.PAPER_VALIDATED
    candidate = (profit_factor >= 1.30 and drawdown <= 8 and completeness >= 0.98
                 and execution >= 0.98 and regimes >= 4 and stable)
    return ReadinessStatus.LIVE_CANDIDATE if candidate else ReadinessStatus.PAPER_VALIDATED


def _decision(state, reason, explanation, common, **values):
    return CapitalDecision(state=str(state), reason_code=reason, explanation=explanation,
                           **common, **values)


def _quote(candidate):
    bid, ask, midpoint = _finite(candidate.bid), _finite(candidate.ask), _finite(candidate.midpoint)
    if bid is None or ask is None or bid < 0 or ask <= 0 or bid > ask:
        return None, None, None
    midpoint = midpoint if midpoint is not None else (bid + ask) / 2
    if midpoint <= 0 or midpoint < bid or midpoint > ask:
        return None, None, None
    return bid, ask, midpoint


def _finite(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _aware(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _env_float(env, key, default):
    return float(env.get(key, default))


def _env_int(env, key, default):
    return int(env.get(key, default))
