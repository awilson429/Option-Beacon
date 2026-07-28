"""Live lifecycle tracking for immutable paper option contract captures."""

from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable

from option_trade_engine import (
    DEFAULT_LEDGER_FILE,
    OptionTradeLedger,
    PaperOptionTrade,
)


LOGGER = logging.getLogger(__name__)
DEFAULT_POSITION_FILE = "paper_option_positions.json"
DEFAULT_PROFIT_TARGET_PERCENT = 50.0
DEFAULT_STOP_LOSS_PERCENT = -30.0


@dataclass(frozen=True)
class PaperOptionPosition:
    trade_id: str
    status: str
    entry_time: datetime
    last_update: datetime
    ticker: str
    direction: str
    option_symbol: str
    expiration: str
    strike: float
    option_type: str
    entry_bid: float | None
    entry_ask: float | None
    entry_mid: float
    current_bid: float | None
    current_ask: float | None
    current_mid: float
    current_return_percent: float
    highest_mid: float
    lowest_mid: float
    max_favorable_excursion_percent: float
    max_adverse_excursion_percent: float
    last_underlying_price: float | None
    last_option_quote_time: datetime | None
    exit_time: datetime | None = None
    exit_reason: str | None = None
    exit_bid: float | None = None
    exit_ask: float | None = None
    exit_mid: float | None = None
    exit_return_percent: float | None = None


class OptionPositionStore:
    """Atomic JSON repository for mutable paper-option lifecycle state."""

    def __init__(self, path: str | Path = DEFAULT_POSITION_FILE):
        self.path = Path(path)

    def load(self) -> list[PaperOptionPosition]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            rows = payload.get("positions", []) if isinstance(payload, dict) else []
            return [_deserialize(row) for row in rows if isinstance(row, dict)]
        except Exception:
            LOGGER.exception("Could not read paper option position store")
            return []

    def save(self, positions: Iterable[PaperOptionPosition]) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        payload = {
            "positions": [_serialize(position) for position in positions],
        }
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(self.path)
        return self.path


class TradierOptionQuoteProvider:
    """Adapter over the existing Tradier quote request path."""

    def quote(self, option_symbol: str):
        from tradier_options import option_quote

        return option_quote(option_symbol)


def position_from_trade(trade: PaperOptionTrade) -> PaperOptionPosition | None:
    """Create an OPEN lifecycle record without changing the capture snapshot."""
    if (
        trade.status != "QUALIFIED"
        or not trade.entry_snapshot_complete
        or not trade.option_symbol
        or not trade.expiration
        or trade.strike is None
    ):
        return None
    entry_mid = _positive(trade.mid)
    if entry_mid is None:
        return None
    return PaperOptionPosition(
        trade_id=trade.trade_id,
        status="OPEN",
        entry_time=trade.created_timestamp,
        last_update=trade.created_timestamp,
        ticker=trade.ticker,
        direction=trade.direction,
        option_symbol=trade.option_symbol,
        expiration=trade.expiration,
        strike=float(trade.strike),
        option_type=trade.option_type or "",
        entry_bid=_finite(trade.bid),
        entry_ask=_finite(trade.ask),
        entry_mid=entry_mid,
        current_bid=_finite(trade.bid),
        current_ask=_finite(trade.ask),
        current_mid=entry_mid,
        current_return_percent=0.0,
        highest_mid=entry_mid,
        lowest_mid=entry_mid,
        max_favorable_excursion_percent=0.0,
        max_adverse_excursion_percent=0.0,
        last_underlying_price=_finite(trade.underlying_entry_price),
        last_option_quote_time=trade.created_timestamp,
    )


def synchronize_captures(
    positions: Iterable[PaperOptionPosition],
    trades: Iterable[PaperOptionTrade],
) -> list[PaperOptionPosition]:
    """Add one lifecycle row per valid immutable capture."""
    result = list(positions)
    existing = {position.trade_id for position in result}
    for trade in trades:
        if trade.trade_id in existing:
            continue
        position = position_from_trade(trade)
        if position is not None:
            result.append(position)
            existing.add(trade.trade_id)
    return result


