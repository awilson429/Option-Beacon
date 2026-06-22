import yfinance as yf
import pandas as pd
import time
from datetime import datetime

from optionbeacon_strategy import score_candle

ETF_SYMBOLS = ["SPY", "QQQ", "IWM", "DIA"]
STOCK_SYMBOLS = ["NVDA", "TSLA", "AAPL", "AMD"]
SYMBOLS = ETF_SYMBOLS + STOCK_SYMBOLS

PERIOD = "5d"
INTERVAL = "5m"

SCAN_SECONDS = 300  # 5 minutes


def get_data(symbol):
    try:
        df = yf.download(
            symbol,
            period=PERIOD,
            interval=INTERVAL,
            progress=False,
            threads=False,
            timeout=10,
        )
    except TypeError:
        df = yf.download(symbol, period=PERIOD, interval=INTERVAL, progress=False)

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    return df.dropna()


def add_indicators(df):
    df["EMA9"] = df["Close"].ewm(span=9, adjust=False).mean()
    df["EMA21"] = df["Close"].ewm(span=21, adjust=False).mean()

    delta = df["Close"].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = -delta.where(delta < 0, 0).rolling(14).mean()
    rs = gain / loss
    df["RSI"] = 100 - (100 / (1 + rs))

    typical_price = (df["High"] + df["Low"] + df["Close"]) / 3
    df["VWAP"] = (typical_price * df["Volume"]).cumsum() / df["Volume"].cumsum()
    df["AVG_VOLUME_20"] = df["Volume"].rolling(20).mean()

    return df.dropna()


def generate_signal(symbol):
    df = add_indicators(get_data(symbol))

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
    print(f"CALL Score: {result['call_score']}")
    print(f"PUT Score: {result['put_score']}")
    print(f"RSI: {result['rsi']:.2f}")
    print(f"VWAP: ${result['vwap']:.2f}")
    print(f"EMA9: ${result['ema9']:.2f}")
    print(f"EMA21: ${result['ema21']:.2f}")

    if result["signal"] != "WAIT":
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

    if result["signal"] in ["WAIT", "MARKET CLOSED / WAIT"]:
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
        "ema9": round(result["ema9"], 2),
        "ema21": round(result["ema21"], 2),
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
