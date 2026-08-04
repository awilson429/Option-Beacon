"""Central, broker-independent paper execution configuration."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, fields, replace
from datetime import time


@dataclass(frozen=True)
class ExecutionConfig:
    simulation_profile: str = "SAFE"
    mode: str = "PAPER"
    trading_enabled: bool = False
    account_size: float = 5000.0
    max_dollars_per_trade: float = 250.0
    max_total_deployed_capital: float = 1250.0
    max_trades_per_day: int = 3
    max_open_positions: int = 1
    max_daily_loss_dollars: float = 100.0
    max_consecutive_losses: int = 2
    loss_cooldown_minutes: int = 30
    min_beacon_score: float = 92.0
    earliest_entry_time: time = time(9, 45)
    latest_entry_time: time = time(15, 0)
    allowed_symbols: tuple[str, ...] = ()
    profit_target_percent: float = 50.0
    stop_loss_percent: float = -30.0
    max_hold_minutes: int = 120
    trailing_profit_enabled: bool = False
    force_close_end_of_day: bool = True
    max_spread_percent: float = 20.0
    min_open_interest: int = 50
    min_volume: int = 0
    entry_fill_toward_ask: float = 0.5

    @classmethod
    def from_environment(cls, environ=None):
        env = os.environ if environ is None else environ
        profile = env.get("PAPER_SIMULATION_PROFILE", "SAFE").strip().upper()
        if profile not in {"SAFE", "BROAD"}:
            raise ValueError("PAPER_SIMULATION_PROFILE must be SAFE or BROAD.")
        broad = profile == "BROAD"
        symbols = tuple(
            item.strip().upper()
            for item in env.get("OPTIONBEACON_ALLOWED_TRADE_SYMBOLS", "").split(",")
            if item.strip()
        )
        return cls(
            simulation_profile=profile,
            mode=env.get("OPTIONBEACON_EXECUTION_MODE", "PAPER").strip().upper(),
            trading_enabled=_boolean(env.get("OPTIONBEACON_TRADING_ENABLED"), False),
            account_size=_float(env, "OPTIONBEACON_PAPER_ACCOUNT_SIZE", 5000),
            max_dollars_per_trade=_float(env, "OPTIONBEACON_MAX_DOLLARS_PER_TRADE", 250),
            max_total_deployed_capital=_float(
                env, "OPTIONBEACON_MAX_TOTAL_DEPLOYED_CAPITAL", 1250
            ),
            max_trades_per_day=_int(env, "OPTIONBEACON_MAX_TRADES_PER_DAY", 20 if broad else 3),
            max_open_positions=_int(env, "OPTIONBEACON_MAX_OPEN_POSITIONS", 5 if broad else 1),
            max_daily_loss_dollars=_float(env, "OPTIONBEACON_MAX_DAILY_LOSS_DOLLARS", 100),
            max_consecutive_losses=_int(
                env, "OPTIONBEACON_MAX_CONSECUTIVE_LOSSES", 0 if broad else 2
            ),
            loss_cooldown_minutes=_int(
                env, "OPTIONBEACON_LOSS_COOLDOWN_MINUTES", 0 if broad else 30
            ),
            min_beacon_score=_float(
                env, "OPTIONBEACON_MIN_BEACON_SCORE", 40 if broad else 92
            ),
            earliest_entry_time=_time(env.get("OPTIONBEACON_EARLIEST_ENTRY_TIME"), time(9, 45)),
            latest_entry_time=_time(env.get("OPTIONBEACON_LATEST_ENTRY_TIME"), time(15, 0)),
            allowed_symbols=symbols,
            profit_target_percent=_float(env, "OPTIONBEACON_PROFIT_TARGET_PERCENT", 50),
            stop_loss_percent=_float(env, "OPTIONBEACON_STOP_LOSS_PERCENT", -30),
            max_hold_minutes=_int(env, "OPTIONBEACON_MAX_HOLD_MINUTES", 120),
            trailing_profit_enabled=_boolean(env.get("OPTIONBEACON_TRAILING_PROFIT_ENABLED"), False),
            force_close_end_of_day=_boolean(env.get("OPTIONBEACON_FORCE_CLOSE_END_OF_DAY"), True),
            max_spread_percent=_float(env, "OPTIONBEACON_MAX_OPTION_SPREAD_PERCENT", 20),
            min_open_interest=_int(env, "OPTIONBEACON_MIN_OPTION_OPEN_INTEREST", 50),
            min_volume=_int(env, "OPTIONBEACON_MIN_OPTION_VOLUME", 0),
            entry_fill_toward_ask=_float(env, "OPTIONBEACON_ENTRY_FILL_TOWARD_ASK", 0.5),
        )

    @classmethod
    def from_resolved_state(cls, state, *, fallback=None):
        """Rebuild read-only display config from authoritative worker state."""
        base = fallback or cls()
        if not isinstance(state, dict) or not state:
            return base
        allowed = {field.name for field in fields(cls)}
        values = {key: value for key, value in state.items() if key in allowed}
        for key in ("earliest_entry_time", "latest_entry_time"):
            if key in values and isinstance(values[key], str):
                values[key] = time.fromisoformat(values[key])
        if "allowed_symbols" in values:
            values["allowed_symbols"] = tuple(values["allowed_symbols"] or ())
        return replace(base, **values)


def resolved_execution_config(config):
    """Return the complete non-secret effective PAPER configuration."""
    state = asdict(config)
    state["earliest_entry_time"] = config.earliest_entry_time.isoformat()
    state["latest_entry_time"] = config.latest_entry_time.isoformat()
    state["allowed_symbols"] = list(config.allowed_symbols)
    return state


def execution_config_log_record(config):
    """Return compact non-secret fields for structured worker logging."""
    return {
        "event": "paper_execution_config_resolved",
        "simulation_profile": config.simulation_profile,
        "min_score": config.min_beacon_score,
        "max_open_positions": config.max_open_positions,
        "max_trades_per_day": config.max_trades_per_day,
        "max_dollars_per_trade": config.max_dollars_per_trade,
        "max_total_deployed_capital": config.max_total_deployed_capital,
        "max_daily_loss": config.max_daily_loss_dollars,
        "max_consecutive_losses": config.max_consecutive_losses,
        "loss_cooldown_minutes": config.loss_cooldown_minutes,
        "entry_window": (
            f"{config.earliest_entry_time.isoformat()}-"
            f"{config.latest_entry_time.isoformat()} America/New_York"
        ),
    }


def _boolean(value, default):
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _float(env, key, default):
    return float(env.get(key, default))


def _int(env, key, default):
    return int(env.get(key, default))


def _time(value, default):
    return time.fromisoformat(str(value)) if value else default