def option_return_percent(entry_mid, current_mid) -> float | None:
    entry = _positive(entry_mid)
    current = _positive(current_mid)
    if entry is None or current is None:
        return None
    return (current - entry) / entry * 100


def update_position(
    position: PaperOptionPosition,
    quote: dict | None,
    *,
    current_time: datetime,
    profit_target_percent: float = DEFAULT_PROFIT_TARGET_PERCENT,
    stop_loss_percent: float = DEFAULT_STOP_LOSS_PERCENT,
) -> PaperOptionPosition:
    """Advance one OPEN position from a current option quote."""
    if position.status != "OPEN":
        return position
    expiration = _date(position.expiration)
    if expiration is not None and current_time.date() > expiration:
        return _close_position(
            position,
            current_time=current_time,
            reason="EXPIRATION",
            status="EXPIRED",
        )
    normalized = normalize_live_quote(quote)
    if normalized is None:
        return position
    current_mid = normalized["mid"]
    current_return = option_return_percent(position.entry_mid, current_mid)
    if current_return is None:
        return position
    highest = max(position.highest_mid, current_mid)
    lowest = min(position.lowest_mid, current_mid)
    mfe = max(
        position.max_favorable_excursion_percent,
        option_return_percent(position.entry_mid, highest) or 0.0,
    )
    mae = min(
        position.max_adverse_excursion_percent,
        option_return_percent(position.entry_mid, lowest) or 0.0,
    )
    updated = replace(
        position,
        last_update=current_time,
        current_bid=normalized["bid"],
        current_ask=normalized["ask"],
        current_mid=current_mid,
        current_return_percent=current_return,
        highest_mid=highest,
        lowest_mid=lowest,
        max_favorable_excursion_percent=mfe,
        max_adverse_excursion_percent=mae,
        last_underlying_price=normalized["underlying_price"],
        last_option_quote_time=current_time,
    )
    if current_return >= profit_target_percent:
        return _close_position(
            updated,
            current_time=current_time,
            reason="PROFIT_TARGET",
            status="CLOSED",
        )
    if current_return <= stop_loss_percent:
        return _close_position(
            updated,
            current_time=current_time,
            reason="STOP_LOSS",
            status="CLOSED",
        )
    return updated


def refresh_option_positions(
    *,
    position_store: OptionPositionStore | None = None,
    trade_ledger: OptionTradeLedger | None = None,
    provider=None,
    current_time: datetime | None = None,
    profit_target_percent: float = DEFAULT_PROFIT_TARGET_PERCENT,
    stop_loss_percent: float = DEFAULT_STOP_LOSS_PERCENT,
) -> list[PaperOptionPosition]:
    """Synchronize captures and quote only OPEN option symbols."""
    position_store = position_store or OptionPositionStore()
    trade_ledger = trade_ledger or OptionTradeLedger(DEFAULT_LEDGER_FILE)
    provider = provider or TradierOptionQuoteProvider()
    checked_at = current_time or datetime.now(timezone.utc)
    positions = synchronize_captures(position_store.load(), trade_ledger.records())
    quote_cache: dict[str, dict | None] = {}
    updated = []
    for position in positions:
        if position.status != "OPEN":
            updated.append(position)
            continue
        expiration = _date(position.expiration)
        if expiration is not None and checked_at.date() > expiration:
            updated.append(
                update_position(position, None, current_time=checked_at)
            )
            continue
        if position.option_symbol not in quote_cache:
            try:
                quote, error = provider.quote(position.option_symbol)
                if error:
                    LOGGER.warning(
                        "Option quote unavailable for %s: %s",
                        position.option_symbol,
                        _safe_error(error),
                    )
                    quote = None
                quote_cache[position.option_symbol] = quote
            except Exception as exc:
                LOGGER.warning(
                    "Option quote unavailable for %s: %s",
                    position.option_symbol,
                    type(exc).__name__,
                )
                quote_cache[position.option_symbol] = None
        updated.append(
            update_position(
                position,
                quote_cache[position.option_symbol],
                current_time=checked_at,
                profit_target_percent=profit_target_percent,
                stop_loss_percent=stop_loss_percent,
            )
        )
    position_store.save(updated)
    return updated


