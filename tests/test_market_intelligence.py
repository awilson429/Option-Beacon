import pandas as pd

from market_intelligence import (
    chase_risk,
    confidence_explanation,
    liquidity_quality,
    market_regime,
    sector_strength_rows,
    setup_quality,
    setup_quality_summary,
    setup_momentum_snapshot,
    setup_sector_support,
)


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


def test_setup_momentum_snapshot_detects_improving_score():
    history = pd.DataFrame(
        [
            {
                "timestamp": "2026-07-23 09:45 AM ET",
                "symbol": "SPY",
                "bias": "Bullish",
                "score": "78",
                "signal": "WATCHLIST",
            }
        ]
    )
    result = {
        "symbol": "SPY",
        "bias": "Bullish",
        "confidence": 88,
        "signal": "BULLISH SETUP",
    }

    snapshot = setup_momentum_snapshot(result, history)

    assert snapshot["label"] == "Improving"
    assert snapshot["score_change"] == 10


def test_setup_momentum_snapshot_detects_bias_flip():
    history = pd.DataFrame(
        [
            {
                "timestamp": "2026-07-23 09:45 AM ET",
                "symbol": "QQQ",
                "bias": "Bearish",
                "score": "85",
                "signal": "BEARISH SETUP",
            }
        ]
    )
    result = {
        "symbol": "QQQ",
        "bias": "Bullish",
        "confidence": 86,
        "signal": "BULLISH SETUP",
    }

    snapshot = setup_momentum_snapshot(result, history)

    assert snapshot["label"] == "Bias flipped"
    assert snapshot["bias_changed"] is True


def test_setup_sector_support_detects_aligned_technology_setup():
    result = {"symbol": "NVDA", "bias": "Bullish", "confidence": 88}
    latest_results = {
        "XLK": {"bias": "Bullish", "confidence": 84},
    }

    support = setup_sector_support(result, latest_results)

    assert support["status"] == "Aligned"
    assert support["sector_etf"] == "XLK"
    assert "Technology" in support["detail"]


def test_setup_sector_support_detects_against_sector():
    result = {"symbol": "JPM", "bias": "Bullish", "confidence": 82}
    latest_results = {
        "XLF": {"bias": "Bearish", "confidence": 78},
    }

    support = setup_sector_support(result, latest_results)

    assert support["status"] == "Against"
    assert support["sector_bias"] == "Bearish"


def test_sector_strength_rows_sorts_by_score():
    latest_results = {
        "XLK": {"bias": "Bullish", "confidence": 72, "relative_volume": 1.2, "reasons": ["Tech reason"]},
        "XLF": {"bias": "Bearish", "confidence": 91, "relative_volume": 1.5, "reasons": ["Financial reason"]},
    }

    rows = sector_strength_rows(latest_results)

    assert rows[0]["ETF"] == "XLF"
    assert rows[0]["Sector"] == "Financials"


def test_liquidity_quality_grades_active_liquid_symbol():
    quality = liquidity_quality(
        {
            "price": 185,
            "volume": 2_500_000,
            "avg_volume": 25_000_000,
            "relative_volume": 1.7,
        }
    )

    assert quality["label"] == "Strong"
    assert quality["score"] >= 80


def test_setup_quality_rewards_aligned_low_chase_setup():
    result = {
        "symbol": "NVDA",
        "bias": "Bullish",
        "confidence": 88,
        "price": 185,
        "volume": 2_500_000,
        "avg_volume": 25_000_000,
        "relative_volume": 1.7,
        "atr": 2,
        "trade_plan": {"trigger_price": 184.7},
    }
    latest_results = {
        "SPY": {"bias": "Bullish", "confidence": 86},
        "QQQ": {"bias": "Bullish", "confidence": 84},
        "IWM": {"bias": "Bullish", "confidence": 82},
        "DIA": {"bias": "Bearish", "confidence": 75},
        "XLK": {"bias": "Bullish", "confidence": 83},
    }

    quality = setup_quality(result, latest_results)

    assert quality["grade"] in ["A", "B"]
    assert quality["market_support"] == "Aligned"
    assert quality["sector_support"] == "Aligned"


def test_setup_quality_penalizes_chasing_and_sector_against():
    result = {
        "symbol": "JPM",
        "bias": "Bullish",
        "confidence": 91,
        "price": 105,
        "volume": 80_000,
        "avg_volume": 500_000,
        "relative_volume": 0.5,
        "atr": 2,
        "trade_plan": {"trigger_price": 100},
    }
    latest_results = {
        "SPY": {"bias": "Bearish", "confidence": 80},
        "QQQ": {"bias": "Bearish", "confidence": 82},
        "IWM": {"bias": "Bearish", "confidence": 78},
        "DIA": {"bias": "Bearish", "confidence": 81},
        "XLF": {"bias": "Bearish", "confidence": 85},
    }

    quality = setup_quality(result, latest_results)

    assert quality["score"] < result["confidence"]
    assert quality["sector_support"] == "Against"
    assert quality["chase_risk"] == "High"


def test_setup_quality_summary_explains_low_quality_reason():
    result = {
        "symbol": "JPM",
        "bias": "Bullish",
        "confidence": 91,
        "price": 105,
        "volume": 80_000,
        "avg_volume": 500_000,
        "relative_volume": 0.5,
        "atr": 2,
        "trade_plan": {"trigger_price": 100},
    }
    latest_results = {"XLF": {"bias": "Bearish", "confidence": 85}}

    summary = setup_quality_summary(result, latest_results)

    assert "entry location" in summary or "sector" in summary
