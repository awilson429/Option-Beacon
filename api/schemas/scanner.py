from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ScannerSectionStatus(BaseModel):
    section: str
    data_status: str
    message: str | None = None


class ScannerHealth(BaseModel):
    state: str
    message: str
    market_data_state: str
    worker_status: str
    provider_status: str = "not_queried"
    data_freshness: str
    last_started_at: datetime | None = None
    last_completed_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error_at: datetime | None = None
    last_error_message: str | None = None
    scan_duration_seconds: float | None = None
    symbols_processed: int | None = None
    symbols_attempted: int | None = None
    symbol_count: int | None = None
    results: int | None = None
    failures: int | None = None
    expected_interval_seconds: int | None = None
    next_expected_at: datetime | None = None


class ScannerInstrument(BaseModel):
    symbol: str
    data_status: str
    underlying_price: float | None = None
    direction: str | None = None
    setup: str | None = None
    score: float | None = None
    confidence: float | None = None
    signal_state: str
    observed_at: datetime | None = None
    signal_age_seconds: int | None = None
    freshness: str
    actionable: bool = False
    context: dict[str, Any] = Field(default_factory=dict)


class ScannerLaneDecision(BaseModel):
    lane: str
    data_status: str
    state: str | None = None
    reason_code: str | None = None
    explanation: str | None = None
    proposed_contract: str | None = None
    proposed_quantity: int | None = None
    proposed_capital_required: float | None = None
    proposed_dollar_risk: float | None = None
    proposed_account_risk_pct: float | None = None
    decided_at: datetime | None = None


class ScannerOpportunity(BaseModel):
    opportunity_id: str
    symbol: str
    direction: str | None = None
    strategy: str | None = None
    observed_at: datetime
    score: float | None = None
    confidence: float | None = None
    contract: str | None = None
    entry: float | None = None
    stop: float | None = None
    targets: list[float] = Field(default_factory=list)
    status: str
    actionable: bool = False
    data_status: str
    freshness: str
    context: dict[str, Any] = Field(default_factory=dict)
    lane_decisions: list[ScannerLaneDecision] = Field(default_factory=list)


class ScannerActivity(BaseModel):
    activity_id: str
    event_type: str
    occurred_at: datetime
    symbol: str | None = None
    direction: str | None = None
    opportunity_id: str | None = None
    lane: str | None = None
    status: str
    reason_code: str | None = None
    description: str


class ScannerResponse(BaseModel):
    as_of: datetime
    market_status: str
    data_status: str
    research_control_role: str = "RESEARCH_CONTROL_ONLY"
    health: ScannerHealth
    instruments: list[ScannerInstrument] = Field(default_factory=list)
    opportunities: list[ScannerOpportunity] = Field(default_factory=list)
    recent_activity: list[ScannerActivity] = Field(default_factory=list)
    sections: list[ScannerSectionStatus] = Field(default_factory=list)
