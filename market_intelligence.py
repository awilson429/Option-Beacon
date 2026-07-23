def _number(value, default=0):
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _direction_score(result, direction):
    if direction == "Bullish":
        return _number(result.get("bullish_score"))
    if direction == "Bearish":
        return _number(result.get("bearish_score"))
    return _number(result.get("confidence"))


SECTOR_ETF_NAMES = {
    "XLK": "Technology",
    "XLY": "Consumer Discretionary",
    "XLF": "Financials",
    "XLV": "Health Care",
    "XLI": "Industrials",
    "XLE": "Energy",
    "XLP": "Consumer Staples",
    "XLU": "Utilities",
    "XLC": "Communication Services",
    "XLRE": "Real Estate",
    "XLB": "Materials",
}

SYMBOL_SECTOR_ETF = {
    "AAPL": "XLK",
    "AMD": "XLK",
    "AVGO": "XLK",
    "CRM": "XLK",
    "INTC": "XLK",
    "MSFT": "XLK",
    "MU": "XLK",
    "NVDA": "XLK",
    "ORCL": "XLK",
    "QCOM": "XLK",
    "SMCI": "XLK",
    "SNOW": "XLK",
    "ABNB": "XLY",
    "AMZN": "XLY",
    "DKNG": "XLY",
    "HD": "XLY",
    "NKE": "XLY",
    "RIVN": "XLY",
    "ROKU": "XLY",
    "TSLA": "XLY",
    "UBER": "XLY",
    "BABA": "XLY",
    "BAC": "XLF",
    "C": "XLF",
    "GS": "XLF",
    "JPM": "XLF",
    "MS": "XLF",
    "ABBV": "XLV",
    "BMY": "XLV",
    "LLY": "XLV",
    "MRK": "XLV",
    "PFE": "XLV",
    "UNH": "XLV",
    "BA": "XLI",
    "CAT": "XLI",
    "FDX": "XLI",
    "GE": "XLI",
    "CVX": "XLE",
    "SLB": "XLE",
    "USO": "XLE",
    "XOM": "XLE",
    "KO": "XLP",
    "PEP": "XLP",
    "WMT": "XLP",
    "T": "XLC",
    "DIS": "XLC",
    "GOOGL": "XLC",
    "META": "XLC",
    "NFLX": "XLC",
    "BIDU": "XLC",
    "COIN": "XLF",
    "PYPL": "XLF",
    "SHOP": "XLK",
    "SOFI": "XLF",
    "PLTR": "XLK",
    "MSTR": "XLK",
    "RBLX": "XLC",
    "F": "XLY",
}


def sector_for_symbol(symbol):
    symbol = str(symbol or "").upper()
    if symbol in SECTOR_ETF_NAMES:
        return symbol
    return SYMBOL_SECTOR_ETF.get(symbol)


def setup_sector_support(result, latest_results):
    symbol = result.get("symbol")
    direction = result.get("bias", "Neutral")
    sector_etf = sector_for_symbol(symbol)

    if not sector_etf:
        return {
            "status": "Unknown",
            "sector_etf": "",
            "sector_name": "Unmapped",
            "sector_bias": "Unknown",
            "sector_score": 0,
            "detail": "Sector context is not mapped for this symbol yet.",
        }

    sector_result = latest_results.get(sector_etf) or {}
    sector_bias = sector_result.get("bias", "Unknown")
    sector_score = _number(sector_result.get("confidence"))
    sector_name = SECTOR_ETF_NAMES.get(sector_etf, sector_etf)

    if not sector_result:
        return {
            "status": "Unavailable",
            "sector_etf": sector_etf,
            "sector_name": sector_name,
            "sector_bias": "Unknown",
            "sector_score": 0,
            "detail": f"{sector_etf} has not been scanned yet.",
        }

    if symbol == sector_etf:
        status = "Benchmark"
        detail = f"{sector_etf} is the {sector_name} benchmark."
    elif direction in ["Bullish", "Bearish"] and sector_bias == direction and sector_score >= 70:
        status = "Aligned"
        detail = f"{sector_name} ({sector_etf}) supports the {direction.lower()} setup."
    elif direction in ["Bullish", "Bearish"] and sector_bias in ["Bullish", "Bearish"] and sector_bias != direction and sector_score >= 70:
        status = "Against"
        detail = f"{sector_name} ({sector_etf}) is leaning {sector_bias.lower()}, against this setup."
    else:
        status = "Mixed"
        detail = f"{sector_name} ({sector_etf}) is not strongly confirming this setup."

    return {
        "status": status,
        "sector_etf": sector_etf,
        "sector_name": sector_name,
        "sector_bias": sector_bias,
        "sector_score": round(sector_score, 1),
        "detail": detail,
    }