def refresh_option_positions_safely(**kwargs) -> list[PaperOptionPosition]:
    try:
        return refresh_option_positions(**kwargs)
    except Exception:
        LOGGER.exception("Could not refresh paper option positions")
        return []


def normalize_live_quote(quote) -> dict | None:
    if not isinstance(quote, dict):
        return None
    bid = _nonnegative(quote.get("bid"))
    ask = _positive(quote.get("ask"))
    if bid is None or ask is None or bid > ask:
        return None
    mid = (bid + ask) / 2
    if mid <= 0:
        return None
    return {
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "underlying_price": _finite(
            quote.get("underlying_price") or quote.get("underlying")
        ),
    }


def open_position_rows(positions, now=None) -> list[dict]:
    checked_at = now or datetime.now(timezone.utc)
    rows = []
    for position in positions:
        if position.status != "OPEN":
            continue
        rows.append(
            {
                "Ticker": position.ticker,
                "Direction": position.direction,
                "Strike": f"${position.strike:.2f}",
                "Expiration": position.expiration,
                "Current Return": _percent(position.current_return_percent),
                "MFE": _percent(position.max_favorable_excursion_percent),
                "MAE": _percent(position.max_adverse_excursion_percent),
                "Status": position.status,
                "Age": _duration(position.entry_time, checked_at),
            }
        )
    return sorted(rows, key=lambda row: row["Age"])


def completed_position_rows(positions) -> list[dict]:
    closed = [
        position
        for position in positions
        if position.status in {"CLOSED", "EXPIRED"}
    ]
    closed.sort(
        key=lambda position: position.exit_time or position.last_update,
        reverse=True,
    )
    return [
        {
            "Ticker": position.ticker,
            "Direction": position.direction,
            "Contract": position.option_symbol,
            "Entry": _money(position.entry_mid),
            "Exit": _money(position.exit_mid),
            "Return": _percent(position.exit_return_percent),
            "Reason": position.exit_reason or "—",
            "Duration": _duration(
                position.entry_time,
                position.exit_time or position.last_update,
            ),
            "Status": position.status,
        }
        for position in closed
    ]


def _close_position(position, *, current_time, reason, status):
    return replace(
        position,
        status=status,
        last_update=current_time,
        exit_time=current_time,
        exit_reason=reason,
        exit_bid=position.current_bid,
        exit_ask=position.current_ask,
        exit_mid=position.current_mid,
        exit_return_percent=position.current_return_percent,
    )


def _serialize(position):
    values = asdict(position)
    for field in ("entry_time", "last_update", "last_option_quote_time", "exit_time"):
        value = values[field]
        values[field] = value.isoformat() if value is not None else None
    return values


def _deserialize(values):
    values = dict(values)
    for field in ("entry_time", "last_update", "last_option_quote_time", "exit_time"):
        values[field] = _datetime(values.get(field)) if values.get(field) else None
    return PaperOptionPosition(**values)


def _datetime(value):
    timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return timestamp.replace(tzinfo=timezone.utc) if timestamp.tzinfo is None else timestamp


def _date(value):
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _positive(value):
    number = _finite(value)
    return number if number is not None and number > 0 else None


def _nonnegative(value):
    number = _finite(value)
    return number if number is not None and number >= 0 else None


def _percent(value):
    number = _finite(value)
    if number is None:
        return "—"
    return f"{number:+.2f}%" if number != 0 else "0.00%"


def _money(value):
    number = _finite(value)
    return f"${number:.2f}" if number is not None else "—"


def _duration(start, end):
    minutes = max(0, int((end - start).total_seconds() / 60))
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m" if hours else f"{minutes}m"


def _safe_error(value):
    text = str(value or "").lower()
    if "rate" in text or "429" in text:
        return "rate limited"
    if "market" in text and "closed" in text:
        return "market closed"
    if "expired" in text:
        return "expired contract"
    return "provider unavailable"
