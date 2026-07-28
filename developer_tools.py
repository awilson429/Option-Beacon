"""Sanitized diagnostics for the internal OptionBeacon Developer Tools page."""

from __future__ import annotations

import importlib.util
import json
import logging
import math
import time
import tempfile
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

from finnhub_universe import finnhub_api_key, quote_symbol
from option_trade_engine import (
    DEFAULT_LEDGER_FILE,
    OptionTradeLedger,
    PaperOptionTrade,
    TradierOptionChainProvider,
)
from option_position_tracker import (
    OptionPositionStore,
    TradierOptionQuoteProvider,
    refresh_option_positions,
    update_position,
)
from tradier_options import tradier_configured
from verify_option_engine import run_verification


LOGGER = logging.getLogger(__name__)
DEFAULT_DIAGNOSTICS_FILE = "runtime_diagnostics.json"
UNAVAILABLE = "—"
HOSTED_SECRET_NAMES = (
    "APP_ACCESS_CODE",
    "TRADIER_ACCESS_TOKEN",
    "FINNHUB_API_KEY",
)


def hosted_configuration_status() -> dict:
    """Return hosted-secret readiness without exposing configured values."""
    configured = {
        "APP_ACCESS_CODE": _configured_secret("APP_ACCESS_CODE"),
        "TRADIER_ACCESS_TOKEN": tradier_configured(),
        "FINNHUB_API_KEY": bool(finnhub_api_key()),
    }
    missing = [name for name in HOSTED_SECRET_NAMES if not configured[name]]
    return {
        "ready": not missing,
        "missing": missing,
        "statuses": {
            name: "Configured" if configured[name] else "Not configured"
            for name in HOSTED_SECRET_NAMES
        },
    }


def system_status(root: str | Path = ".") -> list[dict]:
    root = Path(root)
    return [
        _status("Tradier access token configured", tradier_configured(), "Configured", "Not configured"),
        _status("Finnhub API key configured", bool(finnhub_api_key()), "Configured", "Not configured"),
        _status("Streamlit secrets available", _streamlit_secrets_available(), "Available", "Unavailable"),
        _status("Tradier provider import available", _import_available("tradier_options"), "Available", "Unavailable"),
        _status("Finnhub provider import available", _import_available("finnhub_universe"), "Available", "Unavailable"),
        _status("Production option ledger present", (root / DEFAULT_LEDGER_FILE).exists(), "File present", "File not present"),
        _status("Signal history present", (root / "signal_history.jsonl").exists(), "File present", "File not present"),
    ]


def verify_tradier_connection(provider=None, now=None) -> dict:
    started = time.perf_counter()
    checked_at = now or datetime.now(timezone.utc)
    provider = provider or TradierOptionChainProvider()
    credential = tradier_configured()
    connection = False
    valid = False
    count = 0
    message = ""
    try:
        expirations, error = provider.expirations("SPY")
        if error:
            message = sanitize_error(error)
        else:
            connection = True
            count = len(expirations or [])
            valid = count > 0 and all(_valid_expiration(item) for item in expirations)
            if not valid:
                message = "malformed response"
    except Exception:
        LOGGER.exception("Tradier diagnostic request failed")
        message = "unexpected internal error"
    result = {
        "validation_type": "Tradier Connection",
        "timestamp": checked_at.isoformat(),
        "provider_mode": "LIVE",
        "overall_result": "PASS" if credential and connection and valid else "FAIL",
        "checks": [
            _check(
                "credential loader resolved a token",
                credential,
                "credential unavailable",
            ),
            _check(
                "provider connection",
                connection,
                message or "provider unavailable",
            ),
            _check(
                "SPY option expirations returned",
                valid,
                message or "malformed response",
            ),
        ],
        "message": message,
        "expiration_count": count,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "contract": None,
    }
    return result