def sector_strength_rows(latest_results):
    rows = []
    for sector_etf, sector_name in SECTOR_ETF_NAMES.items():
        result = latest_results.get(sector_etf)
        if not result or result.get("signal") == "DATA UNAVAILABLE":
            continue

        rows.append(
            {
                "Sector": sector_name,
                "ETF": sector_etf,
                "Bias": result.get("bias", "Neutral"),
                "Score": int(_number(result.get("confidence"))),
                "RVol": round(_number(result.get("relative_volume")), 2),
                "Primary Reason": (result.get("reasons") or [""])[0],
            }
        )

    rows.sort(key=lambda row: row["Score"], reverse=True)
    return rows


def market_regime(latest_results):
    market_symbols = [
        result for symbol, result in latest_results.items()
        if symbol in ["SPY", "QQQ", "IWM", "DIA"] and result
    ]

    if not market_symbols:
        return {
            "regime": "Unknown",
            "support": "Waiting for market data",
            "best_strategy": "Wait for SPY/QQQ context.",
            "bullish_count": 0,
            "bearish_count": 0,
            "average_score": 0,
        }

    bullish_count = sum(1 for result in market_symbols if result.get("bias") == "Bullish")
    bearish_count = sum(1 for result in market_symbols if result.get("bias") == "Bearish")
    average_score = sum(_number(result.get("confidence")) for result in market_symbols) / len(market_symbols)
    high_conviction = average_score >= 80

    if bullish_count >= 3 and high_conviction:
        regime = "Bullish trend"
        support = "Market support favors bullish continuation."
        best_strategy = "Favor bullish pullbacks and clean breakouts."
    elif bearish_count >= 3 and high_conviction:
        regime = "Bearish trend"
        support = "Market support favors bearish continuation."
        best_strategy = "Favor bearish breakdowns and failed bounces."
    elif bullish_count > bearish_count:
        regime = "Bullish but mixed"
        support = "Market leans bullish, but confirmation is not broad."
        best_strategy = "Be selective and avoid late entries."
    elif bearish_count > bullish_count:
        regime = "Bearish but mixed"
        support = "Market leans bearish, but confirmation is not broad."
        best_strategy = "Be selective and avoid late entries."
    else:
        regime = "Choppy"
        support = "Market direction is mixed."
        best_strategy = "Wait for cleaner confirmation or take smaller targets."

    return {
        "regime": regime,
        "support": support,
        "best_strategy": best_strategy,
        "bullish_count": bullish_count,
        "bearish_count": bearish_count,
        "average_score": round(average_score, 1),
    }


def setup_market_support(result, latest_results):
    direction = result.get("bias", "Neutral")
    regime = market_regime(latest_results)

    if direction == "Bullish" and regime["bullish_count"] >= 2:
        return "Aligned"
    if direction == "Bearish" and regime["bearish_count"] >= 2:
        return "Aligned"
    if regime["regime"] in ["Choppy", "Unknown"]:
        return "Mixed"
    return "Against"


