import yfinance as yf
import pandas as pd
import time
import logging
import random
from datetime import datetime
from zoneinfo import ZoneInfo

from finnhub_universe import (
    DEFAULT_ETF_SYMBOLS,
    DEFAULT_STOCK_SYMBOLS,
    active_symbol_groups,
    flatten_symbol_groups,
)
from optionbeacon_strategy import score_candle
from signal_history import record_scanner_result, update_trade_outcomes_from_result
from trade_planning import enrich_with_trade_plan
from trade_plan_service import process_scanner_trade_plan
from tradier_options import enrich_with_option_liquidity

ETF_SYMBOLS = DEFAULT_ETF_SYMBOLS
STOCK_SYMBOLS = DEFAULT_STOCK_SYMBOLS
SYMBOLS = ETF_SYMBOLS + STOCK_SYMBOLS

PERIOD = "5d"
INTERVAL = "5m"
DATA_PERIODS = ["5d", "10d", "1mo"]

SCAN_SECONDS = 300  # 5 minutes
LOGGER = logging.getLogger(__name__)
MARKET_DATA_MAX_ATTEMPTS = 3
MARKET_DATA_BACKOFF_SECONDS = 0.5
MARKET_DATA_MAX_JITTER_SECONDS = 0.25
_MARKET_DATA_SCAN_CACHE = None
_MARKET_DATA_SCAN_STATS = None


def begin_market_data_scan_cycle():
    """Start one serial scan cache and provider-warning accumulator."""
    global _MARKET_DATA_SCAN_CACHE, _MARKET_DATA_SCAN_STATS
    _MARKET_DATA_SCAN_CACHE = {}
    _MARKET_DATA_SCAN_STATS = {
        "provider": "Yahoo Finance via yfinance",
        "requests": 0,
        "cache_hits": 0,
        "rate_limited_symbols": set(),
    }


def end_market_data_scan_cycle() -> dict:
    """Return a JSON-safe scan summary and clear cycle-local state."""
    global _MARKET_DATA_SCAN_CACHE, _MARKET_DATA_SCAN_STATS
    stats = _MARKET_DATA_SCAN_STATS or {
        "provider": "Yahoo Finance via yfinance",
        "requests": 0,
        "cache_hits": 0,
        "rate_limited_symbols": set(),
    }
    result = {
        **stats,
        "rate_limited_symbols": sorted(stats["rate_limited_symbols"]),
    }
    _MARKET_DATA_SCAN_CACHE = None
    _MARKET_DATA_SCAN_STATS = None
    return result


def _rate_limit_error(exc) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return "429" in text or "rate limit" in text or "too many requests" in text


def eastern_timestamp():
    return datetime.now(ZoneInfo("America/New_York")).isoformat()


def eastern_candle_timestamp(value):
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("America/New_York")
    else:
        timestamp = timestamp.tz_convert("America/New_York")
    return timestamp.isoformat()


def download_data(symbol, period):
    try:
        return yf.download(
            symbol,
            period=period,
            interval=INTERVAL,
            progress=False,
            threads=False,
            timeout=10,
        )
    except TypeError:
        return yf.download(symbol, period=period, interval=INTERVAL, progress=False)


def _download_market_data(symbol, period, *, sleep=time.sleep, jitter=random.uniform):
    key = (str(symbol).upper(), str(period), INTERVAL)
    if _MARKET_DATA_SCAN_CACHE is not None and key in _MARKET_DATA_SCAN_CACHE:
        _MARKET_DATA_SCAN_STATS["cache_hits"] += 1
        return _MARKET_DATA_SCAN_CACHE[key].copy()

    last_error = None
    for attempt in range(MARKET_DATA_MAX_ATTEMPTS):
        if _MARKET_DATA_SCAN_STATS is not None:
            _MARKET_DATA_SCAN_STATS["requests"] += 1
        try:
            frame = download_data(symbol, period)
            if _MARKET_DATA_SCAN_CACHE is not None:
                _MARKET_DATA_SCAN_CACHE[key] = frame.copy()
            return frame
        except Exception as exc:
            last_error = exc
            if not _rate_limit_error(exc):
                raise
            if _MARKET_DATA_SCAN_STATS is not None:
                _MARKET_DATA_SCAN_STATS["rate_limited_symbols"].add(
                    str(symbol).upper()
                )
            if attempt < MARKET_DATA_MAX_ATTEMPTS - 1:
                delay = MARKET_DATA_BACKOFF_SECONDS * (2**attempt)
                delay += jitter(0, MARKET_DATA_MAX_JITTER_SECONDS)
                sleep(delay)
    raise RuntimeError("Yahoo Finance rate limit retries exhausted") from last_error


def get_data(symbol):
    last_error = None

    for period in DATA_PERIODS:
        try:
            df = _download_market_data(symbol, period)
        except Exception as exc:
            last_error = exc
            if _rate_limit_error(exc) or _rate_limit_error(exc.__cause__ or exc):
                break
            continue

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df.dropna()
        if not df.empty:
            return df

    if last_error:
        raise RuntimeError(f"market data request failed: {last_error}")

    return pd.DataFrame()


