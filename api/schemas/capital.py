from datetime import datetime

from pydantic import BaseModel, Field


class CapitalMetrics(BaseModel):
    trades: int = 0
    win_rate: float | None = None
    average_winner: float | None = None
    average_loser: float | None = None
    expectancy: float | None = None
    profit_factor: float | None = None
    average_capital_deployed: float | None = None
    peak_capital_deployed: float | None = None
    average_risk_per_trade: float | None = None
    maximum_risk_per_trade: float | None = None
    rejected_opportunities: int = 0
    missed_winners: int = 0
    avoided_losers: int = 0
    capital_efficiency_pct: float | None = None


class CapitalPositionResponse(BaseModel):
    position_id: str
    lane: str
    opportunity_id: str
    symbol: str
    direction: str | None = None
    strategy: str
    contract_symbol: str | None = None
    strike: float | None = None
    expiration: str | None = None
    dte: int | None = None
    entry_premium: float | None = None
    current_premium: float | None = None
    quantity: int
    capital_committed: float
    initial_dollar_risk: float
    unrealized_pnl: float
    realized_pnl: float | None = None
    entry_timestamp: datetime
    time_in_trade_seconds: int | None = None
    stop: float | None = None
    targets: list[float] = Field(default_factory=list)
    status: str


class CapitalLaneState(BaseModel):
    lane: str
    data_status: str
    starting_capital: float
    current_equity: float | None = None
    cash_available: float | None = None
    capital_committed: float | None = None
    net_pnl: float | None = None
    return_pct: float | None = None
    realized_pnl: float | None = None
    unrealized_pnl: float | None = None
    fees: float | None = None
    slippage: float | None = None
    peak_equity: float | None = None
    current_drawdown_pct: float | None = None
    maximum_drawdown_pct: float | None = None
    daily_pnl: float | None = None
    open_risk: float | None = None
    open_positions: int = 0
    risk_state: str
    readiness_status: str
    metrics: CapitalMetrics = Field(default_factory=CapitalMetrics)
    positions: list[CapitalPositionResponse] = Field(default_factory=list)
    updated_at: datetime | None = None


class CapitalOverview(BaseModel):
    as_of: datetime
    mode: str = "SIMULATION"
    lanes: list[CapitalLaneState] = Field(default_factory=list)
    mirror_role: str = "RESEARCH_CONTROL_ONLY"


class CapitalComparison(BaseModel):
    as_of: datetime
    lanes: list[CapitalLaneState] = Field(default_factory=list)
    winner: str
    evidence: str
    normalization: str


class CapitalDecisionResponse(BaseModel):
    decision_id: str
    lane: str
    opportunity_id: str
    symbol: str
    direction: str | None = None
    state: str
    reason_code: str
    explanation: str
    proposed_contract: str | None = None
    proposed_quantity: int = 0
    proposed_capital_required: float = 0
    proposed_dollar_risk: float = 0
    proposed_account_risk_pct: float = 0
    decided_at: datetime


class RiskLaneStatus(BaseModel):
    lane: str
    risk_state: str
    daily_pnl: float | None = None
    daily_loss_limit: float
    open_risk: float | None = None
    maximum_open_risk: float | None = None
    current_drawdown_pct: float | None = None
    entries_allowed: bool


class RiskStatusResponse(BaseModel):
    as_of: datetime
    lanes: list[RiskLaneStatus] = Field(default_factory=list)