def chase_risk(result):
    direction = result.get("bias", "Neutral")
    price = _number(result.get("price"))
    atr = _number(result.get("atr"))
    plan = result.get("trade_plan") or {}
    trigger = _number(plan.get("trigger_price") or result.get("entry") or result.get("price"))

    if not price or not trigger or not atr:
        return {
            "label": "Unknown",
            "distance_atr": None,
            "reason": "Not enough data to measure chase risk.",
        }

    if direction == "Bullish":
        distance = price - trigger
    elif direction == "Bearish":
        distance = trigger - price
    else:
        distance = abs(price - trigger)

    distance_atr = round(distance / atr, 2) if atr else 0

    if distance_atr >= 0.75:
        label = "High"
        reason = f"Price is {distance_atr} ATR beyond the preferred trigger."
    elif distance_atr >= 0.35:
        label = "Moderate"
        reason = f"Price is {distance_atr} ATR beyond the trigger. Entry discipline matters."
    elif distance_atr >= -0.25:
        label = "Low"
        reason = "Price is near the preferred trigger area."
    else:
        label = "Waiting"
        reason = "Price has not reached the preferred trigger area yet."

    return {
        "label": label,
        "distance_atr": distance_atr,
        "reason": reason,
    }


def missing_confirmations(result, latest_results=None):
    latest_results = latest_results or {}
    missing = []
    direction = result.get("bias", "Neutral")

    if _number(result.get("trend_score")) < 18:
        missing.append("trend alignment")
    if _number(result.get("momentum_score")) < 14:
        missing.append("momentum confirmation")
    if _number(result.get("volume_score")) < 14:
        missing.append("strong relative volume")
    if _number(result.get("price_action_score")) < 12:
        missing.append("clean breakout/breakdown")

    support = setup_market_support(result, latest_results)
    if support != "Aligned" and direction in ["Bullish", "Bearish"]:
        missing.append("market support")

    sector = setup_sector_support(result, latest_results)
    if sector["status"] not in ["Aligned", "Benchmark"] and direction in ["Bullish", "Bearish"]:
        missing.append("sector support")

    chase = chase_risk(result)
    if chase["label"] in ["Moderate", "High"]:
        missing.append("better entry location")

    return missing[:5]


def confidence_explanation(result, latest_results=None):
    missing = missing_confirmations(result, latest_results)
    if not missing:
        return "Most major confirmations are aligned."
    return "Missing: " + ", ".join(missing) + "."


def _latest_history_row(history, symbol):
    if history is None or history.empty or "symbol" not in history.columns:
        return None

    rows = history[history["symbol"] == symbol]
    if rows.empty:
        return None
    return rows.iloc[-1].to_dict()


def setup_momentum_snapshot(result, history=None):
    symbol = result.get("symbol")
    current_score = _number(result.get("confidence"))
    current_bias = result.get("bias", "Neutral")
    current_signal = result.get("signal", "WATCHLIST")
    previous = _latest_history_row(history, symbol)

    if not previous:
        return {
            "label": "New read",
            "detail": "No recent high-score history for comparison yet.",
            "score_change": None,
            "bias_changed": False,
        }

    previous_score = _number(previous.get("score"))
    previous_bias = previous.get("bias", "Neutral")
    previous_signal = previous.get("signal", "WATCHLIST")
    score_change = round(current_score - previous_score, 1)
    bias_changed = bool(previous_bias and previous_bias != current_bias)
    signal_changed = bool(previous_signal and previous_signal != current_signal)

    if bias_changed:
        label = "Bias flipped"
        detail = f"Previous bias was {previous_bias}; current bias is {current_bias}."
    elif score_change >= 8:
        label = "Improving"
        detail = f"Score improved by {score_change:g} points since the last high-score read."
    elif score_change <= -8:
        label = "Weakening"
        detail = f"Score faded by {abs(score_change):g} points since the last high-score read."
    elif signal_changed:
        label = "State changed"
        detail = f"Signal changed from {previous_signal} to {current_signal}."
    else:
        label = "Stable"
        detail = "Current read is similar to the last high-score snapshot."

    return {
        "label": label,
        "detail": detail,
        "score_change": score_change,
        "bias_changed": bias_changed,
    }
