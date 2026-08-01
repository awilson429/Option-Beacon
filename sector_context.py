"""Deterministic sector mapping and relative-strength context."""

from __future__ import annotations

import math
from datetime import datetime, timezone

from intelligence_models import SectorContextSnapshot


SECTOR_BENCHMARKS = {
    "Technology": "XLK", "Financials": "XLF", "Energy": "XLE",
    "Health Care": "XLV", "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP", "Industrials": "XLI", "Utilities": "XLU",
    "Real Estate": "XLRE", "Materials": "XLB", "Communication Services": "XLC",
}
SYMBOL_SECTORS = {
    "AAPL": "Technology", "MSFT": "Technology", "NVDA": "Technology",
    "AMD": "Technology", "META": "Communication Services",
    "GOOGL": "Communication Services", "AMZN": "Consumer Discretionary",
    "TSLA": "Consumer Discretionary", "JPM": "Financials", "BAC": "Financials",
    "XOM": "Energy", "CVX": "Energy", "LLY": "Health Care", "UNH": "Health Care",
}


def sector_for_symbol(symbol: str) -> tuple[str, str | None]:
    upper = str(symbol or "").upper()
    sector = SYMBOL_SECTORS.get(upper)
    if not sector and upper in SECTOR_BENCHMARKS.values():
        sector = next(name for name, etf in SECTOR_BENCHMARKS.items() if etf == upper)
    return (sector or "UNKNOWN", SECTOR_BENCHMARKS.get(sector))


def build_sector_context(
    symbol: str,
    direction: str,
    *,
    symbol_return=None,
    sector_return=None,
    sector_rank=None,
    timestamp=None,
) -> SectorContextSnapshot:
    at = timestamp or datetime.now(timezone.utc)
    sector, benchmark = sector_for_symbol(symbol)
    sym, bench = _number(symbol_return), _number(sector_return)
    if sector == "UNKNOWN" or bench is None:
        return SectorContextSnapshot(sector, benchmark, None, "UNKNOWN", None, "UNKNOWN", ("SECTOR_MAPPING_UNAVAILABLE",), at)
    if sym is None or bench is None:
        return SectorContextSnapshot(sector, benchmark, sector_rank, "UNKNOWN", None, "UNKNOWN", ("SECTOR_MARKET_DATA_UNAVAILABLE",), at)
    sector_trend = "BULLISH" if bench > 0 else "BEARISH" if bench < 0 else "FLAT"
    desired = "BULLISH" if str(direction).lower().startswith("bull") else "BEARISH"
    aligned = desired == sector_trend
    relative = round(sym - bench, 6)
    if not aligned:
        status = "CONTRADICTING"
    elif relative > 0:
        status = "OUTPERFORMING"
    elif relative < 0:
        status = "UNDERPERFORMING"
    else:
        status = "ALIGNED"
    return SectorContextSnapshot(sector, benchmark, sector_rank, sector_trend, relative, status, (f"SECTOR_{sector_trend}", f"SYMBOL_{status}"), at)


def rank_sector_returns(returns: dict[str, float]) -> dict[str, int]:
    valid = [(str(key), value) for key, raw in returns.items() if (value := _number(raw)) is not None]
    return {key: rank for rank, (key, _value) in enumerate(sorted(valid, key=lambda item: (-item[1], item[0])), 1)}


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
