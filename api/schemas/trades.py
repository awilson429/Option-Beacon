from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TradeResponse(BaseModel):
    id: str
    opportunity_id: str
    symbol: str | None = None
    direction: str | None = None
    setup: str | None = None
    status: str
    opened_at: datetime | None = None
    closed_at: datetime | None = None
    entry_price: float | None = None
    last_price: float | None = None
    exit_price: float | None = None
    realized_result: float | None = None
    exit_reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActiveTradeResponse(TradeResponse):
    lane: str = "OB"
    lane_role: str = "AUTHORITATIVE"
    strategy: str | None = None
    data_status: str = "persisted"
    contract_symbol: str | None = None
    strike: float | None = None
    option_type: str | None = None
    expiration: str | None = None
    dte: int | None = None
    quantity: int | None = None
    entry_timestamp: datetime | None = None
    underlying_entry: float | None = None
    option_entry_premium: float | None = None
    capital_committed: float | None = None
    initial_dollar_risk: float | None = None
    account_risk_pct: float | None = None
    current_dollar_risk: float | None = None
    latest_underlying: float | None = None
    latest_option_mark: float | None = None
    unrealized_pnl: float | None = None
    unrealized_return_pct: float | None = None
    time_in_trade_seconds: int | None = None
    data_freshness: str = "unavailable"
    mark_timestamp: datetime | None = None
    stop: float | None = None
    target_1: float | None = None
    target_2: float | None = None
    target_3: float | None = None
    breakeven_state: str | None = None
    maximum_hold_minutes: int | None = None
    exit_score: int | None = None
    exit_label: str | None = None
    exit_state: str | None = None
    trade_coach_state: str | None = None
    trade_coach_status: str | None = None
    thesis_state: str | None = None
    thesis_status: str | None = None
    momentum_state: str | None = None
    structure_state: str | None = None
    target_progress: str | None = None
    stop_management_state: str | None = None
    management_reason: str | None = None
    management_updated_at: datetime | None = None
    last_management_update: datetime | None = None
    management_data_status: str = "unavailable"


class TradeManagementSnapshotResponse(BaseModel):
    snapshot_id: str
    trade_id: str
    opportunity_id: str
    lane: str
    lane_role: str
    symbol: str
    contract_symbol: str | None = None
    captured_at: datetime
    source_timestamp: datetime | None = None
    trade_status: str | None = None
    quantity: int | None = None
    entry_timestamp: datetime | None = None
    entry_premium: float | None = None
    latest_option_mark: float | None = None
    latest_underlying: float | None = None
    mark_timestamp: datetime | None = None
    time_in_trade_seconds: int | None = None
    current_stop: float | None = None
    target_1: float | None = None
    target_2: float | None = None
    target_3: float | None = None
    breakeven_state: str | None = None
    maximum_hold_minutes: int | None = None
    exit_score: int | None = None
    exit_label: str | None = None
    trade_coach_state: str | None = None
    thesis_state: str | None = None
    momentum_state: str | None = None
    structure_state: str | None = None
    target_progress: str | None = None
    stop_management_state: str | None = None
    management_reason: str | None = None
    management_version: str | None = None
    management_source: str
    unrealized_pnl: float | None = None
    unrealized_return_pct: float | None = None
    current_managed_risk: float | None = None
    data_freshness: str | None = None
    stale: bool = False
    missing_data: list[str] = Field(default_factory=list)
    state_fingerprint: str


class JournalMetrics(BaseModel):
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    breakeven: int = 0
    win_rate: float | None = None
    realized_pnl: float | None = None
    average_winner: float | None = None
    average_loser: float | None = None
    profit_factor: float | None = None
    average_return_pct: float | None = None
    average_hold_seconds: float | None = None


class JournalLaneMetrics(JournalMetrics):
    lane: str


class HistoricalTradeResponse(BaseModel):
    trade_id: str
    opportunity_id: str
    lane: str
    lane_role: str
    symbol: str | None = None
    direction: str | None = None
    status: str
    strategy: str | None = None
    contract_symbol: str | None = None
    strike: float | None = None
    option_type: str | None = None
    expiration: str | None = None
    dte: int | None = None
    quantity: int | None = None
    entry_timestamp: datetime | None = None
    underlying_entry: float | None = None
    option_entry_premium: float | None = None
    capital_committed: float | None = None
    initial_dollar_risk: float | None = None
    exit_timestamp: datetime | None = None
    underlying_exit: float | None = None
    option_exit_premium: float | None = None
    exit_reason: str | None = None
    hold_duration_seconds: int | None = None
    realized_pnl: float | None = None
    realized_return_pct: float | None = None
    r_multiple: float | None = None
    mfe_dollars: float | None = None
    mae_dollars: float | None = None
    mfe_pct: float | None = None
    mae_pct: float | None = None
    result: str
    initial_stop: float | None = None
    target_1: float | None = None
    target_2: float | None = None
    target_3: float | None = None
    management_history_available: bool = False
    management_snapshot_count: int = 0
    final_exit_score: int | None = None
    final_management_label: str | None = None
    final_management_at: datetime | None = None
    data_quality: str
    missing_data: list[str] = Field(default_factory=list)
    source_version: str | None = None


class TradeHistoryResponse(BaseModel):
    as_of: datetime
    data_status: str
    total_count: int
    limit: int
    offset: int
    summary: JournalMetrics
    lanes: list[JournalLaneMetrics] = Field(default_factory=list)
    control_research: JournalMetrics | None = None
    trades: list[HistoricalTradeResponse] = Field(default_factory=list)
