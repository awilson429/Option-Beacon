DEFAULT_CALL_SCORE_THRESHOLD = 90
DEFAULT_PUT_SCORE_THRESHOLD = 90
OPPORTUNITY_SCORE_THRESHOLD = 80

STOP_PERCENT = 0.0025
TARGET_PERCENT = 0.0050
BREAKEVEN_TRIGGER = 0.0040

BREAKOUT_BUFFER_UP = 1.0003
BREAKOUT_BUFFER_DOWN = 0.9997

VOLUME_MULTIPLIER = 1.40


def quality_from_score(score):
    if score >= 90:
        return "Very High"
    if score >= 80:
        return "High"
    if score >= 70:
        return "Moderate"
    return "Developing"


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
    previous_20 = df.iloc[max(0, i - 20):i]
    prior_candle = df.iloc[i - 1] if i > 0 else candle

    price = float(candle["Close"])
    volume = int(candle["Volume"])
    avg_volume = float(candle["AVG_VOLUME_20"])
    relative_volume = volume / avg_volume if avg_volume else 0

    prior_15_high = float(previous_3["High"].max())
    prior_15_low = float(previous_3["Low"].min())
    prior_20_high = float(previous_20["High"].max()) if len(previous_20) else prior_15_high
    prior_20_low = float(previous_20["Low"].min()) if len(previous_20) else prior_15_low

    bullish_score = 0
    bearish_score = 0
    bullish_reasons = []
    bearish_reasons = []
    category_scores = {
        "trend": 0,
        "momentum": 0,
        "volume": 0,
        "volatility": 0,
        "price_action": 0,
    }

    if price > candle["EMA20"]:
        bullish_score += 6
        category_scores["trend"] += 6
        bullish_reasons.append("Price above 20 EMA")
    elif price < candle["EMA20"]:
        bearish_score += 6
        category_scores["trend"] += 6
        bearish_reasons.append("Price below 20 EMA")

    if price > candle["EMA50"]:
        bullish_score += 6
        category_scores["trend"] += 6
        bullish_reasons.append("Price above 50 EMA")
    elif price < candle["EMA50"]:
        bearish_score += 6
        category_scores["trend"] += 6
        bearish_reasons.append("Price below 50 EMA")

    if price > candle["EMA200"]:
        bullish_score += 6
        category_scores["trend"] += 6
        bullish_reasons.append("Price above 200 EMA")
    elif price < candle["EMA200"]:
        bearish_score += 6
        category_scores["trend"] += 6
        bearish_reasons.append("Price below 200 EMA")

    if candle["EMA20"] > candle["EMA50"] > candle["EMA200"]:
        bullish_score += 7
        category_scores["trend"] += 7
        bullish_reasons.append("Bullish EMA alignment")
    elif candle["EMA20"] < candle["EMA50"] < candle["EMA200"]:
        bearish_score += 7
        category_scores["trend"] += 7
        bearish_reasons.append("Bearish EMA alignment")

    if 52 <= candle["RSI"] <= 70:
        bullish_score += 7
        category_scores["momentum"] += 7
        bullish_reasons.append("RSI in bullish range")
    elif 30 <= candle["RSI"] <= 48:
        bearish_score += 7
        category_scores["momentum"] += 7
        bearish_reasons.append("RSI in bearish range")

    if candle["MACD"] > candle["MACD_SIGNAL"]:
        bullish_score += 7
        category_scores["momentum"] += 7
        bullish_reasons.append("MACD above signal")
    elif candle["MACD"] < candle["MACD_SIGNAL"]:
        bearish_score += 7
        category_scores["momentum"] += 7
        bearish_reasons.append("MACD below signal")

    if candle["MACD_HIST"] > prior_candle["MACD_HIST"] and candle["MACD_HIST"] > 0:
        bullish_score += 6
        category_scores["momentum"] += 6
        bullish_reasons.append("MACD histogram expanding bullish")
    elif candle["MACD_HIST"] < prior_candle["MACD_HIST"] and candle["MACD_HIST"] < 0:
        bearish_score += 6
        category_scores["momentum"] += 6
        bearish_reasons.append("MACD histogram expanding bearish")

    if relative_volume >= 2:
        bullish_score += 10
        bearish_score += 10
        category_scores["volume"] += 10
        bullish_reasons.append("Relative volume above 2.0x")
        bearish_reasons.append("Relative volume above 2.0x")
    elif relative_volume >= VOLUME_MULTIPLIER:
        bullish_score += 7
        bearish_score += 7
        category_scores["volume"] += 7
        bullish_reasons.append("Volume expansion")
        bearish_reasons.append("Volume expansion")
    elif relative_volume >= 1.1:
        bullish_score += 4
        bearish_score += 4
        category_scores["volume"] += 4
        bullish_reasons.append("Volume above average")
        bearish_reasons.append("Volume above average")

    if volume > prior_candle["Volume"] * 1.25:
        bullish_score += 5
        bearish_score += 5
        category_scores["volume"] += 5
        bullish_reasons.append("Volume spike versus prior candle")
        bearish_reasons.append("Volume spike versus prior candle")

    if volume > avg_volume:
        bullish_score += 5
        bearish_score += 5
        category_scores["volume"] += 5
        bullish_reasons.append("Volume confirms interest")
        bearish_reasons.append("Volume confirms interest")

    atr_expanding = candle["ATR"] > candle["AVG_ATR_20"] if candle["AVG_ATR_20"] else False

    if atr_expanding:
        bullish_score += 8
        bearish_score += 8
        category_scores["volatility"] += 8
        bullish_reasons.append("ATR expanding")
        bearish_reasons.append("ATR expanding")

    if candle["High"] > prior_candle["High"] and candle["Low"] > prior_candle["Low"]:
        bullish_score += 4
        category_scores["volatility"] += 4
        bullish_reasons.append("Intraday range expanding upward")
    elif candle["High"] < prior_candle["High"] and candle["Low"] < prior_candle["Low"]:
        bearish_score += 4
        category_scores["volatility"] += 4
        bearish_reasons.append("Intraday range expanding downward")

    if abs(float(candle["Close"] - candle["Open"])) > float(candle["ATR"]) * 0.35:
        bullish_score += 3
        bearish_score += 3
        category_scores["volatility"] += 3
        bullish_reasons.append("Meaningful candle range")
        bearish_reasons.append("Meaningful candle range")

    if price > prior_20_high * BREAKOUT_BUFFER_UP:
        bullish_score += 12
        category_scores["price_action"] += 12
        bullish_reasons.append("Resistance breakout")
    elif price < prior_20_low * BREAKOUT_BUFFER_DOWN:
        bearish_score += 12
        category_scores["price_action"] += 12
        bearish_reasons.append("Support breakdown")

    if price > candle["VWAP"]:
        bullish_score += 4
        category_scores["price_action"] += 4
        bullish_reasons.append("Price above VWAP")
    elif price < candle["VWAP"]:
        bearish_score += 4
        category_scores["price_action"] += 4
        bearish_reasons.append("Price below VWAP")

    if price > prior_15_high * BREAKOUT_BUFFER_UP:
        bullish_score += 4
        category_scores["price_action"] += 4
        bullish_reasons.append("Breakout above prior 15-min high")
    elif price < prior_15_low * BREAKOUT_BUFFER_DOWN:
        bearish_score += 4
        category_scores["price_action"] += 4
        bearish_reasons.append("Breakdown below prior 15-min low")

    bullish_score = min(bullish_score, 100)
    bearish_score = min(bearish_score, 100)

    if bullish_score >= call_score_threshold and bullish_score > bearish_score:
        signal = "BULLISH SETUP"
        confidence = bullish_score
        reasons = bullish_reasons
        entry = price
        stop = price * (1 - STOP_PERCENT)
        target = price * (1 + TARGET_PERCENT)
        breakeven = price * (1 + BREAKEVEN_TRIGGER)
        bias = "Bullish"

    elif bearish_score >= put_score_threshold and bearish_score > bullish_score:
        signal = "BEARISH SETUP"
        confidence = bearish_score
        reasons = bearish_reasons
        entry = price
        stop = price * (1 + STOP_PERCENT)
        target = price * (1 - TARGET_PERCENT)
        breakeven = price * (1 - BREAKEVEN_TRIGGER)
        bias = "Bearish"

    else:
        signal = "WATCHLIST"
        confidence = max(bullish_score, bearish_score)
        reasons = bullish_reasons if bullish_score >= bearish_score else bearish_reasons
        entry = None
        stop = None
        target = None
        breakeven = None
        bias = "Bullish" if bullish_score > bearish_score else "Bearish" if bearish_score > bullish_score else "Neutral"

    return {
        "symbol": symbol,
        "signal": signal,
        "confidence": confidence,
        "bias": bias,
        "quality": quality_from_score(confidence),
        "price": price,
        "entry": entry,
        "stop": stop,
        "target": target,
        "breakeven": breakeven,
        "bullish_score": bullish_score,
        "bearish_score": bearish_score,
        "call_score": bullish_score,
        "put_score": bearish_score,
        "trend_score": category_scores["trend"],
        "momentum_score": category_scores["momentum"],
        "volume_score": category_scores["volume"],
        "volatility_score": category_scores["volatility"],
        "price_action_score": category_scores["price_action"],
        "relative_volume": relative_volume,
        "atr": float(candle["ATR"]),
        "rsi": float(candle["RSI"]),
        "vwap": float(candle["VWAP"]),
        "ema20": float(candle["EMA20"]),
        "ema50": float(candle["EMA50"]),
        "ema200": float(candle["EMA200"]),
        "macd": float(candle["MACD"]),
        "macd_signal": float(candle["MACD_SIGNAL"]),
        "macd_hist": float(candle["MACD_HIST"]),
        "volume": volume,
        "avg_volume": avg_volume,
        "reasons": reasons,
    }
