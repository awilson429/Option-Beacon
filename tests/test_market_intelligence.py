from market_intelligence import chase_risk, confidence_explanation, market_regime


def test_market_regime_detects_bullish_trend():
    latest_results = {
        "SPY": {"bias": "Bullish", "confidence": 88},
        "QQQ": {"bias": "Bullish", "confidence": 90},
        "IWM": {"bias": "Bullish", "confidence": 84},
        "DIA": {"bias": "Bearish", "confidence": 80},
    }

    regime = market_regime(latest_results)

    assert regime["regime"] == "Bullish trend"
    assert regime["bullish_count"] == 3


def test_chase_risk_flags_extended_bullish_entry():
    result = {
        "bias": "Bullish",
        "price": 102,
        "atr": 2,
        "trade_plan": {"trigger_price": 100},
    }

    risk = chase_risk(result)

    assert risk["label"] == "High"
    assert risk["distance_atr"] == 1


def test_confidence_explanation_lists_missing_confirmations():
    result = {
        "bias": "Bullish",
        "trend_score": 20,
        "momentum_score": 10,
        "volume_score": 8,
        "price_action_score": 14,
        "price": 100,
        "atr": 2,
        "trade_plan": {"trigger_price": 100},
    }

    explanation = confidence_explanation(result, {})

    assert "momentum confirmation" in explanation
    assert "strong relative volume" in explanation
