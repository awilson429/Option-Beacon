import re


WHITELISTED_SYMBOLS = {
    "SPY",
    "QQQ",
    "IWM",
    "DIA",
    "NVDA",
    "TSLA",
    "AAPL",
    "AMD",
}

COMMON_FALSE_POSITIVES = {
    "A",
    "AI",
    "AM",
    "ARE",
    "AT",
    "BE",
    "BY",
    "CAN",
    "DD",
    "FOR",
    "GO",
    "HAS",
    "IT",
    "NOW",
    "ON",
    "OR",
    "OUT",
    "SO",
    "UP",
}

COMPANY_ALIASES = {
    "APPLE": "AAPL",
    "NVIDIA": "NVDA",
    "TESLA": "TSLA",
    "ADVANCED MICRO DEVICES": "AMD",
    "AMD": "AMD",
    "NASDAQ": "QQQ",
    "RUSSELL": "IWM",
    "DOW": "DIA",
    "S&P": "SPY",
    "S&P 500": "SPY",
}


def extract_tickers(text):
    if not text:
        return []

    upper_text = text.upper()
    matches = set()

    for alias, symbol in COMPANY_ALIASES.items():
        if alias in upper_text:
            matches.add(symbol)

    cashtags = re.findall(r"\$([A-Z]{1,5})\b", upper_text)
    words = re.findall(r"\b[A-Z]{2,5}\b", upper_text)

    for candidate in cashtags + words:
        if candidate in COMMON_FALSE_POSITIVES:
            continue
        if candidate in WHITELISTED_SYMBOLS:
            matches.add(candidate)

    return sorted(matches)
