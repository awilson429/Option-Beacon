"""Pure open-trade quote-watchlist and price-map enrichment helpers."""

from __future__ import annotations

import logging
import math
from collections.abc import Callable, Iterable

from signal_history import TradeOutcome


LOGGER = logging.getLogger(__name__)


def _valid_price(value) -> float | None:
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return price if math.isfinite(price) and price > 0 else None


def open_trade_symbols(records: Iterable[TradeOutcome]) -> set[str]:
    """Return unique symbols for entered outcomes that have not closed."""
    return {
        str(record.symbol).upper()
        for record in records
        if record.entry_time is not None
        and record.exit_time is None
        and record.symbol
    }


def scanner_price_map(latest_results: dict) -> dict[str, float]:
    """Extract valid prices already obtained during the scanner refresh."""
    prices = {}
    for symbol, result in (latest_results or {}).items():
        price = _valid_price((result or {}).get("price"))
        if price is not None:
            prices[str(symbol).upper()] = price
    return prices


def enrich_open_trade_prices(
    records: Iterable[TradeOutcome],
    latest_results: dict,
    quote_fetcher: Callable[[str], tuple[object, str]],
) -> tuple[dict[str, float], dict[str, str]]:
    """Fetch each missing open symbol once and merge successful prices."""
    prices = scanner_price_map(latest_results)
    quote_status = {}
    missing_symbols = sorted(open_trade_symbols(records) - prices.keys())

    for symbol in missing_symbols:
        try:
            quote, provider_result = quote_fetcher(symbol)
            quote_price = (
                _valid_price(quote.get("price"))
                if isinstance(quote, dict)
                else _valid_price(quote)
            )
            if quote_price is not None:
                prices[symbol] = quote_price
                continue
            detail = str(provider_result or "no quote returned")
        except Exception as exc:
            detail = str(exc) or exc.__class__.__name__
        quote_status[symbol] = "Live quote unavailable"
        LOGGER.warning("Live quote unavailable for %s: %s", symbol, detail)

    return prices, quote_status
