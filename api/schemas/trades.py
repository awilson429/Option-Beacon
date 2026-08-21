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
