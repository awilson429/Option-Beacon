"""Service boundary between scanner/UI code and authoritative trade storage."""

from __future__ import annotations

import logging
import json
import os
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from signal_history import (
    DEFAULT_MAX_CANDIDATE_AGE_MINUTES,
    DEFAULT_MAX_ENTERED_AGE_MINUTES,
    DEFAULT_MIN_ENTRY_CONFIDENCE,
    TradeOutcome,
    close_trade_outcome_end_of_day,
    deserialize_trade_outcome,
    expire_trade_outcome,
    scanner_result_to_trade_outcome,
    serialize_trade_outcome,
    update_trade_outcome,
)
from intraday_session import (
    DEFAULT_EOD_EXIT_TIME_ET,
    eastern_timestamp,
    intraday_entry_allowed,
    intraday_trade_exit_due,
)
from intelligence_capture import outcome_label, setup_feature_snapshot
from opportunity_context import build_opportunity_context, signal_age_bucket, timestamp
from live_trade_activity import persist_outcome_transition
from trade_repository import (
    DEFAULT_REPOSITORY_FILE,
    RepositoryUnavailable,
    TradeRepository,
    parse_utc,
    utc_now,
)
LOGGER = logging.getLogger(__name__)
DEFAULT_STALE_MINUTES = 15
SCANNER_PROGRESS_STALE_MINUTES = 5


def repository_for_runtime(
    *,
    db_file=DEFAULT_REPOSITORY_FILE,
    branch=None,
    database_url=None,
    diagnostic_callback=None,
) -> TradeRepository:
    explicitly_required = os.getenv(
        "OPTIONBEACON_REQUIRE_DURABLE_STORAGE", ""
    ).lower() in {"1", "true", "yes"}
    production_environment = (
        os.getenv("OPTIONBEACON_ENVIRONMENT", "").strip().lower()
        == "production"
    )
    require_durable = (
        explicitly_required or production_environment or branch == "main"
    )
    resolved_database_url = (
        os.getenv("DATABASE_URL", "").strip()
        if database_url is None
        else database_url
    )
    kwargs = {
        "database_url": resolved_database_url,
        "require_durable": require_durable,
    }
    if diagnostic_callback is not None:
        kwargs["diagnostic_callback"] = diagnostic_callback
    return TradeRepository(db_file, **kwargs)


