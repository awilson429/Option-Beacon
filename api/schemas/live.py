from datetime import date, datetime

from pydantic import BaseModel, Field

from api.schemas.provenance import ProvenanceCycleHealth, ProvenanceObservationResponse
from api.schemas.scanner import ScannerHealth, ScannerInstrument, ScannerLaneDecision
from api.schemas.system import SystemStatus
from api.schemas.trades import ActiveTradeResponse, TradeResponse


class LiveMarketSnapshot(BaseModel):
    session_date: date
    session_state: str
    last_authoritative_data_at: datetime | None = None
    freshness: str


class LiveSymbolSnapshot(BaseModel):
    symbol: str
    data_status: str
    observation: ProvenanceObservationResponse | None = None
    scanner: ScannerInstrument
    latest_decisions: list[ScannerLaneDecision] = Field(default_factory=list)


class LiveDecision(BaseModel):
    decision_id: str | None = None
    opportunity_id: str
    symbol: str
    lane: str
    timestamp: datetime | None = None
    action: str | None = None
    score: float | None = None
    setup: str | None = None
    direction: str | None = None
    reason_code: str | None = None
    explanation: str | None = None
    observation_id: str | None = None
    scan_cycle_id: str | None = None


class LiveScannerSnapshot(BaseModel):
    cycle_id: str | None = None
    cycle_timestamp: datetime | None = None
    cycle_completion_state: str | None = None
    latest_processed_symbols: list[str] = Field(default_factory=list)
    status: str
    last_successful_completed_cycle: datetime | None = None
    health: ScannerHealth


class LiveSystemSnapshot(BaseModel):
    state: SystemStatus
    coverage: dict[str, str]
    provenance: ProvenanceCycleHealth
    stale_or_missing: list[str] = Field(default_factory=list)


class LiveSnapshotResponse(BaseModel):
    schema_version: str = "1"
    snapshot_id: str
    generated_at: datetime
    data_status: str
    market: LiveMarketSnapshot
    symbols: dict[str, LiveSymbolSnapshot]
    scanner: LiveScannerSnapshot
    decisions: list[LiveDecision] = Field(default_factory=list)
    active_trades: list[ActiveTradeResponse] = Field(default_factory=list)
    recent_trades: list[TradeResponse] = Field(default_factory=list)
    system: LiveSystemSnapshot
    provenance: dict[str, str | int | None]
