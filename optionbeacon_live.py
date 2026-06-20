import yfinance as yf
import pandas as pd
import time
from datetime import datetime

SYMBOLS = ["SPY", "QQQ", "IWM", "DIA"]

PERIOD = "5d"
INTERVAL = "5m"

MIN_SCORE = 90

STOP_PERCENT = 0.0025
TARGET_PERCENT = 0.0050
BREAKEVEN_TRIGGER = 0.0040

BREAKOUT_BUFFER_UP = 1.0003
BREAKOUT_BUFFER_DOWN = 0.9997

VOLUME_MULTIPLIER = 1.40

SCAN_SECONDS = 300  # 5 minutes


def get_data(symbol):
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


def is_trade_time(timestamp):
    t = timestamp.time()

    if t.hour < 9:
        return False

    if t.hour == 9 and t.minute < 45:
        return False

    if t.hour >= 15:
        return False

    return True


def generate_signal(symbol):
    df = add_indicators(get_data(symbol))

    if len(df) < 30:
        return None

    i = len(df) - 1
    candle = df.iloc[i]

    if not is_trade_time(df.index[i]):
        return {
            "symbol": symbol,
            "signal": "MARKET CLOSED / WAIT",
            "price": float(candle["Close"]),
        }

    previous_3 = df.iloc[i - 3:i]

    price = float(candle["Close"])
    volume = int(candle["Volume"])
    avg_volume = float(candle["AVG_VOLUME_20"])

    prior_15_high = float(previous_3["High"].max())
    prior_15_low = float(previous_3["Low"].min())

    call_score = 0
    put_score = 0
    call_reasons = []
    put_reasons = []

    if price > candle["VWAP"]:
        call_score += 25
        call_reasons.append("Price above VWAP")
    elif price < candle["VWAP"]:
        put_score += 25
        put_reasons.append("Price below VWAP")

    if candle["EMA9"] > candle["EMA21"]:
        call_score += 25
        call_reasons.append("EMA9 above EMA21")
    elif candle["EMA9"] < candle["EMA21"]:
        put_score += 25
        put_reasons.append("EMA9 below EMA21")

    if price > prior_15_high * BREAKOUT_BUFFER_UP:
        call_score += 20
        call_reasons.append("Breakout above prior 15-min high")

    if price < prior_15_low * BREAKOUT_BUFFER_DOWN:
        put_score += 20
        put_reasons.append("Breakdown below prior 15-min low")

    if 52 <= candle["RSI"] <= 70:
        call_score += 15
        call_reasons.append("RSI bullish zone")

    if 30 <= candle["RSI"] <= 48:
        put_score += 15
        put_reasons.append("RSI bearish zone")

    if volume > avg_volume * VOLUME_MULTIPLIER:
        call_score += 15
        put_score += 15
        call_reasons.append("Volume expansion")
        put_reasons.append("Volume expansion")

    if call_score >= MIN_SCORE and call_score > put_score:
        signal = "BUY CALL"
        confidence = call_score
        reasons = call_reasons
        entry = price
        stop = price * (1 - STOP_PERCENT)
        target = price * (1 + TARGET_PERCENT)
        breakeven = price * (1 + BREAKEVEN_TRIGGER)

    elif put_score >= MIN_SCORE and put_score > call_score:
        signal = "BUY PUT"
        confidence = put_score
        reasons = put_reasons
        entry = price
        stop = price * (1 + STOP_PERCENT)
        target = price * (1 - TARGET_PERCENT)
        breakeven = price * (1 - BREAKEVEN_TRIGGER)

    else:
        signal = "WAIT"
        confidence = max(call_score, put_score)
        reasons = call_reasons if call_score >= put_score else put_reasons
        entry = None
        stop = None
        target = None
        breakeven = None

    return {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "symbol": symbol,
        "signal": signal,
        "confidence": confidence,
        "price": price,
        "entry": entry,
        "stop": stop,
        "target": target,
        "breakeven": breakeven,
        "call_score": call_score,
        "put_score": put_score,
        "rsi": float(candle["RSI"]),
        "vwap": float(candle["VWAP"]),
        "ema9": float(candle["EMA9"]),
        "ema21": float(candle["EMA21"]),
        "volume": volume,
        "avg_volume": avg_volume,
        "reasons": reasons,
    }


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
    print("SPY / QQQ / IWM / DIA 5-Minute Live Signal Scanner")
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
