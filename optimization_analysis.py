"""Point-in-time baseline and failure analysis for the production strategy.

This module is deliberately disconnected from live scanning.  It replays the
existing scoring and fixed trade-management rules for research and reporting.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
import math
from statistics import mean, median
from typing import Iterable

import pandas as pd

from optionbeacon_strategy import (
    DEFAULT_CALL_SCORE_THRESHOLD,
    DEFAULT_PUT_SCORE_THRESHOLD,
    STOP_PERCENT,
    TARGET_PERCENT,
    score_candle,
)
from setup_stages import EXTENDED, classify_setup_stage
from trade_analytics import confidence_bucket
from trade_replay import add_replay_indicators


ANALYSIS_VERSION = "1.0"
DEFAULT_MAX_HOLD_CANDLES = 48
ANALYSIS_FORMATION_SCORE = 80
REGIME_LOOKBACK = 100

REGIME_BULLISH_TREND = "bullish trend"
REGIME_BEARISH_TREND = "bearish trend"
REGIME_RANGE_BOUND = "range-bound"
REGIME_HIGH_VOLATILITY = "high-volatility expansion"
REGIME_LOW_VOLATILITY = "low-volatility compression"
REGIME_GAP_CONTINUATION = "opening gap continuation"
REGIME_GAP_REVERSAL = "opening gap reversal"
REGIME_MEAN_REVERSION = "mean-reversion environment"
FAILURE_MODE_CATEGORIES = (
    "alert arrived late",
    "entered after extension",
    "false breakout",
    "low-volume breakout",
    "opposing higher-timeframe trend",
    "too close to support/resistance",
    "poor risk/reward",
    "market regime mismatch",
    "gap distortion",
    "VWAP conflict",
    "weak candle body",
    "momentum exhaustion",
    "low liquidity",
    "time-of-day weakness",
    "stop too tight",
    "target unrealistic",
    "signal reversed immediately",
    "signal never confirmed",
    "timeout/no follow-through",
)


def _finite(value, default=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _timestamp(value):
    return pd.Timestamp(value)


def _elapsed_minutes(start, end):
    return max(0.0, (_timestamp(end) - _timestamp(start)).total_seconds() / 60)


def _directional_return(entry, exit_price, direction):
    if not entry:
        return None
    if direction == "Bullish":
        return ((exit_price - entry) / entry) * 100
    return ((entry - exit_price) / entry) * 100


def _day_rows(frame, index):
    current_time = _timestamp(frame.index[index])
    return frame.iloc[: index + 1][
        pd.DatetimeIndex(frame.index[: index + 1]).date == current_time.date()
    ]


def _previous_session_close(frame, index):
    current_time = _timestamp(frame.index[index])
    prior = frame.iloc[:index][
        pd.DatetimeIndex(frame.index[:index]).date < current_time.date()
    ]
    return _finite(prior.iloc[-1]["Close"]) if not prior.empty else None


def classify_market_regime(frame: pd.DataFrame, index: int) -> dict:
    """Classify one bar using only observations available through ``index``."""
    if index < 0 or index >= len(frame):
        raise IndexError("regime index is outside the supplied frame")

    row = frame.iloc[index]
    history = frame.iloc[max(0, index - REGIME_LOOKBACK + 1) : index + 1]
    price = _finite(row.get("Close"), 0.0)
    atr = _finite(row.get("ATR"), 0.0)
    vwap = _finite(row.get("VWAP"), price)
    ema20 = _finite(row.get("EMA20"), price)
    ema50 = _finite(row.get("EMA50"), price)
    ema200 = _finite(row.get("EMA200"), price)

    atr_history = pd.to_numeric(history.get("ATR"), errors="coerce").dropna()
    atr_percentile = (
        float(
            (
                (atr_history < atr).sum()
                + 0.5 * (atr_history == atr).sum()
            )
            / len(atr_history)
            * 100
        )
        if atr and not atr_history.empty
        else None
    )
    slope_window = history.tail(min(6, len(history)))
    ema20_slope = (
        _finite(slope_window.iloc[-1].get("EMA20"), ema20)
        - _finite(slope_window.iloc[0].get("EMA20"), ema20)
    )
    slope_atr = ema20_slope / atr if atr else 0.0
    distance_vwap_atr = (price - vwap) / atr if atr else 0.0

    previous_close = _previous_session_close(frame, index)
    day_rows = _day_rows(frame, index)
    opening_price = _finite(day_rows.iloc[0].get("Open"), price)
    gap_atr = (
        (opening_price - previous_close) / atr
        if atr and previous_close is not None
        else 0.0
    )
    opening_direction = 1 if gap_atr > 0 else -1 if gap_atr < 0 else 0
    current_direction = 1 if price > opening_price else -1 if price < opening_price else 0

    bullish_alignment = price > ema20 > ema50 and ema50 >= ema200
    bearish_alignment = price < ema20 < ema50 and ema50 <= ema200
    high_volatility = atr_percentile is not None and atr_percentile >= 80
    low_volatility = atr_percentile is not None and atr_percentile <= 20

    if abs(gap_atr) >= 0.75 and current_direction:
        label = (
            REGIME_GAP_CONTINUATION
            if current_direction == opening_direction
            else REGIME_GAP_REVERSAL
        )
    elif high_volatility:
        label = REGIME_HIGH_VOLATILITY
    elif low_volatility:
        label = REGIME_LOW_VOLATILITY
    elif bullish_alignment and slope_atr > 0.1:
        label = REGIME_BULLISH_TREND
    elif bearish_alignment and slope_atr < -0.1:
        label = REGIME_BEARISH_TREND
    elif abs(distance_vwap_atr) >= 1.0 and abs(slope_atr) < 0.35:
        label = REGIME_MEAN_REVERSION
    else:
        label = REGIME_RANGE_BOUND

    return {
        "regime": label,
        "atr_percentile": atr_percentile,
        "ema20_slope_atr": slope_atr,
        "distance_from_vwap_atr": distance_vwap_atr,
        "opening_gap_atr": gap_atr,
        "bullish_alignment": bullish_alignment,
        "bearish_alignment": bearish_alignment,
    }


def _resample_higher_timeframe(frame, index, rule="30min"):
    """Return higher-timeframe bars built only from data visible at ``index``."""
    visible = frame.iloc[: index + 1][["Open", "High", "Low", "Close", "Volume"]]
    return (
        visible.resample(rule)
        .agg(
            {
                "Open": "first",
                "High": "max",
                "Low": "min",
                "Close": "last",
                "Volume": "sum",
            }
        )
        .dropna()
    )


def higher_timeframe_alignment(frame, index, direction):
    """Measure alignment from completed/visible 30-minute aggregates only."""
    higher = _resample_higher_timeframe(frame, index)
    if len(higher) < 8:
        return "unavailable"
    close = higher["Close"]
    ema_fast = close.ewm(span=4, adjust=False).mean()
    ema_slow = close.ewm(span=8, adjust=False).mean()
    slope = ema_fast.iloc[-1] - ema_fast.iloc[-3]
    if direction == "Bullish":
        aligned = close.iloc[-1] > ema_fast.iloc[-1] > ema_slow.iloc[-1] and slope > 0
        opposed = close.iloc[-1] < ema_slow.iloc[-1] and slope < 0
    else:
        aligned = close.iloc[-1] < ema_fast.iloc[-1] < ema_slow.iloc[-1] and slope < 0
        opposed = close.iloc[-1] > ema_slow.iloc[-1] and slope > 0
    return "aligned" if aligned else "non-aligned" if opposed else "partially aligned"


@dataclass(frozen=True)
class ReplayOutcome:
    exit_index: int
    exit_price: float
    exit_reason: str
    target_1_hit: bool
    target_2_hit: bool
    target_3_hit: bool
    mfe_percent: float
    mae_percent: float


def replay_fixed_plan(
    frame: pd.DataFrame,
    entry_index: int,
    *,
    entry: float,
    direction: str,
    max_hold_candles: int = DEFAULT_MAX_HOLD_CANDLES,
) -> ReplayOutcome:
    """Replay the current fixed stop/target plan with conservative bar ordering."""
    stop = entry * (1 - STOP_PERCENT if direction == "Bullish" else 1 + STOP_PERCENT)
    targets = [
        entry * (1 + TARGET_PERCENT * level)
        if direction == "Bullish"
        else entry * (1 - TARGET_PERCENT * level)
        for level in (1, 2, 3)
    ]
    final_index = min(entry_index + max_hold_candles, len(frame) - 1)
    exit_index = final_index
    exit_price = _finite(frame.iloc[final_index]["Close"], entry)
    exit_reason = "TIME_EXIT"
    target_hits = [False, False, False]
    favorable_extreme = entry
    adverse_extreme = entry

    for candle_index in range(entry_index + 1, final_index + 1):
        row = frame.iloc[candle_index]
        high = _finite(row["High"], entry)
        low = _finite(row["Low"], entry)
        if direction == "Bullish":
            favorable_extreme = max(favorable_extreme, high)
            adverse_extreme = min(adverse_extreme, low)
            stop_hit = low <= stop
            reached = [high >= target for target in targets]
        else:
            favorable_extreme = min(favorable_extreme, low)
            adverse_extreme = max(adverse_extreme, high)
            stop_hit = high >= stop
            reached = [low <= target for target in targets]

        if stop_hit:
            exit_index = candle_index
            exit_price = stop
            exit_reason = "STOP"
            break

        for target_index, hit in enumerate(reached):
            target_hits[target_index] = target_hits[target_index] or hit
        if target_hits[2]:
            exit_index = candle_index
            exit_price = targets[2]
            exit_reason = "TARGET_3"
            break
        if target_hits[1]:
            exit_index = candle_index
            exit_price = targets[1]
            exit_reason = "TARGET_2"
            break
        if target_hits[0]:
            exit_index = candle_index
            exit_price = targets[0]
            exit_reason = "TARGET_1"
            break

    mfe = _directional_return(entry, favorable_extreme, direction) or 0.0
    adverse_return = _directional_return(entry, adverse_extreme, direction) or 0.0
    return ReplayOutcome(
        exit_index=exit_index,
        exit_price=exit_price,
        exit_reason=exit_reason,
        target_1_hit=target_hits[0],
        target_2_hit=target_hits[1],
        target_3_hit=target_hits[2],
        mfe_percent=max(0.0, mfe),
        mae_percent=min(0.0, adverse_return),
    )


def _setup_failure_modes(frame, index, result, regime, outcome, formation_delay):
    """Classify weak-trade diagnostics; these labels never gate production."""
    row = frame.iloc[index]
    direction = "Bullish" if result["signal"] == "BULLISH SETUP" else "Bearish"
    atr = _finite(row.get("ATR"), 0.0)
    price = _finite(row.get("Close"), 0.0)
    vwap = _finite(row.get("VWAP"), price)
    relative_volume = _finite(result.get("relative_volume"), 0.0)
    body_atr = abs(_finite(row.get("Close"), 0) - _finite(row.get("Open"), 0)) / atr if atr else 0
    risk = price * STOP_PERCENT
    modes = []

    if formation_delay >= 15:
        modes.append("alert arrived late")
    if result.get("_analysis_setup_stage") == EXTENDED:
        modes.append("entered after extension")
    if relative_volume < 1.4:
        modes.append("low-volume breakout")
    if higher_timeframe_alignment(frame, index, direction) == "non-aligned":
        modes.append("opposing higher-timeframe trend")
    if atr and risk < atr * 0.35:
        modes.append("stop too tight")
    if regime["regime"] in {
        REGIME_RANGE_BOUND,
        REGIME_MEAN_REVERSION,
    }:
        modes.append("market regime mismatch")
    if abs(regime["opening_gap_atr"]) >= 0.75:
        modes.append("gap distortion")
    if (direction == "Bullish" and price < vwap) or (
        direction == "Bearish" and price > vwap
    ):
        modes.append("VWAP conflict")
    if body_atr < 0.35:
        modes.append("weak candle body")
    rsi = _finite(row.get("RSI"), 50)
    if (direction == "Bullish" and rsi > 70) or (
        direction == "Bearish" and rsi < 30
    ):
        modes.append("momentum exhaustion")
    if _timestamp(frame.index[index]).hour >= 14:
        modes.append("time-of-day weakness")
    if not any(
        phrase in result.get("reasons", [])
        for phrase in ("Resistance breakout", "Support breakdown")
    ):
        modes.append("signal never confirmed")
    elif outcome.exit_reason == "STOP":
        modes.append("false breakout")
    if outcome.exit_reason == "STOP" and outcome.exit_index - index <= 3:
        modes.append("signal reversed immediately")
    if outcome.exit_reason == "TIME_EXIT":
        modes.append("timeout/no follow-through")
    return sorted(set(modes))


def replay_current_strategy(
    symbol: str,
    raw_frame: pd.DataFrame,
    *,
    timeframe: str,
    period_label: str,
    max_hold_candles: int = DEFAULT_MAX_HOLD_CANDLES,
) -> pd.DataFrame:
    """Replay unchanged production scoring and fixed plan over supplied bars."""
    frame = add_replay_indicators(raw_frame.copy())
    intra_session_deltas = pd.Series(frame.index).diff().dropna()
    intra_session_minutes = [
        delta.total_seconds() / 60
        for delta in intra_session_deltas
        if 0 < delta.total_seconds() / 60 <= 120
    ]
    bar_minutes = median(intra_session_minutes) if intra_session_minutes else 0.0
    trades = []
    candidate_started = {"Bullish": None, "Bearish": None}
    index = 25

    while index < len(frame):
        result = score_candle(
            frame,
            index,
            symbol,
            call_score_threshold=DEFAULT_CALL_SCORE_THRESHOLD,
            put_score_threshold=DEFAULT_PUT_SCORE_THRESHOLD,
        )
        bias = result.get("bias")
        confidence = _finite(result.get("confidence"), 0.0)
        if bias in candidate_started:
            if confidence >= ANALYSIS_FORMATION_SCORE:
                candidate_started[bias] = candidate_started[bias] or index
            else:
                candidate_started[bias] = None

        signal = result.get("signal")
        if signal not in {"BULLISH SETUP", "BEARISH SETUP"}:
            index += 1
            continue

        direction = "Bullish" if signal == "BULLISH SETUP" else "Bearish"
        setup_stage = classify_setup_stage(result)["setup_stage"]
        result["_analysis_setup_stage"] = setup_stage
        entry = _finite(result.get("entry") or result.get("price"))
        outcome = replay_fixed_plan(
            frame,
            index,
            entry=entry,
            direction=direction,
            max_hold_candles=max_hold_candles,
        )
        start_index = candidate_started.get(direction)
        formation_delay = (
            (index - start_index) * bar_minutes
            if start_index is not None
            else 0.0
        )
        regime = classify_market_regime(frame, index)
        pnl = _directional_return(entry, outcome.exit_price, direction)
        failure_modes = (
            _setup_failure_modes(
                frame,
                index,
                result,
                regime,
                outcome,
                formation_delay,
            )
            if pnl is None or pnl <= 0 or outcome.exit_reason == "TIME_EXIT"
            else []
        )
        hold_minutes = (outcome.exit_index - index) * bar_minutes
        trades.append(
            {
                "symbol": symbol,
                "period": period_label,
                "timeframe": timeframe,
                "signal_time": _timestamp(frame.index[index]).isoformat(),
                "exit_time": _timestamp(frame.index[outcome.exit_index]).isoformat(),
                "direction": direction,
                "setup": signal,
                "confidence": confidence,
                "confidence_bucket": confidence_bucket(confidence),
                "entry": entry,
                "exit": outcome.exit_price,
                "realized_return": pnl,
                "exit_reason": outcome.exit_reason,
                "hold_minutes": hold_minutes,
                "mfe": outcome.mfe_percent,
                "mae": outcome.mae_percent,
                "target_1_hit": outcome.target_1_hit,
                "target_2_hit": outcome.target_2_hit,
                "target_3_hit": outcome.target_3_hit,
                "stop_first": outcome.exit_reason == "STOP",
                "late": setup_stage == EXTENDED,
                "invalidated_quickly": outcome.exit_reason == "STOP"
                and outcome.exit_index - index <= 3,
                "formation_delay_minutes": formation_delay,
                "hour": _timestamp(frame.index[index]).strftime("%H:00"),
                "regime": regime["regime"],
                "higher_timeframe_alignment": higher_timeframe_alignment(
                    frame, index, direction
                ),
                "failure_modes": failure_modes,
            }
        )
        candidate_started[direction] = None
        index += max_hold_candles

    return pd.DataFrame(trades)


def _safe_average(values):
    usable = [_finite(value) for value in values]
    usable = [value for value in usable if value is not None]
    return mean(usable) if usable else None


def _maximum_drawdown(returns):
    cumulative = 0.0
    peak = 0.0
    drawdown = 0.0
    for value in returns:
        cumulative += value
        peak = max(peak, cumulative)
        drawdown = min(drawdown, cumulative - peak)
    return drawdown


def _longest_losing_streak(returns):
    longest = current = 0
    for value in returns:
        if value < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def performance_metrics(trades: pd.DataFrame, *, trading_days=None) -> dict:
    """Return comprehensive, JSON-safe metrics for one replay slice."""
    if trades.empty:
        return {
            key: 0 if key in {
                "total_alerts",
                "wins",
                "losses",
                "breakeven",
                "longest_losing_streak",
            } else None
            for key in (
                "total_alerts",
                "alerts_per_day",
                "wins",
                "losses",
                "breakeven",
                "win_rate",
                "loss_rate",
                "breakeven_rate",
                "expectancy",
                "profit_factor",
                "average_winner",
                "average_loser",
                "median_winner",
                "median_loser",
                "maximum_drawdown",
                "longest_losing_streak",
                "average_hold_minutes",
                "average_mfe",
                "average_mae",
                "target_1_rate",
                "target_2_rate",
                "stop_first_rate",
                "time_exit_rate",
                "late_rate",
                "quick_invalidation_rate",
                "average_formation_delay_minutes",
            )
        }

    returns = [
        value
        for value in (_finite(item) for item in trades["realized_return"])
        if value is not None
    ]
    winners = [value for value in returns if value > 0]
    losers = [value for value in returns if value < 0]
    breakeven = [value for value in returns if value == 0]
    decided = len(winners) + len(losers)
    count = len(trades)
    days = trading_days or len(
        {_timestamp(value).date() for value in trades["signal_time"]}
    )
    gross_loss = abs(sum(losers))
    profit_factor = (
        sum(winners) / gross_loss
        if gross_loss
        else None
    )
    return {
        "total_alerts": count,
        "alerts_per_day": count / days if days else None,
        "wins": len(winners),
        "losses": len(losers),
        "breakeven": len(breakeven),
        "win_rate": len(winners) / decided * 100 if decided else None,
        "loss_rate": len(losers) / decided * 100 if decided else None,
        "breakeven_rate": len(breakeven) / count * 100 if count else None,
        "expectancy": _safe_average(returns),
        "profit_factor": profit_factor,
        "average_winner": _safe_average(winners),
        "average_loser": _safe_average(losers),
        "median_winner": median(winners) if winners else None,
        "median_loser": median(losers) if losers else None,
        "maximum_drawdown": _maximum_drawdown(returns),
        "longest_losing_streak": _longest_losing_streak(returns),
        "average_hold_minutes": _safe_average(trades["hold_minutes"]),
        "average_mfe": _safe_average(trades["mfe"]),
        "average_mae": _safe_average(trades["mae"]),
        "target_1_rate": float(trades["target_1_hit"].mean() * 100),
        "target_2_rate": float(trades["target_2_hit"].mean() * 100),
        "stop_first_rate": float(trades["stop_first"].mean() * 100),
        "time_exit_rate": float(
            (trades["exit_reason"] == "TIME_EXIT").mean() * 100
        ),
        "late_rate": float(trades["late"].mean() * 100),
        "quick_invalidation_rate": float(
            trades["invalidated_quickly"].mean() * 100
        ),
        "average_formation_delay_minutes": _safe_average(
            trades["formation_delay_minutes"]
        ),
    }


def grouped_performance(
    trades: pd.DataFrame,
    field: str,
    *,
    trading_days_by_group=None,
) -> list[dict]:
    if trades.empty or field not in trades:
        return []
    results = []
    for group, records in trades.groupby(field, dropna=False, sort=True):
        results.append(
            {
                "group": str(group),
                **performance_metrics(
                    records,
                    trading_days=(
                        trading_days_by_group.get(str(group))
                        if trading_days_by_group
                        else None
                    ),
                ),
            }
        )
    return results


def failure_mode_audit(trades: pd.DataFrame) -> list[dict]:
    """Summarize diagnostic labels assigned only to losing/weak signals."""
    expanded = []
    for row in trades.to_dict("records") if not trades.empty else []:
        for mode in row.get("failure_modes") or []:
            expanded.append({**row, "failure_mode": mode})
    failures = pd.DataFrame(expanded) if expanded else pd.DataFrame()
    results = []
    for mode in FAILURE_MODE_CATEGORIES:
        records = (
            failures[failures["failure_mode"] == mode]
            if not failures.empty
            else pd.DataFrame()
        )
        results.append(
            {
                "failure_mode": mode,
                "frequency": len(records),
                "average_return": (
                    _safe_average(records["realized_return"])
                    if not records.empty
                    else None
                ),
                "symbols": dict(Counter(records["symbol"])) if not records.empty else {},
                "hours": dict(Counter(records["hour"])) if not records.empty else {},
                "setups": dict(Counter(records["setup"])) if not records.empty else {},
            }
        )
    return sorted(results, key=lambda item: (-item["frequency"], item["failure_mode"]))


def baseline_report(trades: pd.DataFrame, data_manifest: list[dict]) -> dict:
    """Build the full analysis report from deterministic replay rows."""
    primary = (
        trades[
            (trades["period"] == "60-trading-days")
            & (trades["timeframe"] == "5m")
        ]
        if not trades.empty
        else trades
    )
    primary_days = max(
        (
            int(item.get("trading_days") or 0)
            for item in data_manifest
            if item.get("period") == "60-trading-days"
            and item.get("timeframe") == "5m"
        ),
        default=0,
    )
    period_days = {
        period: max(
            (
                int(item.get("trading_days") or 0)
                for item in data_manifest
                if item.get("period") == period
            ),
            default=0,
        )
        for period in (
            set(trades["period"]) if not trades.empty else set()
        )
    }
    primary_day_map = {
        str(group): primary_days
        for field in (
            "symbol",
            "direction",
            "setup",
            "hour",
            "confidence_bucket",
            "regime",
            "higher_timeframe_alignment",
        )
        for group in (set(primary[field]) if not primary.empty else set())
    }
    return {
        "analysis_version": ANALYSIS_VERSION,
        "data_manifest": data_manifest,
        "primary_scope": "60-trading-days / 5m production timeframe",
        "overall": performance_metrics(primary, trading_days=primary_days),
        "all_windows": performance_metrics(trades),
        "by_symbol": grouped_performance(
            primary, "symbol", trading_days_by_group=primary_day_map
        ),
        "by_direction": grouped_performance(
            primary, "direction", trading_days_by_group=primary_day_map
        ),
        "by_setup": grouped_performance(
            primary, "setup", trading_days_by_group=primary_day_map
        ),
        "by_hour": grouped_performance(
            primary, "hour", trading_days_by_group=primary_day_map
        ),
        "by_confidence_bucket": grouped_performance(
            primary,
            "confidence_bucket",
            trading_days_by_group=primary_day_map,
        ),
        "by_regime": grouped_performance(
            primary, "regime", trading_days_by_group=primary_day_map
        ),
        "by_period": grouped_performance(
            trades, "period", trading_days_by_group=period_days
        ),
        "by_timeframe": grouped_performance(trades, "timeframe"),
        "by_higher_timeframe_alignment": grouped_performance(
            primary,
            "higher_timeframe_alignment",
            trading_days_by_group=primary_day_map,
        ),
        "failure_modes": failure_mode_audit(primary),
        "trade_count": len(trades),
        "primary_trade_count": len(primary),
    }


def regime_methodology() -> dict:
    return {
        "point_in_time": True,
        "lookback_bars": REGIME_LOOKBACK,
        "inputs": [
            "EMA20/EMA50/EMA200 alignment",
            "recent EMA20 slope normalized by ATR",
            "ATR percentile using trailing observations only",
            "price distance from VWAP normalized by ATR",
            "opening gap normalized by current ATR",
            "price direction from the session open",
        ],
        "labels": [
            REGIME_BULLISH_TREND,
            REGIME_BEARISH_TREND,
            REGIME_RANGE_BOUND,
            REGIME_HIGH_VOLATILITY,
            REGIME_LOW_VOLATILITY,
            REGIME_GAP_CONTINUATION,
            REGIME_GAP_REVERSAL,
            REGIME_MEAN_REVERSION,
        ],
        "production_effect": "analysis only; no signal is rejected or modified",
    }
