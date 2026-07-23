from datetime import datetime
from zoneinfo import ZoneInfo

from after_hours import (
    after_hours_focus_rows,
    compact_summary,
    format_news_time,
    normalize_earnings,
    normalize_news,
    normalize_report_time,
)


def test_normalize_report_time_labels():
    assert normalize_report_time("bmo") == "Before Open"
    assert normalize_report_time("amc") == "After Close"
    assert normalize_report_time("") == "TBD"


def test_normalize_earnings_handles_finnhub_payload():
    payload = {
        "earningsCalendar": [
            {
                "date": "2026-07-24",
                "symbol": "NVDA",
                "hour": "amc",
                "epsEstimate": 1.23,
                "revenueEstimate": 45600000000,
            }
        ]
    }

    rows = normalize_earnings(payload)

    assert rows == [
        {
            "Date": "2026-07-24",
            "Symbol": "NVDA",
            "Report Time": "After Close",
            "EPS Est": 1.23,
            "Revenue Est": 45600000000,
        }
    ]


def test_normalize_news_formats_current_day_time():
    now = datetime(2026, 7, 23, 16, 30, tzinfo=ZoneInfo("America/New_York"))
    timestamp = int(datetime(2026, 7, 23, 15, 42, tzinfo=ZoneInfo("America/New_York")).timestamp())

    rows = normalize_news(
        [
            {
                "datetime": timestamp,
                "source": "Example",
                "headline": "Market breadth improves after the close",
                "summary": "A concise update.",
                "url": "https://example.com/news",
            }
        ],
        now=now,
    )

    assert rows[0]["Time"] == "3:42 PM ET"
    assert rows[0]["Headline"] == "Market breadth improves after the close"


def test_compact_summary_truncates_long_text():
    assert compact_summary("x" * 200, max_chars=10) == "xxxxxxx..."


def test_after_hours_focus_rows_keeps_high_quality_setups():
    rows = after_hours_focus_rows(
        {
            "SPY": {
                "bias": "Bullish",
                "confidence": 88,
                "entry_timing": "Entry zone active",
                "trade_plan": {
                    "entry_zone_low": 500,
                    "entry_zone_high": 501,
                    "technical_stop": 498,
                },
            },
            "QQQ": {"bias": "Neutral", "confidence": 99},
            "AMD": {"bias": "Bearish", "confidence": 79},
        }
    )

    assert len(rows) == 1
    assert rows[0]["Symbol"] == "SPY"
    assert rows[0]["Entry Zone"] == "$500.00-$501.00"
