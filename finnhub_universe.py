import json
import os
import time
from datetime import datetime
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


DEFAULT_ETF_SYMBOLS = ["SPY", "QQQ", "IWM", "DIA"]
DEFAULT_STOCK_SYMBOLS = ["NVDA", "TSLA", "AAPL", "AMD"]
DEFAULT_SYMBOL_GROUPS = {
    "ETF Scanner": DEFAULT_ETF_SYMBOLS,
    "Single Stock Scanner": DEFAULT_STOCK_SYMBOLS,
}

DEFAULT_TOP_MOVER_COUNT = 30
MAX_TOP_MOVER_COUNT = 50
FINNHUB_BASE_URL = "https://finnhub.io/api/v1"
FINNHUB_UNIVERSE_CACHE_FILE = "finnhub_movers_cache.json"

LIQUID_OPTIONS_CANDIDATES = [
    "AAPL",
    "ABBV",
    "ABNB",
    "AMD",
    "AMZN",
    "ARKK",
    "AVGO",
    "BA",
    "BAC",
    "BABA",
    "BIDU",
    "BMY",
    "C",
    "CAT",
    "COIN",
    "CRM",
    "CVX",
    "DIA",
    "DIS",
    "DKNG",
    "F",
    "FDX",
    "GLD",
    "GOOGL",
    "GS",
    "HD",
    "INTC",
    "IWM",
    "JPM",
    "KO",
    "LLY",
    "META",
    "MRK",
    "MS",
    "MSFT",
    "MSTR",
    "MU",
    "NFLX",
    "NKE",
    "NVDA",
    "ORCL",
    "PEP",
    "PFE",
    "PLTR",
    "PYPL",
    "QCOM",
    "QQQ",
    "RIVN",
    "ROKU",
    "SHOP",
    "SLV",
    "SMCI",
    "SNOW",
    "SOFI",
    "SPY",
    "T",
    "TLT",
    "TSLA",
    "UBER",
    "UNH",
    "USO",
    "V",
    "WMT",
    "XLE",
    "XLF",
    "XLI",
    "XLK",
    "XLP",
    "XLU",
    "XLV",
    "XLY",
    "XOM",
]


def finnhub_api_key():
    return os.getenv("FINNHUB_API_KEY", "").strip()


def top_mover_count():
    try:
        requested_count = int(os.getenv("OPTION_BEACON_TOP_MOVER_COUNT", DEFAULT_TOP_MOVER_COUNT))
    except (TypeError, ValueError):
        return DEFAULT_TOP_MOVER_COUNT

    return max(10, min(requested_count, MAX_TOP_MOVER_COUNT))


def candidate_symbols():
    custom_symbols = os.getenv("OPTION_BEACON_SYMBOLS", "").strip()
    if custom_symbols:
        symbols = [symbol.strip().upper() for symbol in custom_symbols.split(",")]
        return sorted({symbol for symbol in symbols if symbol})

    return LIQUID_OPTIONS_CANDIDATES


def _request_json(path, params, api_key):
    query = urlencode({**params, "token": api_key})
    request = Request(f"{FINNHUB_BASE_URL}{path}?{query}", headers={"User-Agent": "OptionBeacon/1.0"})
    with urlopen(request, timeout=8) as response:
        return json.loads(response.read().decode("utf-8"))


def today_label():
    return datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")


def load_cached_movers():
    if not os.path.exists(FINNHUB_UNIVERSE_CACHE_FILE):
        return None

    try:
        with open(FINNHUB_UNIVERSE_CACHE_FILE, "r", encoding="utf-8") as cache_file:
            cache = json.load(cache_file)
    except (OSError, json.JSONDecodeError):
        return None

    if cache.get("date") != today_label():
        return None

    movers = cache.get("movers")
    if not isinstance(movers, dict):
        return None

    if not movers.get("bullish") or not movers.get("bearish"):
        return None

    return movers


def save_cached_movers(movers):
    payload = {
        "date": today_label(),
        "source": "Finnhub daily movers",
        "movers": movers,
    }

    try:
        with open(FINNHUB_UNIVERSE_CACHE_FILE, "w", encoding="utf-8") as cache_file:
            json.dump(payload, cache_file, indent=2)
    except OSError:
        pass


def quote_symbol(symbol, api_key):
    data = _request_json("/quote", {"symbol": symbol}, api_key)
    current_price = float(data.get("c") or 0)
    percent_change = float(data.get("dp") or 0)

    if current_price <= 0:
        return None

    return {
        "symbol": symbol,
        "price": current_price,
        "change": float(data.get("d") or 0),
        "percent_change": percent_change,
    }


def rank_daily_movers(api_key=None, symbols=None, limit=None, pause_seconds=0.05):
    api_key = (api_key or finnhub_api_key()).strip()
    if not api_key:
        return None, "Finnhub API key not configured"

    limit = limit or top_mover_count()
    quotes = []
    errors = []

    for symbol in symbols or candidate_symbols():
        try:
            quote = quote_symbol(symbol, api_key)
            if quote:
                quotes.append(quote)
        except (OSError, URLError, ValueError, TimeoutError) as exc:
            errors.append(f"{symbol}: {exc}")
        time.sleep(pause_seconds)

    if not quotes:
        return None, "Finnhub returned no quote data"

    bullish = sorted(quotes, key=lambda row: row["percent_change"], reverse=True)[:limit]
    bearish = sorted(quotes, key=lambda row: row["percent_change"])[:limit]
    return {"bullish": bullish, "bearish": bearish}, "; ".join(errors[:3])


def active_symbol_groups(api_key=None):
    cached_movers = load_cached_movers()
    if cached_movers:
        movers = cached_movers
        error = ""
    else:
        movers, error = rank_daily_movers(api_key=api_key)

        if movers:
            save_cached_movers(movers)

    if not movers:
        return DEFAULT_SYMBOL_GROUPS, "Original scanner universe", error

    bullish_symbols = [row["symbol"] for row in movers["bullish"]]
    bearish_symbols = [row["symbol"] for row in movers["bearish"]]

    return (
        {
            "Top Bullish Movers": bullish_symbols,
            "Top Bearish Movers": bearish_symbols,
        },
        "Finnhub daily movers",
        error,
    )


def flatten_symbol_groups(symbol_groups):
    seen = set()
    symbols = []

    for group_symbols in symbol_groups.values():
        for symbol in group_symbols:
            if symbol not in seen:
                seen.add(symbol)
                symbols.append(symbol)

    return symbols
