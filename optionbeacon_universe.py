import os


ETF_SYMBOLS = [
    "SPY",
    "QQQ",
    "IWM",
    "DIA",
    "TLT",
    "GLD",
    "SLV",
    "USO",
    "XLE",
    "XLF",
    "XLK",
    "XLV",
    "XLY",
    "XLI",
    "XLP",
    "XLU",
    "ARKK",
]

STOCK_SYMBOLS = [
    "NVDA",
    "TSLA",
    "AAPL",
    "AMD",
    "MSFT",
    "META",
    "AMZN",
    "GOOGL",
    "NFLX",
    "AVGO",
    "SMCI",
    "COIN",
    "MSTR",
    "PLTR",
    "INTC",
    "MU",
    "CRM",
    "ORCL",
    "JPM",
    "BAC",
    "GS",
    "MS",
    "UNH",
    "LLY",
    "XOM",
    "CVX",
    "BA",
    "DIS",
    "NKE",
]


def _symbols_from_env():
    raw_symbols = os.getenv("OPTION_BEACON_SYMBOLS", "")
    symbols = [symbol.strip().upper() for symbol in raw_symbols.split(",")]
    return [symbol for symbol in symbols if symbol]


CUSTOM_SYMBOLS = _symbols_from_env()
SYMBOL_GROUPS = {
    "ETF Scanner": ETF_SYMBOLS,
    "Single Stock Scanner": STOCK_SYMBOLS,
}

SYMBOLS = CUSTOM_SYMBOLS or ETF_SYMBOLS + STOCK_SYMBOLS
TRADABLE_SYMBOLS = set(ETF_SYMBOLS + STOCK_SYMBOLS + CUSTOM_SYMBOLS)
