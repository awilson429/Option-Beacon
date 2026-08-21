from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


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
