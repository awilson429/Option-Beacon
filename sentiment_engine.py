OPTIONS_TERMS = {
    "call",
    "calls",
    "put",
    "puts",
    "strike",
    "expiration",
    "expiry",
    "premium",
    "iv",
    "implied volatility",
    "delta",
    "gamma",
    "theta",
    "dte",
    "contract",
    "contracts",
    "sweep",
    "open interest",
    "0dte",
    "weekly",
}

BULLISH_TERMS = {
    "breakout",
    "buying calls",
    "calls",
    "call debit",
    "green",
    "higher",
    "long",
    "moon",
    "rally",
    "squeeze",
    "support held",
    "upside",
}

BEARISH_TERMS = {
    "breakdown",
    "buying puts",
    "puts",
    "red",
    "rejection",
    "rug pull",
    "short",
    "selloff",
    "selling calls",
    "downside",
    "iv crush",
}


def contains_options_intent(text):
    lowered = (text or "").lower()
    return any(term in lowered for term in OPTIONS_TERMS)


def classify_sentiment(text):
    lowered = (text or "").lower()
    bullish_hits = sum(1 for term in BULLISH_TERMS if term in lowered)
    bearish_hits = sum(1 for term in BEARISH_TERMS if term in lowered)

    if bullish_hits == bearish_hits:
        return {"label": "Neutral", "score": 0.0, "confidence": "Low"}

    raw_score = (bullish_hits - bearish_hits) / max(bullish_hits + bearish_hits, 1)
    score = max(-1.0, min(1.0, raw_score))
    confidence = "High" if abs(score) >= 0.66 else "Medium"

    if score >= 0.66:
        label = "Strongly bullish"
    elif score > 0:
        label = "Bullish"
    elif score <= -0.66:
        label = "Strongly bearish"
    else:
        label = "Bearish"

    return {"label": label, "score": round(score, 2), "confidence": confidence}
