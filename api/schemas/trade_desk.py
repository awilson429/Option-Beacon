from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from api.schemas.capital import CapitalDecisionResponse, CapitalLaneState


class Bias(BaseModel):
    direction: str | None = None
    label: str | None = None


class TradeCoverage(BaseModel):
    direction: str | None = None
    entry_trigger: float | None = None
    state: str


class Setup(BaseModel):
    state: str
    strike: float | None = None
    expiration: str | None = None
    dte: int | None = None
    spread: float | None = None
    contract: str | None = None


class Context(BaseModel):
    level: str = "unavailable"
    known_factors: list[str] = Field(default_factory=list)
    details: dict[str, Any] | None = None


class Confirmations(BaseModel):
    state: str = "unavailable"
    items: list[str] = Field(default_factory=list)


class MarketCondition(BaseModel):
    regime: str | None = None


class SessionSummary(BaseModel):
    pnl: float | None = None
    trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float | None = None


class TradeDeskResponse(BaseModel):
    symbol: str
    price: float | None = None
    market_status: str
    data_status: str
    last_updated: datetime | None = None
    bias: Bias
    trade_coverage: TradeCoverage
    setup: Setup
    context: Context
    confirmations: Confirmations
    market_condition: MarketCondition
    session: SessionSummary


class HomeSessionSummary(BaseModel):
    realized_pnl: float | None = None
    unrealized_pnl: float | None = None
    total_pnl: float | None = None
    trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float | None = None
    active_trades: int = 0


class HomeTrade(BaseModel):
    id: str
    symbol: str | None = None
    direction: str | None = None
    strategy: str
    lane_role: str
    status: str
    setup: str | None = None
    entry_price: float | None = None
    current_price: float | None = None
    contract: str | None = None
    pnl: float | None = None
    opened_at: datetime | None = None
    closed_at: datetime | None = None
    event: str


class LaneSummary(BaseModel):
    key: str
    label: str
    role: str
    active_trades: int = 0
    trades_today: int = 0
    realized_pnl: float | None = None
    description: str


class TradeDeskHomeResponse(BaseModel):
    as_of: datetime
    session: HomeSessionSummary
    active: list[HomeTrade] = Field(default_factory=list)
    lanes: list[LaneSummary] = Field(default_factory=list)
    recent_activity: list[HomeTrade] = Field(default_factory=list)
    accounts: list[CapitalLaneState] = Field(default_factory=list)
    capital_decisions: list[CapitalDecisionResponse] = Field(default_factory=list)
    data_status: str
