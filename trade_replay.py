import pandas as pd

from finnhub_universe import DEFAULT_SYMBOL_GROUPS, flatten_symbol_groups
from optionbeacon_strategy import (
    BREAKEVEN_TRIGGER,
    DEFAULT_CALL_SCORE_THRESHOLD,
    DEFAULT_PUT_SCORE_THRESHOLD,
    STOP_PERCENT,
    TARGET_PERCENT,
    score_candle,
)


DEFAULT_REPLAY_SYMBOLS = flatten_symbol_groups(DEFAULT_SYMBOL_GROUPS)
DEFAULT_PERIOD = "60d"
DEFAULT_INTERVAL = "5m"
DEFAULT_MAX_HOLD_CANDLES = 48


def get_replay_data(symbol, period=DEFAULT_PERIOD, interval=DEFAULT_INTERVAL):
    import yfinance as yf

    data = yf.download(symbol, period=period, interval=interval, progress=False)

    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    return data.dropna()


def add_replay_indicators(data):
    df = data.copy()
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


def _direction(result):
    if result["signal"] == "BULLISH SETUP":
        return "Bullish"
    if result["signal"] == "BEARISH SETUP":
        return "Bearish"
    return None


def _target_price(entry, direction, multiplier=1):
    move = TARGET_PERCENT * multiplier
    if direction == "Bullish":
        return entry * (1 + move)
    return entry * (1 - move)


def _stop_price(entry, direction):
    if direction == "Bullish":
        return entry * (1 - STOP_PERCENT)
    return entry * (1 + STOP_PERCENT)


def _breakeven_trigger(entry, direction):
    if direction == "Bullish":
        return entry * (1 + BREAKEVEN_TRIGGER)
    return entry * (1 - BREAKEVEN_TRIGGER)


def _favorable_price(row, direction):
    return float(row["High"]) if direction == "Bullish" else float(row["Low"])


def _adverse_price(row, direction):
    return float(row["Low"]) if direction == "Bullish" else float(row["High"])


def _hit_or_better(price, level, direction):
    return price >= level if direction == "Bullish" else price <= level


def _hit_or_worse(price, level, direction):
    return price <= level if direction == "Bullish" else price >= level


def _pnl_percent(entry, exit_price, direction):
    if direction == "Bullish":
        return ((exit_price - entry) / entry) * 100
    return ((entry - exit_price) / entry) * 100


def replay_trade(df, entry_index, result, max_hold_candles=DEFAULT_MAX_HOLD_CANDLES):
    direction = _direction(result)
    entry = float(result.get("entry") or result["price"])
    stop = float(result.get("stop") or _stop_price(entry, direction))
    target_1 = float(result.get("target") or _target_price(entry, direction, 1))
    target_2 = _target_price(entry, direction, 2)
    target_3 = _target_price(entry, direction, 3)
    breakeven = float(result.get("breakeven") or _breakeven_trigger(entry, direction))
    current_stop = stop
    peak_price = entry
    partial_1 = False
    partial_2 = False
    breakeven_active = False
    events = []
    exit_reason = "TIME EXIT"
    exit_price = float(df.iloc[min(entry_index + max_hold_candles, len(df) - 1)]["Close"])
    exit_index = min(entry_index + max_hold_candles, len(df) - 1)

    for candle_index in range(entry_index + 1, min(entry_index + max_hold_candles + 1, len(df))):
        row = df.iloc[candle_index]
        favorable = _favorable_price(row, direction)
        adverse = _adverse_price(row, direction)

        if _hit_or_better(favorable, peak_price, direction):
            peak_price = favorable

        if _hit_or_worse(adverse, current_stop, direction):
            exit_reason = "STOP"
            exit_price = current_stop
            exit_index = candle_index
            events.append("Stop hit")
            break

        if not breakeven_active and _hit_or_better(favorable, breakeven, direction):
            breakeven_active = True
            current_stop = entry
            events.append("Moved stop to breakeven")

        if not partial_1 and _hit_or_better(favorable, target_1, direction):
            partial_1 = True
            events.append("Target 1 / first partial reached")

        if not partial_2 and _hit_or_better(favorable, target_2, direction):
            partial_2 = True
            current_stop = target_1
            events.append("Target 2 reached; trailed stop near Target 1")

        if _hit_or_better(favorable, target_3, direction):
            exit_reason = "TARGET 3"
            exit_price = target_3
            exit_index = candle_index
            events.append("Target 3 reached")
            break

    pnl = _pnl_percent(entry, exit_price, direction)
    peak_pnl = _pnl_percent(entry, peak_price, direction)

    return {
        "Exit Time": df.index[exit_index],
        "Exit Reason": exit_reason,
        "Exit Price": round(exit_price, 2),
        "P/L %": round(pnl, 3),
        "Peak P/L %": round(peak_pnl, 3),
        "Target 1 Hit": "Yes" if partial_1 else "No",
        "Target 2 Hit": "Yes" if partial_2 else "No",
        "Breakeven Stop": "Yes" if breakeven_active else "No",
        "Final Stop": round(current_stop, 2),
        "Events": "; ".join(events) if events else "No management event before exit",
    }


