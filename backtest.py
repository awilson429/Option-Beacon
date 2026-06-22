import yfinance as yf
import pandas as pd

ETF_SYMBOLS = ["SPY", "QQQ", "IWM", "DIA"]
STOCK_SYMBOLS = ["NVDA", "TSLA", "AAPL", "AMD"]
SYMBOLS = ETF_SYMBOLS + STOCK_SYMBOLS

PERIOD = "60d"
INTERVAL = "5m"

CALL_SCORE_THRESHOLD = 90
PUT_SCORE_THRESHOLD = 75

MAX_HOLD_CANDLES = 48

STOP_PERCENT = 0.0025
TARGET_PERCENT = 0.0050
BREAKEVEN_TRIGGER = 0.0040

BREAKOUT_BUFFER_UP = 1.0003
BREAKOUT_BUFFER_DOWN = 0.9997

VOLUME_MULTIPLIER = 1.40
BREAKOUT_VOLUME_MULTIPLIER = 1.05
EMA_GAP_MIN = 0.0003


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


def score_candle(df, i):
    candle = df.iloc[i]

    if not is_trade_time(df.index[i]):
        return "WAIT", 0, float(candle["Close"])

    previous_3 = df.iloc[i - 3:i]

    price = float(candle["Close"])
    volume = int(candle["Volume"])
    avg_volume = float(candle["AVG_VOLUME_20"])

    prior_15_high = float(previous_3["High"].max())
    prior_15_low = float(previous_3["Low"].min())

    call_score = 0
    put_score = 0

    if price > candle["VWAP"]:
        call_score += 25
    elif price < candle["VWAP"]:
        put_score += 25

    ema_gap = abs(candle["EMA9"] - candle["EMA21"]) / price

    if candle["EMA9"] > candle["EMA21"] and ema_gap > EMA_GAP_MIN:
        call_score += 25
    elif candle["EMA9"] < candle["EMA21"] and ema_gap > EMA_GAP_MIN:
        put_score += 25

    if (
        price > prior_15_high * BREAKOUT_BUFFER_UP
        and volume > avg_volume * BREAKOUT_VOLUME_MULTIPLIER
    ):
        call_score += 20

    if (
        price < prior_15_low * BREAKOUT_BUFFER_DOWN
        and volume > avg_volume * BREAKOUT_VOLUME_MULTIPLIER
    ):
        put_score += 20

    if 52 <= candle["RSI"] <= 70:
        call_score += 15

    if candle["RSI"] < 50:
        put_score += 15

    if volume > avg_volume * VOLUME_MULTIPLIER:
        call_score += 15
        put_score += 15

    if call_score >= CALL_SCORE_THRESHOLD and call_score > put_score:
        return "BUY CALL", call_score, price

    if put_score >= PUT_SCORE_THRESHOLD and put_score > call_score:
        return "BUY PUT", put_score, price

    return "WAIT", max(call_score, put_score), price


def grade_trade(df, entry_index, signal, entry_price):
    breakeven_active = False

    if signal == "BUY CALL":
        stop = entry_price * (1 - STOP_PERCENT)
        target = entry_price * (1 + TARGET_PERCENT)
        breakeven_price = entry_price * (1 + BREAKEVEN_TRIGGER)

        for j in range(entry_index + 1, min(entry_index + MAX_HOLD_CANDLES, len(df))):
            low = float(df.iloc[j]["Low"])
            high = float(df.iloc[j]["High"])

            if high >= breakeven_price:
                breakeven_active = True

            active_stop = entry_price if breakeven_active else stop

            if low <= active_stop:
                if breakeven_active:
                    return "BREAKEVEN", entry_price
                return "LOSS", stop

            if high >= target:
                return "WIN", target

    if signal == "BUY PUT":
        stop = entry_price * (1 + STOP_PERCENT)
        target = entry_price * (1 - TARGET_PERCENT)
        breakeven_price = entry_price * (1 - BREAKEVEN_TRIGGER)

        for j in range(entry_index + 1, min(entry_index + MAX_HOLD_CANDLES, len(df))):
            low = float(df.iloc[j]["Low"])
            high = float(df.iloc[j]["High"])

            if low <= breakeven_price:
                breakeven_active = True

            active_stop = entry_price if breakeven_active else stop

            if high >= active_stop:
                if breakeven_active:
                    return "BREAKEVEN", entry_price
                return "LOSS", stop

            if low <= target:
                return "WIN", target

    final_index = min(entry_index + MAX_HOLD_CANDLES, len(df) - 1)
    return "TIME EXIT", float(df.iloc[final_index]["Close"])


def backtest_symbol(symbol):
    df = add_indicators(get_data(symbol))

    trades = []
    i = 25

    while i < len(df):
        signal, score, price = score_candle(df, i)

        if signal != "WAIT":
            result, exit_price = grade_trade(df, i, signal, price)

            if signal == "BUY CALL":
                pnl_percent = ((exit_price - price) / price) * 100
                direction = "LONG"
            else:
                pnl_percent = ((price - exit_price) / price) * 100
                direction = "SHORT"

            trades.append({
                "symbol": symbol,
                "time": df.index[i],
                "signal": signal,
                "direction": direction,
                "score": score,
                "entry": round(price, 2),
                "exit": round(exit_price, 2),
                "result": result,
                "pnl_percent": round(pnl_percent, 3),
            })

            i += MAX_HOLD_CANDLES
        else:
            i += 1

    return pd.DataFrame(trades)


