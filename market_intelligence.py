import pandas as pd


def _score_value(result, key):
    try:
        return int(result.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0


def _trend_direction(result):
    if not result or result.get("signal") == "DATA UNAVAILABLE":
        return "Unavailable"

    price = result.get("price")
    ema20 = result.get("ema20")
    ema50 = result.get("ema50")
    ema200 = result.get("ema200")
    vwap = result.get("vwap")

    if not all([price, ema20, ema50, ema200, vwap]):
        return result.get("bias", "Neutral")

    if price > vwap and price > ema20 > ema50:
        return "Bullish"
    if price < vwap and price < ema20 < ema50:
        return "Bearish"
    if ema20 > ema50 > ema200:
        return "Risk-on"
    if ema20 < ema50 < ema200:
        return "Risk-off"
    return "Range-bound"


def market_regime(latest_results):
    spy = latest_results.get("SPY", {})
    qqq = latest_results.get("QQQ", {})
    spy_trend = _trend_direction(spy)
    qqq_trend = _trend_direction(qqq)

    avg_atr_expansion = []
    for result in latest_results.values():
        atr = result.get("atr") if result else None
        if atr:
            avg_atr_expansion.append(float(atr))

    if spy_trend == "Bullish" and qqq_trend == "Bullish":
        return "Bullish trend"
    if spy_trend == "Bearish" and qqq_trend == "Bearish":
        return "Bearish trend"
    if spy_trend == "Risk-on" or qqq_trend == "Risk-on":
        return "Risk-on"
    if spy_trend == "Risk-off" or qqq_trend == "Risk-off":
        return "Risk-off"
    return "Range-bound"


def build_market_overview(latest_results, market_open, refreshed_at):
    valid_results = {
        symbol: result
        for symbol, result in latest_results.items()
        if result and result.get("signal") != "DATA UNAVAILABLE" and result.get("price")
    }

    above_vwap = [
        symbol
        for symbol, result in valid_results.items()
        if result.get("vwap") and result.get("price", 0) > result.get("vwap")
    ]
    breadth = round((len(above_vwap) / len(valid_results)) * 100) if valid_results else 0

    ranked_strength = sorted(
        valid_results.items(),
        key=lambda item: _score_value(item[1], "bullish_score")
        - _score_value(item[1], "bearish_score"),
        reverse=True,
    )

    strongest = ranked_strength[0][0] if ranked_strength else "N/A"
    weakest = ranked_strength[-1][0] if ranked_strength else "N/A"

    waiting = any(
        result.get("signal") == "WAITING FOR CANDLE"
        for result in latest_results.values()
        if result
    )

    return {
        "SPY Trend": _trend_direction(latest_results.get("SPY")),
        "QQQ Trend": _trend_direction(latest_results.get("QQQ")),
        "Market Regime": market_regime(latest_results),
        "Breadth": f"{breadth}% above VWAP",
        "Strongest": strongest,
        "Weakest": weakest,
        "Scanner Status": "Waiting for candle" if market_open and waiting else "Active" if market_open else "Market closed",
        "Last Refresh": refreshed_at,
    }


def build_trending_options_rows(latest_results):
    rows = []
    for symbol, result in latest_results.items():
        if not result or result.get("signal") == "DATA UNAVAILABLE":
            continue

        bullish_score = _score_value(result, "bullish_score")
        bearish_score = _score_value(result, "bearish_score")
        score = max(bullish_score, bearish_score)
        direction = "Bullish" if bullish_score > bearish_score else "Bearish" if bearish_score > bullish_score else "Mixed"
        rel_volume = result.get("relative_volume", 0) or 0
        price = result.get("price")
        vwap = result.get("vwap")
        trend = _trend_direction(result)

        if direction == "Bullish" and price and vwap and price > vwap:
            confirmation = "Market confirmed"
        elif direction == "Bearish" and price and vwap and price < vwap:
            confirmation = "Market confirmed"
        elif price and vwap:
            confirmation = "Diverging"
        else:
            confirmation = "Insufficient data"

        buzz_score = min(100, round((score * 0.7) + (min(rel_volume, 3) / 3 * 30)))

        rows.append(
            {
                "Ticker": symbol,
                "Buzz Score": buzz_score,
                "Mentions": "Provider pending",
                "Mention Change": "Provider pending",
                "Sentiment": direction,
                "Confidence": result.get("quality", "Developing"),
                "Call/Put Talk": "Provider pending",
                "Options Volume": "Provider pending",
                "Price": round(price, 2) if price else None,
                "Relative Volume": f"{rel_volume:.2f}x",
                "Trend": trend,
                "Confirmation": confirmation,
            }
        )

    rows = sorted(rows, key=lambda row: row["Buzz Score"], reverse=True)
    for rank, row in enumerate(rows, start=1):
        row["Rank"] = rank

    columns = [
        "Rank",
        "Ticker",
        "Buzz Score",
        "Mentions",
        "Mention Change",
        "Sentiment",
        "Confidence",
        "Call/Put Talk",
        "Options Volume",
        "Price",
        "Relative Volume",
        "Trend",
        "Confirmation",
    ]
    return pd.DataFrame(rows, columns=columns)


def signal_explanation(result):
    if not result:
        return {
            "supporting": ["No scanner data available."],
            "risks": ["Market data provider did not return enough candles."],
        }

    reasons = result.get("reasons") or ["No strong setup yet."]
    risks = []
    bias = result.get("bias", "Neutral")
    rsi = result.get("rsi")
    relative_volume = result.get("relative_volume")
    price = result.get("price")
    vwap = result.get("vwap")

    if bias == "Bullish" and price and vwap and price < vwap:
        risks.append("Bullish score is not confirmed by VWAP.")
    if bias == "Bearish" and price and vwap and price > vwap:
        risks.append("Bearish score is not confirmed by VWAP.")
    if rsi and rsi >= 70:
        risks.append("RSI is elevated, so upside may be crowded.")
    if rsi and rsi <= 30:
        risks.append("RSI is deeply oversold, so downside may be stretched.")
    if relative_volume is not None and relative_volume < 1:
        risks.append("Relative volume is below average.")
    if result.get("signal") == "WATCHLIST":
        risks.append("Setup score has not reached the active alert threshold.")

    if not risks:
        risks.append("No major scanner risk flag from current price, volume, and momentum checks.")

    return {"supporting": reasons, "risks": risks}