def add_indicators(df):
    df["EMA9"] = df["Close"].ewm(span=9, adjust=False).mean()
    df["EMA21"] = df["Close"].ewm(span=21, adjust=False).mean()
    df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
    df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()
    df["EMA200"] = df["Close"].ewm(span=200, adjust=False).mean()

    df["MACD"] = df["Close"].ewm(span=12, adjust=False).mean() - df["Close"].ewm(span=26, adjust=False).mean()
    df["MACD_SIGNAL"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_HIST"] = df["MACD"] - df["MACD_SIGNAL"]

    delta = df["Close"].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = -delta.where(delta < 0, 0).rolling(14).mean()
    rs = gain / loss
    df["RSI"] = 100 - (100 / (1 + rs))

    typical_price = (df["High"] + df["Low"] + df["Close"]) / 3
    df["VWAP"] = (typical_price * df["Volume"]).cumsum() / df["Volume"].cumsum()
    df["AVG_VOLUME_20"] = df["Volume"].rolling(20).mean()

    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift()).abs()
    low_close = (df["Low"] - df["Close"].shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["ATR"] = true_range.rolling(14).mean()
    df["AVG_ATR_20"] = df["ATR"].rolling(20).mean()

    return df.dropna()


def generate_signal(symbol):
    raw_data = get_data(symbol)

    if raw_data.empty:
        return None

    df = add_indicators(raw_data)

    if len(df) < 30:
        return None

    i = len(df) - 1
    result = score_candle(df, i, symbol)
    result = enrich_with_trade_plan(result)
    result = enrich_with_option_liquidity(result)
    result["last_candle_at"] = eastern_candle_timestamp(df.index[i])
    result["timestamp"] = eastern_timestamp()
    process_scanner_trade_plan(result)
    update_trade_outcomes_from_result(result)
    record_scanner_result(result)
    try:
        from false_breakout_experiment import record_live_shadow

        record_live_shadow(result, df, i)
    except Exception as exc:
        LOGGER.warning(
            "Experiment 001 shadow evaluation failed for %s: %s",
            symbol,
            exc,
        )
    try:
        from regime_selection_experiment import record_live_shadow

        record_live_shadow(result, df, i)
    except Exception as exc:
        LOGGER.warning(
            "Experiment 002 shadow evaluation failed for %s: %s",
            symbol,
            exc,
        )
    try:
        from signal_funnel_experiment import record_live_shadow

        record_live_shadow(result)
    except Exception as exc:
        LOGGER.warning(
            "Experiment 003 signal funnel shadow evaluation failed for %s: %s",
            symbol,
            exc,
        )
    return result


def print_signal(result):
    print("\n" + "=" * 50)
    print(f"{result['symbol']} OPTIONBEACON LIVE SIGNAL")
    print("=" * 50)
    print(f"Signal: {result['signal']}")

    if result["signal"] == "MARKET CLOSED / WAIT":
        print(f"Price: ${result['price']:.2f}")
        return

    print(f"Confidence: {result['confidence']}%")
    print(f"Price: ${result['price']:.2f}")
    print(f"Bullish Score: {result['bullish_score']}")
    print(f"Bearish Score: {result['bearish_score']}")
    print(f"RSI: {result['rsi']:.2f}")
    print(f"VWAP: ${result['vwap']:.2f}")
    print(f"EMA20: ${result['ema20']:.2f}")
    print(f"EMA50: ${result['ema50']:.2f}")
    print(f"EMA200: ${result['ema200']:.2f}")

    if result["signal"] not in ["WATCHLIST", "MARKET CLOSED / WAIT"]:
        print("\nTRADE PLAN")
        print(f"Entry: ${result['entry']:.2f}")
        print(f"Stop: ${result['stop']:.2f}")
        print(f"Target: ${result['target']:.2f}")
        print(f"Breakeven Trigger: ${result['breakeven']:.2f}")

    print("\nReasons:")
    if result["reasons"]:
        for reason in result["reasons"]:
            print(f"- {reason}")
    else:
        print("- No strong setup yet")


def log_signal(result):
    if result is None:
        return

    if result["signal"] in ["WATCHLIST", "MARKET CLOSED / WAIT"]:
        return

    row = {
        "timestamp": result["timestamp"],
        "symbol": result["symbol"],
        "signal": result["signal"],
        "confidence": result["confidence"],
        "entry": round(result["entry"], 2),
        "stop": round(result["stop"], 2),
        "target": round(result["target"], 2),
        "breakeven": round(result["breakeven"], 2),
        "price": round(result["price"], 2),
        "call_score": result["call_score"],
        "put_score": result["put_score"],
        "rsi": round(result["rsi"], 2),
        "vwap": round(result["vwap"], 2),
        "ema20": round(result["ema20"], 2),
        "ema50": round(result["ema50"], 2),
        "ema200": round(result["ema200"], 2),
        "status": "OPEN",
    }

    file_name = "optionbeacon_live_signals.csv"

    try:
        old_log = pd.read_csv(file_name)
        new_log = pd.concat([old_log, pd.DataFrame([row])], ignore_index=True)
    except FileNotFoundError:
        new_log = pd.DataFrame([row])

    new_log.to_csv(file_name, index=False)


def main():
    print("\nOPTIONBEACON LIVE SCANNER")
    print("ETF + Single Stock 5-Minute Live Signal Scanner")
    print("Press CTRL + C to stop.")

    while True:
        print("\n\nScanning...")
        print(eastern_timestamp())
        symbol_groups, source, error = active_symbol_groups()
        scan_symbols = flatten_symbol_groups(symbol_groups)
        print(f"Universe: {source} ({len(scan_symbols)} symbols)")
        if error:
            print(f"Universe note: {error}")

        for symbol in scan_symbols:
            result = generate_signal(symbol)

            if result:
                print_signal(result)
                log_signal(result)

        print(f"\nWaiting {SCAN_SECONDS // 60} minutes...")
        time.sleep(SCAN_SECONDS)


if __name__ == "__main__":
    main()
