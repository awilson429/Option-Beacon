from datetime import datetime

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    service: str = "optionbeacon-api"
    database: str
    timestamp: datetime
    version: str


class SystemStatus(BaseModel):
    status: str
    market_status: str
    database: str
    data_freshness: str
    worker_status: str
    worker_last_success: datetime | None = None
    provider_status: str = "not_queried"
    timestamp: datetime
