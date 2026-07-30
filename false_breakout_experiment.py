"""Experiment 001: point-in-time false-breakout protection research.

Nothing in this module is imported by production scoring.  The optional live
shadow recorder consumes an already-computed production result and returns it
unchanged.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime
import hashlib
import json
import logging
import math
from pathlib import Path
from statistics import mean, median
from typing import Iterable

import pandas as pd

from optimization_analysis import (
    classify_market_regime,
    higher_timeframe_alignment,
    performance_metrics,
    replay_fixed_plan,
)
from optionbeacon_strategy import (
    DEFAULT_CALL_SCORE_THRESHOLD,
    DEFAULT_PUT_SCORE_THRESHOLD,
    score_candle,
)
from trade_replay import add_replay_indicators


LOGGER = logging.getLogger(__name__)
EXPERIMENT_ID = "EXP-001-FALSE-BREAKOUT"
DEFAULT_SHADOW_FILE = "experiment_001_shadow.jsonl"
MAX_CONFIRMATION_BARS = 6

DETECTED = "DETECTED"
WATCHING = "WATCHING"
CONFIRMED = "CONFIRMED"
ACTIVE = "ACTIVE"
LATE = "LATE"
REJECTED = "REJECTED"
INVALIDATED = "INVALIDATED"


@dataclass(frozen=True)
class CandidateModel:
    name: str
    confirmation: str = "any_close"
    close_buffer_atr: float = 0.0
    volume_ratio: float | None = None
    max_extension_atr: float | None = None
    max_target_consumption: float | None = None
    min_risk_reward: float | None = None
    max_candles_after_confirmation: int | None = None
    max_vwap_distance_atr: float | None = None
    require_vwap_alignment: bool = False
    gap_wait_minutes: int = 0
    gap_aware: bool = False
    gap_require_opening_range: bool = False
    gap_require_alignment: bool = False
    gap_require_vwap_return: bool = False


MODELS = {
    "MODEL_A_BASELINE": CandidateModel(
        "MODEL_A_BASELINE",
        confirmation="baseline",
    ),
    "MODEL_B_CLOSE_ONLY": CandidateModel("MODEL_B_CLOSE_ONLY"),
    "MODEL_C_CLOSE_VOLUME": CandidateModel(
        "MODEL_C_CLOSE_VOLUME",
        volume_ratio=1.20,
    ),
    "MODEL_D_CLOSE_EXTENSION": CandidateModel(
        "MODEL_D_CLOSE_EXTENSION",
        max_extension_atr=0.35,
        max_target_consumption=0.50,
        min_risk_reward=1.50,
        max_candles_after_confirmation=2,
    ),
    "MODEL_E_CLOSE_VOLUME_EXTENSION": CandidateModel(
        "MODEL_E_CLOSE_VOLUME_EXTENSION",
        volume_ratio=1.20,
        max_extension_atr=0.35,
        max_target_consumption=0.50,
        min_risk_reward=1.50,
        max_candles_after_confirmation=2,
    ),
    "MODEL_F_GAP_AWARE": CandidateModel(
        "MODEL_F_GAP_AWARE",
        confirmation="one_candle_hold",
        gap_wait_minutes=15,
        gap_aware=True,
        gap_require_opening_range=True,
        gap_require_alignment=True,
    ),
    "MODEL_G_RETEST_HOLD": CandidateModel(
        "MODEL_G_RETEST_HOLD",
        confirmation="retest_hold",
    ),
    "MODEL_H_HYBRID": CandidateModel(
        "MODEL_H_HYBRID",
        close_buffer_atr=0.05,
        volume_ratio=1.10,
        max_extension_atr=0.35,
        max_target_consumption=0.50,
        min_risk_reward=1.50,
        max_candles_after_confirmation=2,
        max_vwap_distance_atr=0.75,
        require_vwap_alignment=True,
        gap_wait_minutes=15,
        gap_aware=True,
        gap_require_opening_range=True,
        gap_require_alignment=True,
    ),
}


def _number(value, default=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _directional_reached(value, level, direction):
    return value >= level if direction == "Bullish" else value <= level


def _directional_failed(value, level, direction):
    return value <= level if direction == "Bullish" else value >= level


def volume_confirmation_features(frame, index):
    """Calculate volume features from the current and prior bars only."""
    row = frame.iloc[index]
    current = _number(row.get("Volume"), 0.0)
    trailing = _number(row.get("AVG_VOLUME_20"), 0.0)
    prior_five = pd.to_numeric(
        frame.iloc[max(0, index - 5) : index]["Volume"],
        errors="coerce",
    ).dropna()
    current_time = pd.Timestamp(frame.index[index])
    prior_same_time = frame.iloc[:index][
        [
            pd.Timestamp(value).time() == current_time.time()
            for value in frame.index[:index]
        ]
    ]
    same_time_volume = (
        pd.to_numeric(prior_same_time["Volume"], errors="coerce").dropna()
        if "Volume" in prior_same_time
        else pd.Series(dtype=float)
    )
    return {
        "trailing_20_ratio": current / trailing if trailing else None,
        "prior_five_ratio": current / prior_five.mean()
        if not prior_five.empty and prior_five.mean()
        else None,
        "same_time_ratio": current / same_time_volume.mean()
        if not same_time_volume.empty and same_time_volume.mean()
        else None,
    }


def atr_extension(price, trigger, atr, direction):
    if not atr:
        return None
    distance = price - trigger if direction == "Bullish" else trigger - price
    return distance / atr


def target_one_consumption(price, trigger, target, direction):
    total = target - trigger if direction == "Bullish" else trigger - target
    consumed = price - trigger if direction == "Bullish" else trigger - price
    return consumed / total if total > 0 else None


def risk_reward_at_entry(price, stop, target, direction):
    risk = price - stop if direction == "Bullish" else stop - price
    reward = target - price if direction == "Bullish" else price - target
    return reward / risk if risk > 0 else None


def classify_gap(gap_atr):
    magnitude = abs(_number(gap_atr, 0.0))
    if magnitude < 0.25:
        return "<0.25 ATR"
    if magnitude < 0.50:
        return "0.25-0.50 ATR"
    if magnitude <= 1.00:
        return "0.50-1.00 ATR"
    return ">1.00 ATR"


def entry_window(timestamp):
    value = pd.Timestamp(timestamp)
    minutes = value.hour * 60 + value.minute
    for label, start, end in (
        ("09:30-10:00", 570, 600),
        ("10:00-11:00", 600, 660),
        ("11:00-13:00", 660, 780),
        ("13:00-14:00", 780, 840),
        ("14:00-15:00", 840, 900),
        ("15:00-16:00", 900, 960),
    ):
        if start <= minutes < end:
            return label
    return "outside-window"


def close_confirmed(close, trigger, atr, direction, buffer_atr=0.0):
    offset = (_number(atr, 0.0) or 0.0) * buffer_atr
    level = trigger + offset if direction == "Bullish" else trigger - offset
    return _directional_reached(close, level, direction)


def _confirmation_index(frame, base_index, setup, model):
    if model.confirmation == "baseline":
        return base_index, "existing production decision"
    direction = setup["direction"]
    trigger = setup["trigger"]
    atr = setup["atr"]
    breakout_index = None
    retest_index = None
    last_index = min(base_index + MAX_CONFIRMATION_BARS, len(frame) - 1)

    for index in range(base_index, last_index + 1):
        close = _number(frame.iloc[index]["Close"], 0.0)
        if _directional_failed(close, setup["stop"], direction):
            return None, "setup invalidated before confirmation"
        confirmed = close_confirmed(
            close,
            trigger,
            atr,
            direction,
            model.close_buffer_atr,
        )
        if model.confirmation == "any_close" and confirmed:
            return index, "close confirmed beyond trigger"
        if model.confirmation in {"one_candle_hold", "two_closes"}:
            if (
                index > base_index
                and confirmed
                and close_confirmed(
                    _number(frame.iloc[index - 1]["Close"], 0.0),
                    trigger,
                    atr,
                    direction,
                    model.close_buffer_atr,
                )
            ):
                return index, "two consecutive closes held beyond trigger"
        if model.confirmation == "retest_hold":
            if breakout_index is None and confirmed:
                breakout_index = index
                continue
            if breakout_index is not None and retest_index is None and index > breakout_index:
                row = frame.iloc[index]
                touched = (
                    _number(row["Low"], trigger) <= trigger + atr * 0.10
                    if direction == "Bullish"
                    else _number(row["High"], trigger) >= trigger - atr * 0.10
                )
                materially_failed = (
                    _number(row["Close"], trigger) < trigger - atr * 0.05
                    if direction == "Bullish"
                    else _number(row["Close"], trigger) > trigger + atr * 0.05
                )
                if touched and not materially_failed:
                    retest_index = index
                    continue
            if retest_index is not None and index > retest_index and confirmed:
                return index, "breakout retested, held, and resumed"
    return None, "confirmation not completed within allowed bars"


def _session_minutes(frame, index):
    timestamp = pd.Timestamp(frame.index[index])
    return max(0, timestamp.hour * 60 + timestamp.minute - 570)


def _opening_range(frame, index, minutes=30):
    timestamp = pd.Timestamp(frame.index[index])
    visible = frame.iloc[: index + 1]
    same_day = visible[
        [pd.Timestamp(value).date() == timestamp.date() for value in visible.index]
    ]
    opening = same_day[
        [
            pd.Timestamp(value).hour * 60 + pd.Timestamp(value).minute
            < 570 + minutes
            for value in same_day.index
        ]
    ]
    if opening.empty:
        return None, None
    return _number(opening["High"].max()), _number(opening["Low"].min())


def _candidate_decision(frame, base_index, setup, model):
    confirmation_index, confirmation_reason = _confirmation_index(
        frame, base_index, setup, model
    )
    if confirmation_index is None:
        status = (
            INVALIDATED
            if "invalidated" in confirmation_reason
            else REJECTED
        )
        return {
            "status": status,
            "confirmation_index": None,
            "entry_index": None,
            "reason": confirmation_reason,
        }

    row = frame.iloc[confirmation_index]
    price = _number(row["Close"], 0.0)
    direction = setup["direction"]
    volume = volume_confirmation_features(frame, confirmation_index)
    extension = atr_extension(
        price, setup["trigger"], setup["atr"], direction
    )
    consumption = target_one_consumption(
        price, setup["trigger"], setup["target_1"], direction
    )
    risk_reward = risk_reward_at_entry(
        price, setup["stop"], setup["target_1"], direction
    )
    vwap = _number(row.get("VWAP"), price)
    vwap_distance = (
        abs(price - vwap) / setup["atr"] if setup["atr"] else None
    )
    vwap_aligned = (
        price >= vwap if direction == "Bullish" else price <= vwap
    )
    regime = classify_market_regime(frame, confirmation_index)
    gap_bucket = classify_gap(regime["opening_gap_atr"])
    reasons = []

    if (
        model.volume_ratio is not None
        and (
            volume["trailing_20_ratio"] is None
            or volume["trailing_20_ratio"] < model.volume_ratio
        )
    ):
        reasons.append("volume confirmation failed")
    if model.gap_aware and abs(regime["opening_gap_atr"]) >= 0.50:
        if _session_minutes(frame, confirmation_index) < model.gap_wait_minutes:
            reasons.append("gap-day waiting period incomplete")
        gap_direction = (
            "Bullish" if regime["opening_gap_atr"] > 0 else "Bearish"
        )
        if (
            model.gap_require_alignment
            and direction != gap_direction
            and regime["regime"] != "opening gap reversal"
        ):
            reasons.append("opposes large gap without reversal confirmation")
        opening_high, opening_low = _opening_range(frame, confirmation_index)
        if model.gap_require_opening_range:
            if _session_minutes(frame, confirmation_index) < 30:
                reasons.append("opening range not complete")
            elif (
                opening_high is None
                or (direction == "Bullish" and price < opening_high)
                or (direction == "Bearish" and price > opening_low)
            ):
                reasons.append("opening range break-and-hold absent")
        if model.gap_require_vwap_return:
            visible = frame.iloc[base_index : confirmation_index + 1]
            returned_to_vwap = any(
                _number(candidate["Low"], price)
                <= _number(candidate["VWAP"], price)
                <= _number(candidate["High"], price)
                for _, candidate in visible.iterrows()
            )
            if not returned_to_vwap:
                reasons.append("price did not return to VWAP before entry")
    if model.require_vwap_alignment and not vwap_aligned:
        reasons.append("directional VWAP alignment failed")
    if (
        model.max_vwap_distance_atr is not None
        and vwap_distance is not None
        and vwap_distance > model.max_vwap_distance_atr
    ):
        reasons.append("VWAP distance exceeded")
    if reasons:
        return {
            "status": REJECTED,
            "confirmation_index": confirmation_index,
            "entry_index": None,
            "reason": "; ".join(reasons),
            "gap_classification": gap_bucket,
        }

    late_reasons = []
    if (
        model.max_extension_atr is not None
        and extension is not None
        and extension > model.max_extension_atr
    ):
        late_reasons.append("ATR extension exceeded")
    if (
        model.max_target_consumption is not None
        and consumption is not None
        and consumption > model.max_target_consumption
    ):
        late_reasons.append("more than allowed Target 1 distance consumed")
    if (
        model.min_risk_reward is not None
        and (risk_reward is None or risk_reward < model.min_risk_reward)
    ):
        late_reasons.append("risk/reward below minimum")
    if (
        model.max_candles_after_confirmation is not None
        and confirmation_index - base_index > model.max_candles_after_confirmation
    ):
        late_reasons.append("confirmation arrived too many candles later")
    if late_reasons:
        return {
            "status": LATE,
            "confirmation_index": confirmation_index,
            "entry_index": None,
            "reason": "; ".join(late_reasons),
            "gap_classification": gap_bucket,
            "extension_atr": extension,
            "target_1_consumption": consumption,
            "risk_reward": risk_reward,
        }

    return {
        "status": ACTIVE,
        "confirmation_index": confirmation_index,
        "entry_index": confirmation_index,
        "reason": confirmation_reason,
        "gap_classification": gap_bucket,
        "extension_atr": extension,
        "target_1_consumption": consumption,
        "risk_reward": risk_reward,
        "volume_ratio": volume["trailing_20_ratio"],
        "same_time_volume_ratio": volume["same_time_ratio"],
        "prior_five_volume_ratio": volume["prior_five_ratio"],
        "vwap_distance_atr": vwap_distance,
        "vwap_aligned": vwap_aligned,
        "regime": regime["regime"],
    }


def _fixed_plan_outcome(frame, entry_index, setup):
    """Replay original planned levels from the delayed theoretical entry."""
    direction = setup["direction"]
    stop = setup["stop"]
    targets = [setup["target_1"], setup["target_2"], setup["target_3"]]
    entry_price = _number(frame.iloc[entry_index]["Close"], setup["entry"])
    final_index = min(entry_index + 48, len(frame) - 1)
    favorable = adverse = entry_price
    hits = [False, False, False]
    exit_index = final_index
    exit_price = _number(frame.iloc[final_index]["Close"], entry_price)
    reason = "TIME_EXIT"
    for index in range(entry_index + 1, final_index + 1):
        high = _number(frame.iloc[index]["High"], entry_price)
        low = _number(frame.iloc[index]["Low"], entry_price)
        favorable = max(favorable, high) if direction == "Bullish" else min(favorable, low)
        adverse = min(adverse, low) if direction == "Bullish" else max(adverse, high)
        if _directional_failed(
            low if direction == "Bullish" else high,
            stop,
            direction,
        ):
            exit_index, exit_price, reason = index, stop, "STOP"
            break
        for target_index, target in enumerate(targets):
            probe = high if direction == "Bullish" else low
            hits[target_index] = hits[target_index] or _directional_reached(
                probe, target, direction
            )
        if hits[2]:
            exit_index, exit_price, reason = index, targets[2], "TARGET_3"
            break
        if hits[1]:
            exit_index, exit_price, reason = index, targets[1], "TARGET_2"
            break
        if hits[0]:
            exit_index, exit_price, reason = index, targets[0], "TARGET_1"
            break

    def pnl(price):
        if direction == "Bullish":
            return (price - entry_price) / entry_price * 100
        return (entry_price - price) / entry_price * 100

    return {
        "realized_return": pnl(exit_price),
        "exit_reason": reason,
        "target_1_hit": hits[0],
        "target_2_hit": hits[1],
        "target_3_hit": hits[2],
        "stop_first": reason == "STOP",
        "invalidated_quickly": reason == "STOP" and exit_index - entry_index <= 3,
        "mfe": max(0.0, pnl(favorable)),
        "mae": min(0.0, pnl(adverse)),
        "hold_minutes": (exit_index - entry_index) * setup["bar_minutes"],
    }


def collect_base_setups(symbol, raw_frame):
    """Collect unchanged production setups and their original outcomes."""
    frame = add_replay_indicators(raw_frame.copy())
    deltas = pd.Series(frame.index).diff().dropna()
    minutes = [
        delta.total_seconds() / 60
        for delta in deltas
        if 0 < delta.total_seconds() / 60 <= 120
    ]
    bar_minutes = median(minutes) if minutes else 5.0
    setups = []
    index = 25
    while index < len(frame):
        result = score_candle(
            frame,
            index,
            symbol,
            call_score_threshold=DEFAULT_CALL_SCORE_THRESHOLD,
            put_score_threshold=DEFAULT_PUT_SCORE_THRESHOLD,
        )
        if result.get("signal") not in {"BULLISH SETUP", "BEARISH SETUP"}:
            index += 1
            continue
        direction = (
            "Bullish" if result["signal"] == "BULLISH SETUP" else "Bearish"
        )
        entry = _number(result["entry"])
        target_1 = _number(result["target"])
        setup = {
            "symbol": symbol,
            "base_index": index,
            "signal_time": pd.Timestamp(frame.index[index]).isoformat(),
            "direction": direction,
            "setup": result["signal"],
            "confidence": _number(result["confidence"], 0.0),
            "entry": entry,
            "trigger": _number(
                result["resistance"] if direction == "Bullish" else result["support"]
            ),
            "stop": _number(result["stop"]),
            "target_1": target_1,
            "target_2": entry + (target_1 - entry) * 2,
            "target_3": entry + (target_1 - entry) * 3,
            "atr": _number(result["atr"], 0.0),
            "bar_minutes": bar_minutes,
        }
        base_outcome = _fixed_plan_outcome(frame, index, setup)
        regime = classify_market_regime(frame, index)
        setup.update(
            {
                "base_outcome": base_outcome,
                "regime": regime["regime"],
                "gap_classification": classify_gap(regime["opening_gap_atr"]),
                "gap_atr": regime["opening_gap_atr"],
                "higher_timeframe_alignment": {
                    "aligned": "aligned",
                    "partially aligned": "neutral",
                    "non-aligned": "opposed",
                    "unavailable": "neutral",
                }[higher_timeframe_alignment(frame, index, direction)],
                "hour": entry_window(frame.index[index]),
            }
        )
        setups.append(setup)
        index += 48
    return frame, setups


def evaluate_model(frame, setups, model):
    rows = []
    for setup in setups:
        decision = _candidate_decision(
            frame, setup["base_index"], setup, model
        )
        row = {
            "model": model.name,
            "symbol": setup["symbol"],
            "signal_time": setup["signal_time"],
            "direction": setup["direction"],
            "setup": setup["setup"],
            "regime": setup["regime"],
            "gap_classification": setup["gap_classification"],
            "hour": setup["hour"],
            "higher_timeframe_alignment": setup[
                "higher_timeframe_alignment"
            ],
            "status": decision["status"],
            "reason": decision["reason"],
            "confirmed_at": (
                pd.Timestamp(frame.index[decision["confirmation_index"]]).isoformat()
                if decision.get("confirmation_index") is not None
                else None
            ),
            "entry_time": (
                pd.Timestamp(frame.index[decision["entry_index"]]).isoformat()
                if decision.get("entry_index") is not None
                else None
            ),
            "entry_delay_minutes": (
                (decision["entry_index"] - setup["base_index"])
                * setup["bar_minutes"]
                if decision.get("entry_index") is not None
                else None
            ),
            "risk_reward": decision.get("risk_reward"),
            "base_return": setup["base_outcome"]["realized_return"],
            "base_exit_reason": setup["base_outcome"]["exit_reason"],
        }
        if decision["status"] == ACTIVE:
            row.update(_fixed_plan_outcome(frame, decision["entry_index"], setup))
            row.update(
                {
                    "late": False,
                    "formation_delay_minutes": row["entry_delay_minutes"],
                }
            )
        rows.append(row)
    return pd.DataFrame(rows)


def _average(values):
    usable = [_number(value) for value in values]
    usable = [value for value in usable if value is not None]
    return mean(usable) if usable else None


def candidate_metrics(rows):
    eligible = len(rows)
    active = rows[rows["status"] == ACTIVE] if not rows.empty else rows
    performance = performance_metrics(active)
    delays = (
        pd.to_numeric(active["entry_delay_minutes"], errors="coerce").dropna().tolist()
        if not active.empty
        else []
    )
    return {
        "total_eligible_setups": eligible,
        "confirmed_setups": int(rows["confirmed_at"].notna().sum()) if eligible else 0,
        "rejected_setups": int((rows["status"] == REJECTED).sum()) if eligible else 0,
        "invalidated_setups": int((rows["status"] == INVALIDATED).sum()) if eligible else 0,
        "late_setups": int((rows["status"] == LATE).sum()) if eligible else 0,
        "active_entries": len(active),
        "alert_reduction_percent": (
            (eligible - len(active)) / eligible * 100 if eligible else None
        ),
        **performance,
        "average_entry_delay_minutes": _average(delays),
        "median_entry_delay_minutes": median(delays) if delays else None,
        "average_risk_reward_at_entry": (
            _average(active["risk_reward"]) if not active.empty else None
        ),
    }


def opportunity_cost(rows):
    counts = {
        "avoided loser": 0,
        "avoided winner": 0,
        "delayed loser": 0,
        "delayed winner": 0,
        "converted loser to no-trade": 0,
        "converted winner to late/no-trade": 0,
    }
    for row in rows.to_dict("records"):
        base_winner = (_number(row.get("base_return"), 0.0) or 0.0) > 0
        if row["status"] != ACTIVE:
            if base_winner:
                counts["avoided winner"] += 1
                counts["converted winner to late/no-trade"] += 1
            else:
                counts["avoided loser"] += 1
                counts["converted loser to no-trade"] += 1
        elif (_number(row.get("entry_delay_minutes"), 0.0) or 0.0) > 0:
            key = "delayed winner" if (_number(row.get("realized_return"), 0.0) or 0.0) > 0 else "delayed loser"
            counts[key] += 1
    return counts


def _group_metrics(rows, field):
    results = []
    if rows.empty:
        return results
    for name, group in rows.groupby(field, sort=True):
        results.append({"group": str(name), **candidate_metrics(group)})
    return results


def model_report(rows):
    return {
        "metrics": candidate_metrics(rows),
        "opportunity_cost": opportunity_cost(rows),
        "by_symbol": _group_metrics(rows, "symbol"),
        "by_direction": _group_metrics(rows, "direction"),
        "by_regime": _group_metrics(rows, "regime"),
        "by_gap_classification": _group_metrics(rows, "gap_classification"),
        "by_hour": _group_metrics(rows, "hour"),
        "by_higher_timeframe_alignment": _group_metrics(
            rows, "higher_timeframe_alignment"
        ),
    }


def parameter_sweeps(frames_and_setups):
    """Run univariate exploratory ranges without selecting on the full sample."""
    variants = []
    definitions = []
    for buffer_value in (0.0, 0.05, 0.10):
        definitions.append(
            replace(
                MODELS["MODEL_B_CLOSE_ONLY"],
                name=f"close_buffer_{buffer_value:.2f}",
                close_buffer_atr=buffer_value,
            )
        )
    definitions.append(
        replace(
            MODELS["MODEL_B_CLOSE_ONLY"],
            name="close_two_consecutive",
            confirmation="two_closes",
        )
    )
    for ratio in (1.0, 1.1, 1.2, 1.3, 1.4):
        definitions.append(
            replace(
                MODELS["MODEL_C_CLOSE_VOLUME"],
                name=f"volume_{ratio:.1f}",
                volume_ratio=ratio,
            )
        )
    for maximum in (0.15, 0.25, 0.35, 0.50):
        definitions.append(
            replace(
                MODELS["MODEL_D_CLOSE_EXTENSION"],
                name=f"extension_{maximum:.2f}",
                max_extension_atr=maximum,
            )
        )
    for maximum in (0.25, 0.50, 0.75, 1.00, None):
        definitions.append(
            replace(
                MODELS["MODEL_B_CLOSE_ONLY"],
                name=f"vwap_distance_{maximum if maximum is not None else 'none'}",
                max_vwap_distance_atr=maximum,
            )
        )
    for minimum in (1.25, 1.50):
        definitions.append(
            replace(
                MODELS["MODEL_D_CLOSE_EXTENSION"],
                name=f"risk_reward_{minimum:.2f}",
                min_risk_reward=minimum,
            )
        )
    for candles in (1, 2, 3):
        definitions.append(
            replace(
                MODELS["MODEL_D_CLOSE_EXTENSION"],
                name=f"confirmation_delay_{candles}",
                max_candles_after_confirmation=candles,
            )
        )
    for wait in (15, 30):
        definitions.append(
            replace(
                MODELS["MODEL_F_GAP_AWARE"],
                name=f"gap_wait_{wait}",
                gap_wait_minutes=wait,
            )
        )
    definitions.extend(
        [
            replace(
                MODELS["MODEL_F_GAP_AWARE"],
                name="gap_opening_range_only",
                gap_wait_minutes=0,
                gap_require_opening_range=True,
                gap_require_alignment=False,
            ),
            replace(
                MODELS["MODEL_F_GAP_AWARE"],
                name="gap_direction_alignment_only",
                gap_wait_minutes=0,
                gap_require_opening_range=False,
                gap_require_alignment=True,
            ),
            replace(
                MODELS["MODEL_F_GAP_AWARE"],
                name="gap_return_to_vwap",
                gap_wait_minutes=0,
                gap_require_opening_range=False,
                gap_require_alignment=False,
                gap_require_vwap_return=True,
            ),
            replace(
                MODELS["MODEL_B_CLOSE_ONLY"],
                name="vwap_alignment_descriptive",
            ),
            replace(
                MODELS["MODEL_B_CLOSE_ONLY"],
                name="vwap_alignment_soft",
            ),
            replace(
                MODELS["MODEL_B_CLOSE_ONLY"],
                name="vwap_alignment_hard",
                require_vwap_alignment=True,
            ),
            replace(
                MODELS["MODEL_B_CLOSE_ONLY"],
                name="entry_immediate_breakout",
                confirmation="any_close",
            ),
            replace(
                MODELS["MODEL_B_CLOSE_ONLY"],
                name="entry_one_candle_hold",
                confirmation="one_candle_hold",
            ),
            replace(
                MODELS["MODEL_B_CLOSE_ONLY"],
                name="entry_retest_and_hold",
                confirmation="retest_hold",
            ),
        ]
    )

    for model in definitions:
        all_rows = []
        for frame, setups in frames_and_setups:
            all_rows.append(evaluate_model(frame, setups, model))
        rows = pd.concat(all_rows, ignore_index=True)
        variants.append(
            {
                "variant": model.name,
                "rules": asdict(model),
                "metrics": candidate_metrics(rows),
            }
        )
    return variants


def walk_forward(model_rows):
    """Evaluate fixed models across chronological expanding windows."""
    all_times = sorted(
        {
            pd.Timestamp(value)
            for rows in model_rows.values()
            for value in rows["signal_time"]
        }
    )
    if len(all_times) < 3:
        return {"folds": [], "conclusion": "inconclusive"}
    boundaries = [
        all_times[len(all_times) // 3],
        all_times[(len(all_times) * 2) // 3],
    ]
    folds = []
    for fold_index, (train_end, validation_end) in enumerate(
        (
            (boundaries[0], boundaries[1]),
            (boundaries[1], all_times[-1] + pd.Timedelta(microseconds=1)),
        ),
        start=1,
    ):
        candidates = {}
        for name, rows in model_rows.items():
            times = pd.to_datetime(rows["signal_time"], utc=True)
            normalized_train_end = pd.Timestamp(train_end)
            if normalized_train_end.tzinfo is None:
                normalized_train_end = normalized_train_end.tz_localize("UTC")
            else:
                normalized_train_end = normalized_train_end.tz_convert("UTC")
            train = rows[times < normalized_train_end]
            candidates[name] = candidate_metrics(train)
        viable = [
            (name, metrics)
            for name, metrics in candidates.items()
            if metrics["active_entries"] >= 3
        ]
        selected = max(
            viable,
            key=lambda item: (
                item[1]["expectancy"]
                if item[1]["expectancy"] is not None
                else -math.inf,
                item[1]["active_entries"],
            ),
            default=(None, None),
        )[0]
        selected_rows = model_rows[selected] if selected else pd.DataFrame()
        selected_times = (
            pd.to_datetime(selected_rows["signal_time"], utc=True)
            if not selected_rows.empty
            else pd.Series(dtype="datetime64[ns, UTC]")
        )
        train_end_utc = pd.Timestamp(train_end)
        train_end_utc = (
            train_end_utc.tz_localize("UTC")
            if train_end_utc.tzinfo is None
            else train_end_utc.tz_convert("UTC")
        )
        validation_end_utc = pd.Timestamp(validation_end)
        validation_end_utc = (
            validation_end_utc.tz_localize("UTC")
            if validation_end_utc.tzinfo is None
            else validation_end_utc.tz_convert("UTC")
        )
        validation = (
            selected_rows[
                (selected_times >= train_end_utc)
                & (selected_times < validation_end_utc)
            ]
            if selected
            else pd.DataFrame()
        )
        folds.append(
            {
                "fold": fold_index,
                "train_end": pd.Timestamp(train_end).isoformat(),
                "validation_end": pd.Timestamp(validation_end).isoformat(),
                "selected_on_train": selected,
                "train_metrics": candidates.get(selected) if selected else None,
                "validation_metrics": candidate_metrics(validation),
            }
        )
    period_ranges = (
        (None, boundaries[0]),
        (boundaries[0], boundaries[1]),
        (boundaries[1], all_times[-1] + pd.Timedelta(microseconds=1)),
    )
    leave_one_period_out = []
    for period_index, (start, end) in enumerate(period_ranges, start=1):
        model_metrics = {}
        for name, rows in model_rows.items():
            times = pd.to_datetime(rows["signal_time"], utc=True)
            end_utc = pd.Timestamp(end)
            end_utc = (
                end_utc.tz_localize("UTC")
                if end_utc.tzinfo is None
                else end_utc.tz_convert("UTC")
            )
            if start is None:
                held_out = rows[times < end_utc]
            else:
                start_utc = pd.Timestamp(start)
                start_utc = (
                    start_utc.tz_localize("UTC")
                    if start_utc.tzinfo is None
                    else start_utc.tz_convert("UTC")
                )
                held_out = rows[(times >= start_utc) & (times < end_utc)]
            model_metrics[name] = candidate_metrics(held_out)
        leave_one_period_out.append(
            {
                "held_out_period": period_index,
                "start": pd.Timestamp(start).isoformat() if start is not None else None,
                "end": pd.Timestamp(end).isoformat(),
                "models": model_metrics,
            }
        )
    return {
        "folds": folds,
        "leave_one_period_out": leave_one_period_out,
        "conclusion": "inconclusive"
        if any(
            fold["validation_metrics"]["active_entries"] < 5
            for fold in folds
        )
        else "promising but unproven",
    }


def evaluate_experiment(symbol_frames):
    frames_and_setups = []
    for symbol, raw in symbol_frames.items():
        frames_and_setups.append(collect_base_setups(symbol, raw))
    model_rows = {}
    reports = {}
    for name, model in MODELS.items():
        rows = pd.concat(
            [
                evaluate_model(frame, setups, model)
                for frame, setups in frames_and_setups
            ],
            ignore_index=True,
        )
        model_rows[name] = rows
        reports[name] = {
            "definition": asdict(model),
            **model_report(rows),
        }
    return {
        "models": reports,
        "parameter_sweeps": parameter_sweeps(frames_and_setups),
        "walk_forward": walk_forward(model_rows),
        "rows": pd.concat(model_rows.values(), ignore_index=True),
    }


def shadow_record(result, frame=None, index=None, now=None):
    """Build one isolated shadow record without mutating the production result."""
    snapshot = dict(result or {})
    signal = snapshot.get("signal")
    direction = (
        "Bullish"
        if signal == "BULLISH SETUP"
        else "Bearish"
        if signal == "BEARISH SETUP"
        else None
    )
    status = DETECTED if direction else WATCHING
    reason = "base directional setup detected" if direction else "no base directional setup"
    regime = None
    gap = None
    if frame is not None and index is not None and 0 <= index < len(frame):
        classification = classify_market_regime(frame, index)
        regime = classification["regime"]
        gap = classify_gap(classification["opening_gap_atr"])
        if direction:
            trigger = _number(
                snapshot.get("resistance")
                if direction == "Bullish"
                else snapshot.get("support")
            )
            atr = _number(snapshot.get("atr"), 0.0)
            price = _number(snapshot.get("price"), 0.0)
            if trigger is not None and close_confirmed(
                price, trigger, atr, direction
            ):
                status = CONFIRMED
                reason = "current close confirms the experimental trigger"
    timestamp = now or datetime.now().astimezone().isoformat()
    identity = "|".join(
        str(value)
        for value in (
            EXPERIMENT_ID,
            snapshot.get("symbol"),
            snapshot.get("last_candle_at") or snapshot.get("timestamp") or timestamp,
            status,
        )
    )
    return {
        "experiment_id": EXPERIMENT_ID,
        "shadow_id": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
        "recorded_at": timestamp,
        "symbol": snapshot.get("symbol"),
        "production_signal": signal,
        "production_confidence": snapshot.get("confidence"),
        "experimental_status": status,
        "rejection_reason": reason if status in {REJECTED, INVALIDATED} else None,
        "decision_reason": reason,
        "confirmation_timestamp": timestamp if status == CONFIRMED else None,
        "theoretical_entry": snapshot.get("entry"),
        "theoretical_stop": snapshot.get("stop"),
        "theoretical_target_1": snapshot.get("target"),
        "theoretical_risk_reward": risk_reward_at_entry(
            _number(snapshot.get("entry")),
            _number(snapshot.get("stop")),
            _number(snapshot.get("target")),
            direction,
        )
        if direction
        else None,
        "regime": regime,
        "gap_classification": gap,
    }


def append_shadow_record(record, path=DEFAULT_SHADOW_FILE):
    """Append one deduplicated experimental record to its isolated JSONL log."""
    target = Path(path)
    try:
        if target.exists():
            for line in target.read_text(encoding="utf-8").splitlines():
                try:
                    if json.loads(line).get("shadow_id") == record.get("shadow_id"):
                        return False
                except json.JSONDecodeError:
                    continue
        with target.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
        return True
    except OSError as exc:
        LOGGER.warning("Experiment 001 shadow write failed: %s", exc)
        return False


def record_live_shadow(result, frame, index, path=DEFAULT_SHADOW_FILE):
    """Safely observe a completed production result and return it unchanged."""
    record = shadow_record(result, frame, index)
    append_shadow_record(record, path)
    return result