def calculate_stats(results):
    if len(results) == 0:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "breakevens": 0,
            "time_exits": 0,
            "win_rate": 0,
            "avg_pnl": 0,
            "total_pnl": 0,
            "avg_win": 0,
            "avg_loss": 0,
            "avg_time_exit": 0,
            "profit_factor": 0,
        }

    wins = len(results[results["result"] == "WIN"])
    losses = len(results[results["result"] == "LOSS"])
    breakevens = len(results[results["result"] == "BREAKEVEN"])
    time_exits = len(results[results["result"] == "TIME EXIT"])

    win_rate = wins / len(results) * 100
    avg_pnl = results["pnl_percent"].mean()
    total_pnl = results["pnl_percent"].sum()

    avg_win = results[results["result"] == "WIN"]["pnl_percent"].mean()
    avg_loss = results[results["result"] == "LOSS"]["pnl_percent"].mean()
    avg_time_exit = results[results["result"] == "TIME EXIT"]["pnl_percent"].mean()

    if pd.isna(avg_win):
        avg_win = 0
    if pd.isna(avg_loss):
        avg_loss = 0
    if pd.isna(avg_time_exit):
        avg_time_exit = 0

    gross_wins = results[results["pnl_percent"] > 0]["pnl_percent"].sum()
    gross_losses = abs(results[results["pnl_percent"] < 0]["pnl_percent"].sum())

    profit_factor = gross_wins / gross_losses if gross_losses != 0 else 0

    return {
        "trades": len(results),
        "wins": wins,
        "losses": losses,
        "breakevens": breakevens,
        "time_exits": time_exits,
        "win_rate": win_rate,
        "avg_pnl": avg_pnl,
        "total_pnl": total_pnl,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "avg_time_exit": avg_time_exit,
        "profit_factor": profit_factor,
    }


def print_stats(title, stats):
    print(f"\n{title}")
    print("=" * 30)
    print(f"Trades: {stats['trades']}")
    print(f"Wins: {stats['wins']}")
    print(f"Losses: {stats['losses']}")
    print(f"Breakevens: {stats['breakevens']}")
    print(f"Time Exits: {stats['time_exits']}")
    print(f"Win Rate: {stats['win_rate']:.2f}%")
    print(f"Average P/L: {stats['avg_pnl']:.3f}%")
    print(f"Total P/L: {stats['total_pnl']:.3f}%")
    print(f"Average Win: {stats['avg_win']:.3f}%")
    print(f"Average Loss: {stats['avg_loss']:.3f}%")
    print(f"Average Time Exit: {stats['avg_time_exit']:.3f}%")
    print(f"Profit Factor: {stats['profit_factor']:.2f}")


def print_results(symbol, results):
    print("\n" + "=" * 40)
    print(f"{symbol} BACKTEST RESULTS")
    print("=" * 40)

    if len(results) == 0:
        print("No trades found.")
        return

    print_stats("ALL TRADES", calculate_stats(results))
    print_stats("LONG / CALL RESULTS", calculate_stats(results[results["direction"] == "LONG"]))
    print_stats("SHORT / PUT RESULTS", calculate_stats(results[results["direction"] == "SHORT"]))

    print("\nLast 10 trades")
    print("=" * 30)
    print(results.tail(10))

    file_name = f"{symbol}_backtest_results.csv"
    results.to_csv(file_name, index=False)
    print(f"\nSaved to {file_name}")


def main():
    print("\nOPTIONBEACON BACKTEST")
    print("ETF + Single Stock 5-Minute Strategy Test")
    print(f"Period: {PERIOD}")
    print(f"Interval: {INTERVAL}")
    print(f"Call Score Threshold: {CALL_SCORE_THRESHOLD}")
    print(f"Put Score Threshold: {PUT_SCORE_THRESHOLD}")
    print("Trade Window: 9:45 AM to 3:00 PM")
    print("Reward/Risk: 2:1")
    print(f"Stop: {STOP_PERCENT * 100:.2f}%")
    print(f"Target: {TARGET_PERCENT * 100:.2f}%")
    print(f"Breakout Buffer Up: {BREAKOUT_BUFFER_UP}")
    print(f"Breakout Buffer Down: {BREAKOUT_BUFFER_DOWN}")
    print(f"Volume Multiplier: {VOLUME_MULTIPLIER}")
    print(f"Breakout Volume Multiplier: {BREAKOUT_VOLUME_MULTIPLIER}")
    print(f"EMA Gap Minimum: {EMA_GAP_MIN}")
    print(f"Breakeven Trigger: {BREAKEVEN_TRIGGER * 100:.2f}%")

    for symbol in SYMBOLS:
        results = backtest_symbol(symbol)
        print_results(symbol, results)


if __name__ == "__main__":
    main()
