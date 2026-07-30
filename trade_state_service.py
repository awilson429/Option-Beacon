"""Service boundary between scanner/UI code and authoritative trade storage."""

from __future__ import annotations

import logging
import os
from dataclasses import asdict
from datetime import datetime, timezone

from signal_history import (
    TradeOutcome,
    deserialize_trade_outcome,
    serialize_trade_outcome,
)
from trade_repository import (
    DEFAULT_REPOSITORY_FILE,
    RepositoryUnavailable,
    TradeRepository,
    parse_utc,
    utc_now,
)
from trade_storage import database_url as configured_database_url


LOGGER = logging.getLogger(__name__)
DEFAULT_STALE_MINUTES = 15


def repository_for_runtime(
    *,
    db_file=DEFAULT_REPOSITORY_FILE,
    branch=None,
    database_url=None,
) -> TradeRepository:
    explicitly_required = os.getenv(
        "OPTIONBEACON_REQUIRE_DURABLE_STORAGE", ""
    ).lower() in {"1", "true", "yes"}
    require_durable = explicitly_required or branch == "main"
    resolved_database_url = (
        configured_database_url()
        if database_url is None
        else database_url
    )
    return TradeRepository(
        db_file,
        database_url=resolved_database_url,
        require_durable=require_durable,
    )


def sync_trade_outcome(
    repository: TradeRepository, record: TradeOutcome, *, source_version="stable-v1"
) -> dict:
    """Idempotently project one legacy-compatible outcome into SQL."""
    payload = serialize_trade_outcome(record)
    state = _outcome_state(record)
    opportunity = repository.create_opportunity(
        opportunity_id=record.trade_id,
        idempotency_key=record.trade_id,
        symbol=record.symbol,
        direction=record.direction,
        playbook=record.setup,
        signal_timestamp=record.timestamp,
        source_version=source_version,
        state=state,
        confidence=record.confidence,
        entry_reference=record.entry,
        stop_reference=record.stop,
        target_1=record.target_1,
        target_2=record.target_2,
        target_3=record.target_3,
        metadata={"trade_outcome": payload, "legacy_compatible": True},
    )
    repository.update_opportunity(
        opportunity["id"],
        state=state,
        confidence=record.confidence,
        entry_reference=record.entry,
        stop_reference=record.stop,
        target_1=record.target_1,
        target_2=record.target_2,
        target_3=record.target_3,
        metadata_json={"trade_outcome": payload, "legacy_compatible": True},
    )
    if record.entry_time is not None:
        trade = repository.open_trade(
            opportunity["id"],
            trade_id=record.trade_id,
            opened_at=record.entry_time,
            entry_price=record.entry,
            stop_price=record.stop,
            target_1=record.target_1,
            target_2=record.target_2,
            target_3=record.target_3,
            metadata={"trade_outcome": payload},
        )
        if record.exit_time is not None:
            repository.close_trade(
                trade["id"],
                closed_at=record.exit_time,
                exit_price=_outcome_exit_price(record),
                exit_reason=record.exit_reason,
                realized_result=record.realized_return,
                metadata={"trade_outcome": payload},
            )
        else:
            repository.update_trade(
                trade["id"],
                metadata_json={"trade_outcome": payload},
            )
    return repository.get_opportunity(opportunity["id"])


def sync_trade_outcomes(repository, records, *, source_version="stable-v1") -> int:
    synced = 0
    for record in records:
        try:
            sync_trade_outcome(repository, record, source_version=source_version)
            synced += 1
        except Exception:
            LOGGER.exception("Could not synchronize trade outcome %s", record.trade_id)
    return synced


def list_trade_outcomes(repository: TradeRepository, *, limit=5000) -> list[TradeOutcome]:
    records = []
    for opportunity in repository.list_opportunities(limit=limit):
        payload = (opportunity.get("metadata") or {}).get("trade_outcome")
        if not payload:
            continue
        try:
            records.append(deserialize_trade_outcome(payload))
        except Exception:
            LOGGER.exception(
                "Could not decode authoritative outcome %s", opportunity.get("id")
            )
    return records


def authoritative_trade_state(
    *,
    branch=None,
    database_url=None,
    db_file=DEFAULT_REPOSITORY_FILE,
    stale_minutes=DEFAULT_STALE_MINUTES,
    now=None,
) -> dict:
    """Return records plus explicit storage/scanner reliability state."""
    checked_at = now or utc_now()
    try:
        repository = repository_for_runtime(
            db_file=db_file,
            branch=branch,
            database_url=database_url,
        )
        records = list_trade_outcomes(repository)
        health = repository.get_scan_health()
        state = scanner_health_state(
            health,
            now=checked_at,
            stale_minutes=stale_minutes,
        )
        return {
            "repository": repository,
            "records": records,
            "storage_state": "DURABLE"
            if repository.durable
            else "LOCAL DEVELOPMENT",
            "scanner_state": state["state"],
            "market_data_state": state["market_data_state"],
            "last_success_at": state["last_success_at"],
            "age_minutes": state["age_minutes"],
            "message": state["message"],
            "error": None,
        }
    except RepositoryUnavailable as exc:
        return {
            "repository": None,
            "records": [],
            "storage_state": "UNAVAILABLE",
            "scanner_state": "UNKNOWN",
            "market_data_state": "UNKNOWN",
            "last_success_at": None,
            "age_minutes": None,
            "message": (
                "Trade storage is unavailable. Open-trade information may be "
                "incomplete."
            ),
            "error": str(exc),
        }


def scanner_health_state(
    health,
    *,
    now=None,
    stale_minutes=DEFAULT_STALE_MINUTES,
) -> dict:
    checked_at = now or utc_now()
    if not health or not health.get("last_success_at"):
        if health and health.get("last_error_at"):
            return {
                "state": "ERROR",
                "market_data_state": health.get("market_data_state") or "ERROR",
                "last_success_at": None,
                "age_minutes": None,
                "message": "Scanner has not completed successfully. Latest scan failed.",
            }
        return {
            "state": "NEVER RUN",
            "market_data_state": "UNKNOWN",
            "last_success_at": None,
            "age_minutes": None,
            "message": "Scanner has never completed successfully.",
        }
    success = parse_utc(health["last_success_at"])
    age = max(0.0, (checked_at.astimezone(timezone.utc) - success).total_seconds() / 60)
    later_error = parse_utc(health.get("last_error_at"))
    if later_error and later_error > success:
        state = "ERROR"
        message = f"Scanner error. Last successful scan: {round(age)} minutes ago."
    elif age >= stale_minutes:
        state = "STALE"
        message = f"Scanner data is stale. Last successful scan: {round(age)} minutes ago."
    else:
        state = "CURRENT"
        message = f"Scanner data is current. Last successful scan: {round(age)} minutes ago."
    return {
        "state": state,
        "market_data_state": health.get("market_data_state") or "UNKNOWN",
        "last_success_at": success,
        "age_minutes": age,
        "message": message,
    }


def _outcome_state(record):
    if record.exit_time is not None:
        return "CLOSED"
    if record.entry_time is not None:
        return "OPEN"
    return "CANDIDATE"


def _outcome_exit_price(record):
    if record.exit_reason == "STOP":
        return record.stop
    targets = {
        "TARGET_1": record.target_1,
        "TARGET_2": record.target_2,
        "TARGET_3": record.target_3,
    }
    return targets.get(record.exit_reason)