def replay_symbol(
    symbol,
    period=DEFAULT_PERIOD,
    interval=DEFAULT_INTERVAL,
    min_score=DEFAULT_CALL_SCORE_THRESHOLD,
    max_hold_candles=DEFAULT_MAX_HOLD_CANDLES,
):
    raw_data = get_replay_data(symbol, period=period, interval=interval)
    df = add_replay_indicators(raw_data)
    rows = []
    index = 25

    while index < len(df):
        result = score_candle(
            df,
            index,
            symbol,
            call_score_threshold=min_score,
            put_score_threshold=min_score,
        )
        direction = _direction(result)

        if direction:
            trade = replay_trade(df, index, result, max_hold_candles=max_hold_candles)
            rows.append(
                {
                    "Symbol": symbol,
                    "Entry Time": df.index[index],
                    "Direction": direction,
                    "Score": result["confidence"],
                    "Entry Price": round(float(result.get("entry") or result["price"]), 2),
                    "Stop": round(float(result.get("stop") or 0), 2),
                    "Target 1": round(float(result.get("target") or 0), 2),
                    "Primary Reason": result.get("reasons", [""])[0],
                    **trade,
                }
            )
            index += max_hold_candles
        else:
            index += 1

    return pd.DataFrame(rows)


def replay_symbols(
    symbols,
    period=DEFAULT_PERIOD,
    interval=DEFAULT_INTERVAL,
    min_score=DEFAULT_CALL_SCORE_THRESHOLD,
    max_hold_candles=DEFAULT_MAX_HOLD_CANDLES,
):
    frames = []
    errors = {}

    for symbol in symbols:
        try:
            result = replay_symbol(
                symbol,
                period=period,
                interval=interval,
                min_score=min_score,
                max_hold_candles=max_hold_candles,
            )
            if not result.empty:
                frames.append(result)
        except Exception as exc:
            errors[symbol] = str(exc)

    if not frames:
        return pd.DataFrame(), errors

    return pd.concat(frames, ignore_index=True), errors


def replay_summary(results):
    if results.empty:
        return {
            "Trades": 0,
            "Win Rate": "0.00%",
            "Average P/L": "0.000%",
            "Total P/L": "0.000%",
            "Average Peak P/L": "0.000%",
            "Target 1 Rate": "0.00%",
            "Breakeven Rate": "0.00%",
        }

    wins = results[results["P/L %"] > 0]
    target_1 = results[results["Target 1 Hit"] == "Yes"]
    breakeven = results[results["Breakeven Stop"] == "Yes"]

    return {
        "Trades": len(results),
        "Win Rate": f"{(len(wins) / len(results) * 100):.2f}%",
        "Average P/L": f"{results['P/L %'].mean():.3f}%",
        "Total P/L": f"{results['P/L %'].sum():.3f}%",
        "Average Peak P/L": f"{results['Peak P/L %'].mean():.3f}%",
        "Target 1 Rate": f"{(len(target_1) / len(results) * 100):.2f}%",
        "Breakeven Rate": f"{(len(breakeven) / len(results) * 100):.2f}%",
    }
