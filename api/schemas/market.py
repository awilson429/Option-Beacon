from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class MarketSummary(BaseModel):
    symbol: str
    market_status: str
    data_status: str
    price: float | None = None
    bias: str | None = None
    regime: str | None = None
    last_updated: datetime | None = None
    source: str = "persisted_state"
    metadata: dict[str, Any] = Field(default_factory=dict)
