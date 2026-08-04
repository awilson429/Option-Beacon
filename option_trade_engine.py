"""Phase 1 paper-option contract capture and append-only persistence."""

from __future__ import annotations

import hashlib
import json
import logging
import math
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from signal_history import scanner_result_to_trade_outcome
from trade_evidence import scanner_entry_eligibility


LOGGER = logging.getLogger(__name__)
DEFAULT_LEDGER_FILE = "paper_option_trades.jsonl"


@dataclass(frozen=True)
class PaperOptionTrade:
    trade_id: str
    source_signal_id: str
    created_timestamp: datetime
    ticker: str
    direction: str
    underlying_entry_price: float | None
    confidence: float | None
    historical_grade: str | None
    scanner_score: float | None
    entry_reason: str
    expiration: str | None
    strike: float | None
    option_type: str | None
    option_symbol: str | None
    delta: float | None
    implied_volatility: float | None
    bid: float | None
    ask: float | None
    mid: float | None
    spread_percent: float | None
    open_interest: int | None
    volume: int | None
    source: str = "SCANNER"
    execution_type: str = "PAPER"
    status: str = "QUALIFIED"
    entry_snapshot_complete: bool = True
    data_unavailable_reason: str | None = None


class OptionTradeLedger:
    """Small append-only JSONL repository with durable duplicate lookup."""

    def __init__(self, path: str | Path = DEFAULT_LEDGER_FILE):
        self.path = Path(path)

    def records(self) -> list[PaperOptionTrade]:
        if not self.path.exists():
            return []
        records = []
        with self.path.open("r", encoding="utf-8") as ledger:
            for line_number, line in enumerate(ledger, start=1):
                if not line.strip():
                    continue
                try:
                    values = json.loads(line)
                    values["created_timestamp"] = _timestamp(
                        values["created_timestamp"]
                    )
                    records.append(PaperOptionTrade(**values))
                except Exception as exc:
                    LOGGER.warning(
                        "Skipping malformed option ledger row %s: %s",
                        line_number,
                        type(exc).__name__,
                    )
        return records

    def find_source_signal(self, source_signal_id: str) -> PaperOptionTrade | None:
        return next(
            (
                record
                for record in self.records()
                if record.source_signal_id == source_signal_id
            ),
            None,
        )

    def append_once(self, record: PaperOptionTrade) -> PaperOptionTrade:
        existing = self.find_source_signal(record.source_signal_id)
        if existing is not None:
            return existing
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(record)
        payload["created_timestamp"] = record.created_timestamp.isoformat()
        with self.path.open("a", encoding="utf-8") as ledger:
            ledger.write(json.dumps(payload, sort_keys=True) + "\n")
        return record


class TradierOptionChainProvider:
    """Adapter over the existing cached Tradier provider functions."""

    def expirations(self, ticker: str):
        from tradier_options import option_expirations

        return option_expirations(ticker)

    def chain(self, ticker: str, expiration: str):
        from tradier_options import option_chain

        return option_chain(ticker, expiration)