def verify_finnhub_connection(quote_provider=quote_symbol, now=None) -> dict:
    started = time.perf_counter()
    checked_at = now or datetime.now(timezone.utc)
    api_key = finnhub_api_key()
    configured = bool(api_key)
    connection = False
    valid = False
    message = ""
    try:
        if not configured:
            message = "credential unavailable"
        else:
            quote = quote_provider("SPY", api_key)
            connection = quote is not None
            valid = _positive((quote or {}).get("price")) is not None
            if connection and not valid:
                message = "malformed response"
    except Exception:
        LOGGER.exception("Finnhub diagnostic request failed")
        message = "provider unavailable"
    return {
        "validation_type": "Finnhub Connection",
        "timestamp": checked_at.isoformat(),
        "provider_mode": "LIVE",
        "overall_result": "PASS" if configured and connection and valid else "FAIL",
        "checks": [
            _check(
                "Finnhub credential configured",
                configured,
                "credential unavailable",
            ),
            _check(
                "provider connection",
                connection,
                message or "provider unavailable",
            ),
            _check(
                "valid SPY response",
                valid,
                message or "malformed response",
            ),
        ],
        "message": message,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "contract": None,
    }


def option_engine_diagnostic(
    now=None,
    protected_root=".",
    verifier=run_verification,
) -> dict:
    started = time.perf_counter()
    checked_at = now or datetime.now(timezone.utc)
    mode, checks, record = verifier(
        now=checked_at,
        protected_root=protected_root,
    )
    display_checks = []
    for check in checks:
        status = "PASS" if check.passed else "FAIL"
        if (
            mode == "MOCK PROVIDER VALIDATION"
            and check.name in {"Tradier credentials found", "provider connection succeeded"}
            and not check.passed
        ):
            status = "WARNING"
        display_checks.append(
            _normalized_check(check.name, status, check.detail)
        )
    overall = (
        "PASS"
        if all(item["status"] in {"PASS", "WARNING"} for item in display_checks)
        else "FAIL"
    )
    return {
        "validation_type": "Option Engine Verification",
        "timestamp": checked_at.isoformat(),
        "provider_mode": mode,
        "overall_result": overall,
        "checks": display_checks,
        "message": (
            "Live provider validation was not completed."
            if mode == "MOCK PROVIDER VALIDATION"
            else ""
        ),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "contract": contract_summary(record),
    }


def verify_position_tracking(now=None, provider=None) -> dict:
    """Exercise position tracking against temporary persistence only."""
    checked_at = now or datetime.now(timezone.utc)
    started = time.perf_counter()
    source_trades = [
        trade
        for trade in OptionTradeLedger().records()
        if trade.status == "QUALIFIED" and trade.mid and trade.option_symbol
    ]
    trade = source_trades[-1] if source_trades else _diagnostic_trade(checked_at)
    provider_mode = "LIVE" if source_trades and provider is None else "MOCK"
    provider = provider or (
        TradierOptionQuoteProvider()
        if source_trades
        else _DiagnosticQuoteProvider(trade.mid)
    )
    checks = []
    try:
        with tempfile.TemporaryDirectory(prefix="position-tracking-verify-") as directory:
            ledger = OptionTradeLedger(Path(directory) / "trades.jsonl")
            store = OptionPositionStore(Path(directory) / "positions.json")
            ledger.append_once(trade)
            positions = refresh_option_positions(
                position_store=store,
                trade_ledger=ledger,
                provider=provider,
                current_time=checked_at,
                profit_target_percent=500,
                stop_loss_percent=-99,
            )
            position = positions[0] if positions else None
            checks.extend(
                [
                    _check("position file readable", bool(store.load())),
                    _check(
                        "live quote retrieval",
                        position is not None
                        and position.last_option_quote_time == checked_at,
                        "provider unavailable",
                    ),
                    _check(
                        "return calculation",
                        position is not None
                        and position.current_return_percent > 0,
                    ),
                    _check(
                        "MFE update",
                        position is not None
                        and position.max_favorable_excursion_percent > 0,
                    ),
                ]
            )
            adverse = (
                update_position(
                    position,
                    {"bid": trade.mid * 0.7, "ask": trade.mid * 0.9},
                    current_time=checked_at,
                    profit_target_percent=500,
                    stop_loss_percent=-99,
                )
                if position is not None
                else None
            )
            checks.append(
                _check(
                    "MAE update",
                    adverse is not None
                    and adverse.max_adverse_excursion_percent < 0,
                )
            )
            expired_source = (
                adverse
                if adverse is not None
                else position
            )
            expired = (
                update_position(
                    replace(expired_source, expiration="2020-01-01"),
                    None,
                    current_time=checked_at,
                )
                if expired_source is not None
                else None
            )
            checks.append(
                _check(
                    "expiration handling",
                    expired is not None and expired.status == "EXPIRED",
                )
            )
            frozen = (
                update_position(expired, {"bid": 99, "ask": 100}, current_time=checked_at)
                if expired is not None
                else None
            )
            checks.append(
                _check(
                    "closed-position handling",
                    expired is not None and frozen == expired,
                )
            )
    except Exception:
        LOGGER.exception("Position tracking diagnostic failed")
        checks = [_normalized_check("position tracking", "FAIL", "verification failed")]
    overall = "PASS" if checks and all(check["status"] == "PASS" for check in checks) else "FAIL"
    return {
        "validation_type": "Position Tracking",
        "timestamp": checked_at.isoformat(),
        "provider_mode": provider_mode,
        "overall_result": overall,
        "checks": checks,
        "message": "",
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "contract": None,
    }


