from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from api.schemas.trade_desk import TradeDeskResponse


class OptionsDeskResponse(BaseModel):
    instruments: dict[str, TradeDeskResponse]


class ScalpStateResponse(BaseModel):
    symbol: str
    strategy: str = "SCALP_RESEARCH"
    mode: str = "SHADOW"
    market_status: str
    data_status: str
    current: dict[str, Any] | None = None
    live_update_fields: list[str] = Field(default_factory=lambda: ["state", "price", "probability", "entry_trigger", "maximum_chase", "contract", "data_freshness"])


class PerformanceResponse(BaseModel):
    symbol: str
    strategy: str = "SCALP_RESEARCH"
    metrics: dict[str, Any]


class ComparisonResponse(BaseModel):
    strategy: str = "SCALP_RESEARCH"
    symbols: dict[str, dict[str, Any]]
    normalization: str
