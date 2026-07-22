from sentiment_engine import classify_sentiment, contains_options_intent
from ticker_extraction import extract_tickers


def test_extracts_cashtags_and_aliases():
    assert extract_tickers("$NVDA calls and Nvidia breakout") == ["NVDA"]


def test_ignores_common_false_positive_words():
    assert extract_tickers("Can it go up now?") == []


def test_detects_options_intent():
    assert contains_options_intent("Buying SPY 0DTE calls")


def test_classifies_basic_trading_sentiment():
    result = classify_sentiment("NVDA breakout, buying calls")
    assert result["score"] > 0
