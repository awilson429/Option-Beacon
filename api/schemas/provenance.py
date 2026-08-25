from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from api.schemas.trades import TradeManagementSnapshotResponse


class ProvenanceCycleHealth(BaseModel):
    data_status: str
    provenance_status: str
    scan_cycle_id: str | None = None
    cycle_status: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None


class ProvenanceObservationResponse(BaseModel):
    observation_id: str
    scan_cycle_id: str
    symbol: str
    observed_at: datetime
    data_timestamp: datetime | None = None
    underlying_price: float | None = None
    session_state: str
    direction: str | None = None
    data_quality: str
    stale: bool = False
    signal: str | None = None
    setup_state: str | None = None
    qualification_state: str
    reason_code: str
    explanation: str
    total_score: float | None = None
    confidence: float | None = None
    bullish_score: float | None = None
    bearish_score: float | None = None
    component_scores: dict[str, float] = Field(default_factory=dict)
    indicators: dict[str, float] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)
    opportunity_id: str | None = None
    source_version: str | None = None


class RecentProvenanceResponse(BaseModel):
    as_of: datetime
    data_status: str
    health: ProvenanceCycleHealth
    observations: list[ProvenanceObservationResponse] = Field(default_factory=list)


class ProvenanceLaneChain(BaseModel):
    lane: str
    decisions: list[dict[str, Any]] = Field(default_factory=list)
    decision_trade_links: list[dict[str, Any]] = Field(default_factory=list)
    trade: dict[str, Any] | None = None
    management: list[TradeManagementSnapshotResponse] = Field(default_factory=list)
    outcome: dict[str, Any] | None = None


class OpportunityProvenanceResponse(BaseModel):
    as_of: datetime
    data_status: str
    opportunity_id: str
    observation: ProvenanceObservationResponse | None = None
    opportunity: dict[str, Any] | None = None
    lanes: list[ProvenanceLaneChain] = Field(default_factory=list)


class TradeProvenanceResponse(BaseModel):
    as_of: datetime
    data_status: str
    trade_id: str
    lane: str
    observation: ProvenanceObservationResponse | None = None
    qualification: dict[str, Any] | None = None
    opportunity: dict[str, Any] | None = None
    capital_decision: dict[str, Any] | None = None
    decision_trade_link: dict[str, Any] | None = None
    trade: dict[str, Any] | None = None
    management: list[TradeManagementSnapshotResponse] = Field(default_factory=list)
    outcome: dict[str, Any] | None = None
