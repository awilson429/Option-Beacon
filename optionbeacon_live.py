import yfinance as yf
import pandas as pd
import time
from datetime import datetime

from optionbeacon_strategy import score_candle
from optionbeacon_universe import ETF_SYMBOLS, STOCK_SYMBOLS, SYMBOLS

PERIOD = "5d"
INTERVAL = "5m"
DATA_PERIODS = ["5d", "10d", "1mo"]

SCAN_SECONDS = 300  # 5 minutes


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


def get_data(symbol):
    last_error = None

    for period in DATA_PERIODS:
        try:
            df = download_data(symbol, period)
        except Exception as exc:
            last_error = exc
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
    result["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
        print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        for symbol in SYMBOLS:
            result = generate_signal(symbol)

            if result:
                print_signal(result)
                log_signal(result)

        print(f"\nWaiting {SCAN_SECONDS // 60} minutes...")
        time.sleep(SCAN_SECONDS)


if __name__ == "__main__":
    main()