def save_diagnostic_result(result: dict, path: str | Path = DEFAULT_DIAGNOSTICS_FILE) -> Path:
    path = Path(path)
    sanitized = sanitize_diagnostic_result(result)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(sanitized, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)
    return path


def load_latest_diagnostic(path: str | Path = DEFAULT_DIAGNOSTICS_FILE) -> dict | None:
    path = Path(path)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return sanitize_diagnostic_result(value) if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError, TypeError):
        LOGGER.warning("Could not load latest sanitized diagnostic result")
        return None


def latest_production_ledger_entry(path: str | Path = DEFAULT_LEDGER_FILE) -> dict | None:
    records = OptionTradeLedger(path).records()
    return contract_summary(records[-1], include_timestamp=True) if records else None


def contract_summary(record, *, include_timestamp=False) -> dict | None:
    if record is None:
        return None
    summary = {
        "ticker": record.ticker,
        "direction": record.direction,
        "option_type": record.option_type,
        "expiration": record.expiration,
        "strike": record.strike,
        "option_symbol": record.option_symbol,
        "delta": record.delta,
        "implied_volatility": record.implied_volatility,
        "bid": record.bid,
        "ask": record.ask,
        "mid": record.mid,
        "spread_percent": record.spread_percent,
        "open_interest": record.open_interest,
        "volume": record.volume,
        "status": record.status,
    }
    if include_timestamp:
        summary = {"captured_timestamp": record.created_timestamp.isoformat(), **summary}
    return summary


class _DiagnosticQuoteProvider:
    def __init__(self, entry_mid):
        self.entry_mid = float(entry_mid)

    def quote(self, option_symbol):
        return {
            "symbol": option_symbol,
            "bid": self.entry_mid * 1.08,
            "ask": self.entry_mid * 1.12,
        }, ""


def _diagnostic_trade(now):
    return PaperOptionTrade(
        trade_id="position-tracking-diagnostic",
        source_signal_id="position-tracking-diagnostic",
        created_timestamp=now,
        ticker="SPY",
        direction="Bullish",
        underlying_entry_price=500,
        confidence=80,
        historical_grade=None,
        scanner_score=80,
        entry_reason="Temporary position tracking diagnostic.",
        expiration="2099-12-31",
        strike=500,
        option_type="call",
        option_symbol="SPY_DIAGNOSTIC_CALL",
        delta=0.50,
        implied_volatility=0.25,
        bid=4.9,
        ask=5.1,
        mid=5.0,
        spread_percent=4.0,
        open_interest=1000,
        volume=500,
    )