def source_signal_id(result: dict) -> str:
    """Reuse the existing stable signal identity with a deterministic fallback."""
    authoritative_id = str((result or {}).get("_authoritative_entry_id") or "").strip()
    if authoritative_id:
        return authoritative_id
    outcome = scanner_result_to_trade_outcome(result)
    if outcome is not None and outcome.trade_id:
        return outcome.trade_id
    plan = (result or {}).get("trade_plan") or {}
    identity = {
        "ticker": str((result or {}).get("symbol") or "").upper(),
        "direction": plan.get("direction") or (result or {}).get("bias"),
        "timestamp": str(
            (result or {}).get("last_candle_at")
            or (result or {}).get("timestamp")
            or ""
        ),
        "entry": plan.get("trigger_price")
        or plan.get("entry_price")
        or plan.get("entry_zone_low"),
        "setup": plan.get("setup_type")
        or plan.get("setup")
        or (result or {}).get("setup"),
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def preferred_expiration(
    expirations: Iterable[str],
    as_of: date,
) -> str | None:
    """Select the preferred listed Friday, then the next listed expiration."""
    listed = sorted(
        value
        for value in (_expiration_date(item) for item in expirations)
        if value is not None and value >= as_of
    )
    if not listed:
        return None
    days_to_friday = (4 - as_of.weekday()) % 7
    if as_of.weekday() >= 3:
        days_to_friday += 7
    preferred = as_of + timedelta(days=days_to_friday)
    if preferred in listed:
        return preferred.isoformat()
    fallback = next((item for item in listed if item >= preferred), listed[0])
    LOGGER.info(
        "Preferred expiration %s unavailable; using listed expiration %s",
        preferred,
        fallback,
    )
    return fallback.isoformat()


def normalized_contracts(
    contracts: Iterable[dict],
    option_type: str,
) -> list[dict]:
    """Normalize valid provider contracts without inventing missing values."""
    normalized = []
    for raw in contracts or []:
        if str(raw.get("option_type") or "").lower() != option_type:
            continue
        expiration = raw.get("expiration_date") or raw.get("expiration")
        strike = _positive(raw.get("strike"))
        ask = _positive(raw.get("ask"))
        bid = _nonnegative(raw.get("bid"))
        symbol = raw.get("symbol") or raw.get("option_symbol")
        if not expiration or strike is None or ask is None or not symbol:
            continue
        if bid is not None and bid > ask:
            continue
        mid = (bid + ask) / 2 if bid is not None else None
        spread = (
            (ask - bid) / mid * 100
            if bid is not None and mid is not None and mid > 0
            else None
        )
        greeks = raw.get("greeks") if isinstance(raw.get("greeks"), dict) else {}
        normalized.append(
            {
                "expiration": str(expiration),
                "strike": strike,
                "option_type": option_type,
                "option_symbol": str(symbol),
                "delta": _finite(raw.get("delta", greeks.get("delta"))),
                "implied_volatility": _finite(
                    raw.get(
                        "implied_volatility",
                        greeks.get("mid_iv", greeks.get("smv_vol")),
                    )
                ),
                "bid": bid,
                "ask": ask,
                "mid": mid,
                "spread_percent": spread,
                "open_interest": _whole(raw.get("open_interest")),
                "volume": _whole(raw.get("volume")),
            }
        )
    return normalized


def select_contract(
    contracts: Iterable[dict],
    *,
    option_type: str,
    underlying_price: float,
) -> dict | None:
    """Select exactly one valid contract using the deterministic policy."""
    valid = normalized_contracts(contracts, option_type)
    if not valid:
        return None
    has_delta = any(contract["delta"] is not None for contract in valid)

    def liquidity_key(contract):
        return (
            contract["spread_percent"]
            if contract["spread_percent"] is not None
            else math.inf,
            -(contract["open_interest"] or 0),
            -(contract["volume"] or 0),
            contract["strike"],
            contract["option_symbol"],
        )

    if has_delta:
        return min(
            valid,
            key=lambda contract: (
                abs(abs(contract["delta"]) - 0.50)
                if contract["delta"] is not None
                else math.inf,
                *liquidity_key(contract),
            ),
        )
    return min(
        valid,
        key=lambda contract: (
            abs(contract["strike"] - underlying_price),
            *liquidity_key(contract),
        ),
    )


def capture_qualified_signal(
    result: dict,
    *,
    repository: OptionTradeLedger | None = None,
    provider=None,
    history=None,
    now: datetime | None = None,
) -> PaperOptionTrade | None:
    """Capture one immutable contract snapshot for a qualified scanner signal."""
    if not (result or {}).get("_authoritative_entry_id"):
        eligibility = scanner_entry_eligibility(result)
        if not eligibility["eligible"]:
            return None

    repository = repository or OptionTradeLedger()
    provider = provider or TradierOptionChainProvider()
    signal_id = source_signal_id(result)
    existing = repository.find_source_signal(signal_id)
    if existing is not None:
        return existing

    created = now or _signal_timestamp(result)
    plan = result.get("trade_plan") or {}
    ticker = str(result.get("symbol") or "").upper()
    direction = plan.get("direction") or result.get("bias")
    option_type = {"Bullish": "call", "Bearish": "put"}.get(direction)
    underlying = _positive(result.get("price")) or _positive(
        plan.get("trigger_price")
        or plan.get("entry_price")
        or plan.get("entry_zone_low")
    )
    grade = _historical_grade(result, history)
    base = {
        "trade_id": hashlib.sha256(
            f"{signal_id}|PAPER_OPTION".encode("utf-8")
        ).hexdigest(),
        "source_signal_id": signal_id,
        "created_timestamp": created,
        "ticker": ticker,
        "direction": direction,
        "underlying_entry_price": underlying,
        "confidence": _finite(result.get("confidence")),
        "historical_grade": grade,
        "scanner_score": _finite(result.get("score")),
        "entry_reason": str(
            result.get("entry_timing_reason")
            or "Canonical scanner entry eligibility passed."
        ),
    }

    try:
        expirations, error = provider.expirations(ticker)
        if error:
            return repository.append_once(
                _unavailable(base, option_type, _safe_reason(error))
            )
        expiration = preferred_expiration(expirations, created.date())
        if expiration is None:
            return repository.append_once(
                _unavailable(base, option_type, "No listed expiration available.")
            )
        contracts, error = provider.chain(ticker, expiration)
        if error:
            return repository.append_once(
                _unavailable(base, option_type, _safe_reason(error))
            )
        selected = select_contract(
            contracts,
            option_type=option_type,
            underlying_price=underlying,
        )
        if selected is None:
            return repository.append_once(
                _unavailable(base, option_type, "No valid option contract available.")
            )
        return repository.append_once(PaperOptionTrade(**base, **selected))
    except Exception as exc:
        LOGGER.warning(
            "Option contract capture unavailable for %s: %s",
            ticker,
            type(exc).__name__,
        )
        return repository.append_once(
            _unavailable(base, option_type, "Option-chain provider unavailable.")
        )


def capture_qualified_signals(
    results: Iterable[dict],
    *,
    repository: OptionTradeLedger | None = None,
    provider=None,
    history=None,
) -> list[PaperOptionTrade]:
    """Capture all qualified results without allowing one failure to escape."""
    repository = repository or OptionTradeLedger()
    captured = []
    for result in results:
        try:
            record = capture_qualified_signal(
                result,
                repository=repository,
                provider=provider,
                history=history,
            )
            if record is not None:
                captured.append(record)
        except Exception:
            LOGGER.exception(
                "Could not capture option contract for %s",
                (result or {}).get("symbol", "unknown"),
            )
    return captured


def _unavailable(base: dict, option_type: str | None, reason: str):
    return PaperOptionTrade(
        **base,
        expiration=None,
        strike=None,
        option_type=option_type,
        option_symbol=None,
        delta=None,
        implied_volatility=None,
        bid=None,
        ask=None,
        mid=None,
        spread_percent=None,
        open_interest=None,
        volume=None,
        status="DATA_UNAVAILABLE",
        entry_snapshot_complete=False,
        data_unavailable_reason=reason,
    )


def _historical_grade(result: dict, history) -> str | None:
    explicit = result.get("historical_grade")
    if explicit:
        return str(explicit)
    if history is None:
        return None
    try:
        from setup_intelligence import setup_intelligence

        return setup_intelligence(result, history).get("historical_grade")
    except Exception:
        return None


def _safe_reason(value) -> str:
    text = str(value or "Option-chain data unavailable.")
    if "token" in text.lower() or "authorization" in text.lower():
        return "Option-chain credentials unavailable."
    return text[:240]


def _signal_timestamp(result: dict) -> datetime:
    value = result.get("last_candle_at") or result.get("timestamp")
    try:
        return _timestamp(value)
    except Exception:
        return datetime.now(timezone.utc)


def _timestamp(value) -> datetime:
    timestamp = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    )
    return (
        timestamp.replace(tzinfo=timezone.utc)
        if timestamp.tzinfo is None
        else timestamp
    )


def _expiration_date(value) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _finite(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _positive(value) -> float | None:
    number = _finite(value)
    return number if number is not None and number > 0 else None


def _nonnegative(value) -> float | None:
    number = _finite(value)
    return number if number is not None and number >= 0 else None


def _whole(value) -> int | None:
    number = _finite(value)
    return int(number) if number is not None and number >= 0 else None