def sync_trade_outcome(
    repository: TradeRepository, record: TradeOutcome, *, source_version="stable-v1",
    underlying_price=None, rule_score=None,
) -> dict:
    """Idempotently project one legacy-compatible outcome into SQL."""
    previous_opportunity = repository.get_opportunity(opportunity_id=record.trade_id)
    previous = None
    previous_payload = ((previous_opportunity or {}).get("metadata") or {}).get("trade_outcome")
    if previous_payload:
        try:
            previous = deserialize_trade_outcome(previous_payload)
        except Exception:
            LOGGER.exception("Could not decode previous outcome %s", record.trade_id)
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
                last_price=underlying_price,
                metadata_json={"trade_outcome": payload},
            )
    persist_outcome_transition(
        repository, previous, record,
        underlying_price=underlying_price, rule_score=rule_score,
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


def process_scanner_result(
    repository,
    result,
    *,
    source_version="stable-v1",
    max_candidate_age_minutes=DEFAULT_MAX_CANDIDATE_AGE_MINUTES,
    max_entered_age_minutes=DEFAULT_MAX_ENTERED_AGE_MINUTES,
    minimum_entry_confidence=DEFAULT_MIN_ENTRY_CONFIDENCE,
    current_timestamp=None,
    eod_exit_time=DEFAULT_EOD_EXIT_TIME_ET,
    scanner_id=None,
    run_number=None,
    outcome_records=None,
    provenance_observation_id=None,
    provenance_scan_cycle_id=None,
) -> int:
    """Advance authoritative outcomes directly from one stable scanner result."""
    symbol = str((result or {}).get("symbol") or "").upper()
    try:
        price = float((result or {}).get("price"))
    except (TypeError, ValueError):
        price = None
    timestamp = _result_timestamp(result)
    lifecycle_timestamp = current_timestamp or timestamp
    changed = 0
    records = outcome_records if outcome_records is not None else list_trade_outcomes(repository)
    for record in records:
        if record.symbol.upper() != symbol or record.exit_time is not None:
            continue
        prior_entry_time = record.entry_time
        before = serialize_trade_outcome(record)
        if price is not None and price > 0:
            eod_due = (
                record.entry_time is not None
                and intraday_trade_exit_due(
                    record.entry_time,
                    lifecycle_timestamp,
                    eod_exit_time,
                )
            )
            if eod_due and (
                eastern_timestamp(record.entry_time).date()
                < eastern_timestamp(lifecycle_timestamp).date()
            ):
                close_trade_outcome_end_of_day(
                    record,
                    price,
                    lifecycle_timestamp,
                )
            if record.exit_time is None:
                expire_trade_outcome(
                    record,
                    price,
                    lifecycle_timestamp,
                    max_candidate_age_minutes=max_candidate_age_minutes,
                    max_entered_age_minutes=max_entered_age_minutes,
                )
            if record.exit_time is None:
                if record.entry_time is not None or intraday_entry_allowed(
                    lifecycle_timestamp, eod_exit_time
                ):
                    update_trade_outcome(
                        record,
                        price,
                        lifecycle_timestamp,
                        minimum_entry_confidence=minimum_entry_confidence,
                    )
            if (
                record.entry_time is not None
                and record.exit_time is None
                and eod_due
            ):
                close_trade_outcome_end_of_day(
                    record,
                    price,
                    lifecycle_timestamp,
                )
        if serialize_trade_outcome(record) != before:
            entered_now = prior_entry_time is None and record.entry_time is not None
            sync_trade_outcome(
                repository,
                record,
                source_version=source_version,
                underlying_price=price,
                rule_score=(result or {}).get("score") or (result or {}).get("confidence"),
            )
            _persist_outcome_label(repository, record)
            if entered_now:
                _persist_authoritative_context_timing(repository, record)
                LOGGER.info(json.dumps({
                    "event": "authoritative_trade_entered",
                    "scanner_id": scanner_id, "run_number": run_number,
                    "opportunity_id": record.trade_id, "symbol": record.symbol,
                    "direction": record.direction, "confidence": record.confidence,
                    "trigger": record.entry, "entry_price": price,
                }, sort_keys=True))
            changed += 1
    candidate = scanner_result_to_trade_outcome(result)
    if (
        candidate is not None
        and repository.get_opportunity(opportunity_id=candidate.trade_id) is None
    ):
        sync_trade_outcome(
            repository,
            candidate,
            source_version=source_version,
            underlying_price=price,
            rule_score=(result or {}).get("score") or (result or {}).get("confidence"),
        )
        _persist_intelligence_snapshot(
            repository, result, candidate, source_version=source_version
        )
        _persist_opportunity_context(repository, result, candidate)
        _persist_outcome_label(repository, candidate)
        if outcome_records is not None:
            outcome_records.append(candidate)
        changed += 1
    if candidate is not None and provenance_observation_id:
        try:
            repository.link_provenance_opportunity(
                provenance_observation_id, candidate.trade_id
            )
        except Exception as exc:
            LOGGER.exception(json.dumps({
                "event": "provenance_opportunity_link_failed",
                "scan_cycle_id": provenance_scan_cycle_id,
                "observation_id": provenance_observation_id,
                "opportunity_id": candidate.trade_id,
                "symbol": symbol,
            }, sort_keys=True))
            try:
                repository.mark_provenance_degraded(
                    provenance_scan_cycle_id,
                    f"opportunity link failed: {type(exc).__name__}",
                )
            except Exception:
                LOGGER.exception("Could not mark provenance cycle degraded")
    return changed


def _persist_intelligence_snapshot(repository, result, record, *, source_version):
    try:
        scanner_id = str((result or {}).get("scanner_id") or "optionbeacon-scanner")
        snapshot_input = dict(result or {})
        snapshot_input.setdefault("source_version", source_version)
        snapshot = setup_feature_snapshot(snapshot_input, record, scanner_id=scanner_id)
        repository.create_intelligence_snapshot(record.trade_id, snapshot.to_dict(), schema_version=snapshot.schema_version)
    except Exception:
        LOGGER.exception("Could not persist intelligence snapshot %s", record.trade_id)


def _persist_opportunity_context(repository, result, record):
    """Failure-isolated shadow capture; it cannot affect authoritative behavior."""
    try:
        context = build_opportunity_context(dict(result or {}), record)
        repository.create_opportunity_context(record.trade_id, context, schema_version=context["schema_version"])
    except Exception:
        LOGGER.exception("Could not persist opportunity context %s", record.trade_id)


def _persist_authoritative_context_timing(repository, record):
    try:
        stored = repository.get_opportunity_context(record.trade_id)
        if not stored:
            return
        context = stored["context"]
        maturity = context.get("signal_maturity") or {}
        lifecycle = context.get("lifecycle") or {}
        entered = timestamp(record.entry_time)
        first_seen = timestamp(maturity.get("first_seen_timestamp"))
        setup = timestamp(lifecycle.get("setup_detected_at"))
        first_age = max(0, (entered - first_seen).total_seconds()) if entered and first_seen and entered >= first_seen else None
        setup_age = max(0, (entered - setup).total_seconds()) if entered and setup and entered >= setup else None
        repository.enrich_opportunity_context(record.trade_id, {
            "lifecycle": {"authoritative_entered_at": entered.isoformat(), "setup_to_authoritative_seconds": setup_age,
                "signal_age_bucket": signal_age_bucket(setup_age if setup_age is not None else first_age)},
            "signal_maturity": {"authoritative_timestamp": entered.isoformat(), "seconds_from_first_seen_to_authoritative": first_age},
        })
    except Exception:
        LOGGER.exception("Could not enrich authoritative context timing %s", record.trade_id)


def _persist_outcome_label(repository, record):
    try:
        label = outcome_label(record)
        repository.upsert_intelligence_outcome(record.trade_id, label.to_dict(), schema_version=label.schema_version)
    except Exception:
        LOGGER.exception("Could not persist intelligence outcome %s", record.trade_id)


def list_trade_outcomes(repository: TradeRepository, *, limit=5000,
                        active_only=False) -> list[TradeOutcome]:
    records = []
    payload_reader = getattr(repository, "list_outcome_payloads", None)
    opportunities = (
        payload_reader(limit=limit, active_only=active_only)
        if callable(payload_reader) else repository.list_opportunities(limit=limit)
    )
    for opportunity in opportunities:
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
        health = repository.get_latest_scan_health()
        scan_lock = repository.get_scan_lock(
            health.get("scanner_id") if health else None
        ) if health else None
        state = scanner_health_state(
            health,
            scan_lock=scan_lock,
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
            "scanner_id": health.get("scanner_id") if health else None,
            "last_success_at": state["last_success_at"],
            "last_completed_at": state["last_completed_at"],
            "last_symbols_processed": state["last_symbols_processed"],
            "current_run_number": state["current_run_number"],
            "current_symbols_attempted": state["current_symbols_attempted"],
            "current_symbol_count": state["current_symbol_count"],
            "current_results": state["current_results"],
            "current_failures": state["current_failures"],
            "progress_updated_at": state["progress_updated_at"],
            "age_minutes": state["age_minutes"],
            "message": state["message"],
            "error": None,
        }
    except RepositoryUnavailable as exc:
        LOGGER.exception("Authoritative trade repository is unavailable: %s", exc)
        return {
            "repository": None,
            "records": [],
            "storage_state": "UNAVAILABLE",
            "scanner_state": "UNKNOWN",
            "market_data_state": "UNKNOWN",
            "scanner_id": None,
            "last_success_at": None,
            "last_completed_at": None,
            "last_symbols_processed": None,
            "current_run_number": None,
            "current_symbols_attempted": None,
            "current_symbol_count": None,
            "current_results": None,
            "current_failures": None,
            "progress_updated_at": None,
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
    scan_lock=None,
    now=None,
    stale_minutes=DEFAULT_STALE_MINUTES,
) -> dict:
    checked_at = now or utc_now()
    health = health or {}
    current_owner = health.get("current_owner_id")
    lock_owner = (scan_lock or {}).get("owner_id")
    lock_expires = parse_utc((scan_lock or {}).get("expires_at"))
    progress_updated = parse_utc(health.get("progress_updated_at"))
    progress_fresh = (
        progress_updated is not None
        and checked_at.astimezone(timezone.utc) - progress_updated
        < timedelta(minutes=SCANNER_PROGRESS_STALE_MINUTES)
    )
    scanning = (
        str(health.get("market_data_state") or "").upper() == "SCANNING"
        and bool(current_owner)
        and current_owner == lock_owner
        and lock_expires is not None
        and lock_expires > checked_at.astimezone(timezone.utc)
        and progress_fresh
    )
    common = {
        "last_completed_at": parse_utc(health.get("last_completed_at")),
        "last_symbols_processed": health.get("last_symbols_processed"),
        "current_run_number": health.get("current_run_number"),
        "current_symbols_attempted": health.get("current_symbols_attempted"),
        "current_symbol_count": health.get("current_symbol_count"),
        "current_results": health.get("current_results"),
        "current_failures": health.get("current_failures"),
        "progress_updated_at": progress_updated,
    }
    if scanning:
        success = parse_utc(health.get("last_success_at"))
        age = (
            max(0.0, (checked_at.astimezone(timezone.utc) - success).total_seconds() / 60)
            if success else None
        )
        return {
            **common, "state": "SCANNING", "market_data_state": "SCANNING",
            "last_success_at": success, "age_minutes": age,
            "message": "Scanner is actively processing the authoritative universe.",
        }
    if not health.get("last_success_at"):
        if health and health.get("last_error_at"):
            return {
                **common,
                "state": "ERROR",
                "market_data_state": health.get("market_data_state") or "ERROR",
                "last_success_at": None,
                "age_minutes": None,
                "message": "Scanner has not completed successfully. Latest scan failed.",
            }
        return {
            **common,
            "state": "WAITING",
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
        **common,
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
    target = targets.get(record.exit_reason)
    if target is not None:
        return target
    if (
        record.exit_reason in {"TIME_EXIT", "END_OF_DAY"}
        and record.entry
        and record.realized_return is not None
    ):
        multiplier = 1 + record.realized_return / 100
        if record.direction == "Bearish":
            multiplier = 1 - record.realized_return / 100
        return record.entry * multiplier
    return None


def _result_timestamp(result):
    value = (result or {}).get("last_candle_at") or (result or {}).get("timestamp")
    if value is None:
        return utc_now()
    parsed = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
