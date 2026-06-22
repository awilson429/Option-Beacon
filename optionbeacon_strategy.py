DEFAULT_CALL_SCORE_THRESHOLD = 90
DEFAULT_PUT_SCORE_THRESHOLD = 90

STOP_PERCENT = 0.0025
TARGET_PERCENT = 0.0050
BREAKEVEN_TRIGGER = 0.0040

BREAKOUT_BUFFER_UP = 1.0003
BREAKOUT_BUFFER_DOWN = 0.9997

VOLUME_MULTIPLIER = 1.40


def is_trade_time(timestamp):
    t = timestamp.time()

    if t.hour < 9:
        return False

    if t.hour == 9 and t.minute < 45:
        return False

    if t.hour >= 15:
        return False

    return True


def score_candle(
    df,
    i,
    symbol,
    call_score_threshold=DEFAULT_CALL_SCORE_THRESHOLD,
    put_score_threshold=DEFAULT_PUT_SCORE_THRESHOLD,
):
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

    if call_score >= call_score_threshold and call_score > put_score:
        signal = "BUY CALL"
        confidence = call_score
        reasons = call_reasons
        entry = price
        stop = price * (1 - STOP_PERCENT)
        target = price * (1 + TARGET_PERCENT)
        breakeven = price * (1 + BREAKEVEN_TRIGGER)

    elif put_score >= put_score_threshold and put_score > call_score:
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
