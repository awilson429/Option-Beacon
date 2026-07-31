"""Sanitized authoritative-storage and scanner-health verification."""

from __future__ import annotations

import json
import logging
import os
import sys

from trade_repository import DEFAULT_SCANNER_ID, RepositoryUnavailable
from trade_state_service import (
    DEFAULT_STALE_MINUTES,
    repository_for_runtime,
    scanner_health_state,
)


LOGGER = logging.getLogger(__name__)


def check_health(
    *,
    repository=None,
    scanner_id=None,
    stale_minutes=DEFAULT_STALE_MINUTES,
):
    scanner_id = scanner_id or os.getenv(
        "OPTIONBEACON_SCANNER_ID", DEFAULT_SCANNER_ID
    )
    try:
        repository = repository or repository_for_runtime()
        health = repository.get_scan_health(scanner_id)
        state = scanner_health_state(
            health,
            stale_minutes=stale_minutes,
        )
        opportunities = repository.list_opportunities(limit=1)
        result = {
            "database_reachable": True,
            "schema_present": True,
            "storage_backend": repository.backend,
            "storage_durable": repository.durable,
            "scanner_id": scanner_id,
            "scanner_state": state["state"],
            "last_success_at": (
                state["last_success_at"].isoformat()
                if state["last_success_at"]
                else None
            ),
            "heartbeat_age_minutes": state["age_minutes"],
            "market_data_state": state["market_data_state"],
            "open_trade_count": len(repository.list_open_trades()),
            "most_recent_opportunity_timestamp": (
                opportunities[0]["signal_timestamp"]
                if opportunities
                else None
            ),
        }
        code = 0 if state["state"] == "CURRENT" else 1
        return code, result
    except RepositoryUnavailable as exc:
        LOGGER.exception("Worker healthcheck repository initialization failed: %s", exc)
        return 2, {
            "database_reachable": False,
            "schema_present": False,
            "storage_backend": "unavailable",
            "error": type(exc).__name__,
        }


def main():
    code, result = check_health()
    print(json.dumps(result, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
