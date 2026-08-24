from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class StrategyMode(str, Enum):
    SHADOW = "SHADOW"


class Direction(str, Enum):
    CALL = "CALL"
    PUT = "PUT"


class ScalpState(str, Enum):
    IDLE = "IDLE"
    WATCHING = "WATCHING"
    FORMING = "FORMING"
    READY = "READY"
    TRIGGERED = "TRIGGERED"
    EXTENDED = "EXTENDED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"


TERMINAL_STATES = {ScalpState.EXTENDED, ScalpState.INVALIDATED, ScalpState.EXPIRED}
ALLOWED_TRANSITIONS = {
    ScalpState.IDLE: {ScalpState.WATCHING},
    ScalpState.WATCHING: {ScalpState.FORMING, ScalpState.IDLE, ScalpState.EXPIRED},
    ScalpState.FORMING: {ScalpState.READY, ScalpState.WATCHING, ScalpState.INVALIDATED, ScalpState.EXPIRED},
    ScalpState.READY: {ScalpState.TRIGGERED, ScalpState.EXTENDED, ScalpState.INVALIDATED, ScalpState.EXPIRED},
    ScalpState.TRIGGERED: {ScalpState.EXTENDED, ScalpState.INVALIDATED, ScalpState.EXPIRED},
    ScalpState.EXTENDED: set(), ScalpState.INVALIDATED: set(), ScalpState.EXPIRED: set(),
}


def transition(current: ScalpState | str, target: ScalpState | str) -> ScalpState:
    current, target = ScalpState(current), ScalpState(target)
    if target not in ALLOWED_TRANSITIONS[current]:
        raise ValueError(f"Invalid scalp transition: {current.value} -> {target.value}")
    return target


@dataclass(frozen=True)
class ScalpOpportunity:
    opportunity_id: str
    symbol: str
    observed_at: datetime
    direction: Direction | None
    setup_family: str | None
    state: ScalpState
    probability: float | None
    entry_trigger: float | None
    entry_zone: tuple[float, float] | None
    invalidation: float | None
    maximum_chase: float | None
    expected_move: float | None
    expected_hold_minutes: tuple[int, int] = (3, 15)
    features: dict[str, Any] = field(default_factory=dict)
    strategy: str = "SCALP_RESEARCH"
    mode: StrategyMode = StrategyMode.SHADOW

    def to_dict(self):
        value = asdict(self)
        value.update(direction=self.direction.value if self.direction else None,
                     state=self.state.value, mode=self.mode.value)
        return value