def sanitize_diagnostic_result(result: dict) -> dict:
    checks = []
    for check in list(result.get("checks") or []):
        if hasattr(check, "__dataclass_fields__"):
            check = asdict(check)
        checks.append(
            _normalized_check(
                str(check.get("name") or "Unnamed check")[:120],
                _check_status(check),
                check.get("message") or check.get("detail"),
            )
        )
    contract = result.get("contract")
    allowed_contract = None
    if isinstance(contract, dict):
        fields = {
            "captured_timestamp", "ticker", "direction", "option_type",
            "expiration", "strike", "option_symbol", "delta",
            "implied_volatility", "bid", "ask", "mid", "spread_percent",
            "open_interest", "volume", "status",
        }
        allowed_contract = {
            key: value for key, value in contract.items() if key in fields
        }
    return {
        "validation_type": str(result.get("validation_type") or "Diagnostic")[:80],
        "timestamp": str(result.get("timestamp") or "")[:50],
        "provider_mode": str(result.get("provider_mode") or "NOT RUN")[:40],
        "overall_result": str(result.get("overall_result") or "NOT RUN")[:20],
        "checks": checks,
        "message": sanitize_message(result.get("message")),
        "contract": allowed_contract,
        "elapsed_seconds": _finite(result.get("elapsed_seconds")),
        **(
            {"expiration_count": int(result.get("expiration_count") or 0)}
            if "expiration_count" in result
            else {}
        ),
    }


def sanitize_error(value) -> str:
    text = str(value or "").lower()
    if any(word in text for word in ("token", "credential", "authorization", "401", "403")):
        return "credential unavailable" if "configured" in text else "request rejected"
    if "malformed" in text or "decode" in text:
        return "malformed response"
    return "provider unavailable"


def sanitize_message(value) -> str:
    if not value:
        return ""
    text = str(value)
    lowered = text.lower()
    if any(
        word in lowered
        for word in ("bearer ", "authorization:", "api_key", "token", "secret")
    ):
        return sanitize_error(text)
    return text[:240]


def _streamlit_secrets_available() -> bool:
    try:
        import streamlit as st

        return bool(st.secrets)
    except Exception:
        return False


def _configured_secret(name: str) -> bool:
    import os

    if os.getenv(name):
        return True
    try:
        import streamlit as st

        return bool(st.secrets.get(name))
    except Exception:
        return False


def _import_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _status(name, available, true_label, false_label):
    return {"name": name, "status": true_label if available else false_label}


def _check(name, passed, failure_message="verification failed"):
    return _normalized_check(
        name,
        "PASS" if passed else "FAIL",
        "" if passed else failure_message,
    )


def _normalized_check(name, status, message=""):
    normalized_status = str(status or "NOT RUN").upper()
    if normalized_status not in {"PASS", "FAIL", "WARNING", "NOT RUN"}:
        normalized_status = "NOT RUN"
    if normalized_status == "PASS":
        normalized_message = ""
    else:
        normalized_message = sanitize_message(message)
        if normalized_status == "FAIL" and not normalized_message:
            normalized_message = "verification failed"
    return {
        "name": str(name or "Unnamed check")[:120],
        "status": normalized_status,
        "message": normalized_message,
    }


def _check_status(check):
    status = str(check.get("status") or "").upper()
    if status in {"PASS", "FAIL", "WARNING", "NOT RUN"}:
        return status
    if "passed" in check:
        return "PASS" if check["passed"] else "FAIL"
    return "NOT RUN"


def _valid_expiration(value) -> bool:
    try:
        datetime.fromisoformat(str(value))
        return True
    except (TypeError, ValueError):
        return False


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _positive(value):
    number = _finite(value)
    return number if number is not None and number > 0 else None
