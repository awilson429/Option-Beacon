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
    exit_state: str | None = None
    trade_coach_status: str | None = None
    thesis_status: str | None = None
    momentum_state: str | None = None
    structure_state: str | None = None
    target_progress: str | None = None
    stop_management_state: str | None = None
    last_management_update: datetime | None = None
    management_data_status: str = "unavailable"
