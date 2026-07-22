import yfinance as yf
import pandas as pd
from datetime import datetime, time

from optionbeacon_universe import SYMBOLS


def get_data(symbol):
    data = yf.download(symbol, period="5d", interval="5m", progress=False)

    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    return data.dropna()


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

    return df


def pick_option_contract(symbol, signal, price):
    if signal == "WAIT":
        return None

    ticker = yf.Ticker(symbol)
    expirations = ticker.options

    if not expirations:
        return None

    expiration = expirations[0]
    chain = ticker.option_chain(expiration)

    if signal == "BUY CALL":
        options = chain.calls.copy()
    else:
        options = chain.puts.copy()

    options["distance"] = abs(options["strike"] - price)

    # Prefer contracts near the money, then decent liquidity
    options = options.sort_values(["distance", "openInterest", "volume"], ascending=[True, False, False])

    best = options.iloc[0]

    return {
        "contract": best["contractSymbol"],
        "expiration": expiration,
        "strike": float(best["strike"]),
        "last_price": float(best["lastPrice"]),
        "bid": float(best["bid"]),
        "ask": float(best["ask"]),
        "volume": int(best["volume"]) if pd.notna(best["volume"]) else 0,
        "open_interest": int(best["openInterest"]) if pd.notna(best["openInterest"]) else 0,
    }

def market_hours_status():
    now = datetime.now().time()

    start_time = time(9, 45)
    stop_time = time(15, 0)

    if now < start_time:
        return False, "Too early — no trades before 9:45 AM"
    elif now > stop_time:
        return False, "Too late — no new trades after 3:00 PM"
    else:
        return True, "Market timing allowed"

def generate_signal(symbol):
    trading_allowed, timing_reason = market_hours_status()
    df = add_indicators(get_data(symbol))

    latest = df.iloc[-1]
    previous_3 = df.iloc[-4:-1]

    price = float(latest["Close"])
    vwap = float(latest["VWAP"])
    ema9 = float(latest["EMA9"])
    ema21 = float(latest["EMA21"])
    rsi = float(latest["RSI"])
    volume = int(latest["Volume"])
    avg_volume = float(latest["AVG_VOLUME_20"])

    prior_15_high = float(previous_3["High"].max())
    prior_15_low = float(previous_3["Low"].min())

    call_score = 0
    put_score = 0
    call_reasons = []
    put_reasons = []

    if price > vwap:
        call_score += 25
        call_reasons.append("Price above VWAP")
    elif price < vwap:
        put_score += 25
        put_reasons.append("Price below VWAP")

    if ema9 > ema21:
        call_score += 25
        call_reasons.append("EMA9 above EMA21")
    elif ema9 < ema21:
        put_score += 25
        put_reasons.append("EMA9 below EMA21")

    if price > prior_15_high:
        call_score += 20
        call_reasons.append("Breakout above prior 15-min high")

    if price < prior_15_low:
        put_score += 20
        put_reasons.append("Breakdown below prior 15-min low")

    if 52 <= rsi <= 70:
        call_score += 15
        call_reasons.append("RSI bullish zone")

    if 30 <= rsi <= 48:
        put_score += 15
        put_reasons.append("RSI bearish zone")

    if volume > avg_volume * 1.25:
        call_score += 15
        put_score += 15
        call_reasons.append("Volume expansion")
        put_reasons.append("Volume expansion")

    if not trading_allowed:
        signal = "WAIT"
        confidence = max(call_score, put_score)
        reasons = [timing_reason]

    elif call_score >= 75 and call_score > put_score:
        signal = "BUY CALL"
        confidence = call_score
        reasons = call_reasons
    elif put_score >= 75 and put_score > call_score:
        signal = "BUY PUT"
        confidence = put_score
        reasons = put_reasons
    else:
        signal = "WAIT"
        confidence = max(call_score, put_score)
        reasons = call_reasons if call_score >= put_score else put_reasons

    entry = price

    if signal == "BUY CALL":
        stop = price * 0.9975
        target_1 = price * 1.0025
        target_2 = price * 1.0050
    elif signal == "BUY PUT":
        stop = price * 1.0025
        target_1 = price * 0.9975
        target_2 = price * 0.9950
    else:
        stop = None
        target_1 = None
        target_2 = None

    option_contract = pick_option_contract(symbol, signal, price)

    return {
        "symbol": symbol,
        "signal": signal,
        "confidence": confidence,
        "price": price,
        "entry": entry,
        "stop": stop,
        "target_1": target_1,
        "target_2": target_2,
        "rsi": rsi,
        "vwap": vwap,
        "ema9": ema9,
        "ema21": ema21,
        "reasons": reasons,
        "option_contract": option_contract,
    }


def print_signal(result):
    print("\n" + "=" * 40)
    print(f"{result['symbol']} OPTIONBEACON SIGNAL")
    print("=" * 40)
    print(f"Signal: {result['signal']}")
    print(f"Confidence: {result['confidence']}%")
    print(f"Price: ${result['price']:.2f}")
    print(f"RSI: {result['rsi']:.2f}")
    print(f"VWAP: ${result['vwap']:.2f}")
    print(f"EMA9: ${result['ema9']:.2f}")
    print(f"EMA21: ${result['ema21']:.2f}")

    if result["signal"] != "WAIT":
        print(f"Entry: ${result['entry']:.2f}")
        print(f"Stop: ${result['stop']:.2f}")
        print(f"Target 1: ${result['target_1']:.2f}")
        print(f"Target 2: ${result['target_2']:.2f}")

    if result["option_contract"]:
        c = result["option_contract"]
        print("\nSuggested Option Contract:")
        print(f"Contract: {c['contract']}")
        print(f"Expiration: {c['expiration']}")
        print(f"Strike: ${c['strike']:.2f}")
        print(f"Last Price: ${c['last_price']:.2f}")
        print(f"Bid/Ask: ${c['bid']:.2f} / ${c['ask']:.2f}")
        print(f"Volume: {c['volume']}")
        print(f"Open Interest: {c['open_interest']}")

    print("\nReasons:")
    if result["reasons"]:
        for reason in result["reasons"]:
            print(f"- {reason}")
    else:
        print("- No strong setup yet")

def log_signal(result):
    if result["signal"] == "WAIT":
        return

    row = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "symbol": result["symbol"],
        "signal": result["signal"],
        "confidence": result["confidence"],
        "entry": round(result["entry"], 2),
        "stop": round(result["stop"], 2),
        "target_1": round(result["target_1"], 2),
        "target_2": round(result["target_2"], 2),
        "price": round(result["price"], 2),
        "status": "OPEN",
    }

    file_name = "optionbeacon_trade_journal.csv"

    try:
        old_log = pd.read_csv(file_name)
        new_log = pd.concat(
            [old_log, pd.DataFrame([row])],
            ignore_index=True
        )
    except FileNotFoundError:
        new_log = pd.DataFrame([row])

    new_log.to_csv(file_name, index=False)

def main():
    print("\nOPTIONBEACON")
    print("SPY / QQQ Signal Scanner")

    for symbol in SYMBOLS:
        result = generate_signal(symbol)
        print_signal(result)
        log_signal(result)


if __name__ == "__main__":
    main()
