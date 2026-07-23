from datetime import date

from trade_journal import (
    filter_journal_rows,
    lesson_pattern_rows,
    outcome_review_rows,
    review_dashboard_rows,
    review_trend_rows,
)


def test_outcome_review_rows_groups_closed_trades():
    rows = [
        {
            "Outcome": "Good setup / good management",
            "Premium P/L": 150,
        },
        {
            "Outcome": "Good setup / good management",
            "Premium P/L": -50,
        },
        {
            "Outcome": "Rule break",
            "Premium P/L": -100,
        },
    ]

    review = outcome_review_rows(rows)
    good_setup = next(
        row for row in review if row["Outcome"] == "Good setup / good management"
    )

    assert good_setup["Trades"] == 2
    assert good_setup["Wins"] == 1
    assert good_setup["Losses"] == 1
    assert good_setup["Win Rate %"] == 50.0
    assert good_setup["Total P/L"] == 100


def test_lesson_pattern_rows_counts_common_keywords():
    rows = [
        {"Lessons Learned": "Wait for confirmation and respect the stop."},
        {"Lessons Learned": "Wait for volume confirmation before entry."},
    ]

    patterns = lesson_pattern_rows(rows)

    assert {"Pattern": "confirmation", "Mentions": 2} in patterns
    assert {"Pattern": "wait", "Mentions": 2} in patterns


def test_outcome_review_rows_ignores_missing_pnl():
    rows = [
        {
            "Outcome": None,
            "Premium P/L": None,
        }
    ]

    review = outcome_review_rows(rows)

    assert review == [
        {
            "Outcome": "Unreviewed",
            "Trades": 1,
            "Wins": 0,
            "Losses": 0,
            "Total P/L": 0,
            "Win Rate %": 0.0,
        }
    ]


def test_review_dashboard_rows_separates_trade_quality_lenses():
    rows = [
        {"Outcome": "Good setup / poor management"},
        {"Outcome": "Bad setup / avoided worse loss"},
        {"Outcome": "Rule break"},
    ]

    dashboard = review_dashboard_rows(rows)

    assert {
        "Review Area": "Setup Quality",
        "Result": "Good setup",
        "Trades": 1,
        "Share %": 33.33,
    } in dashboard
    assert {
        "Review Area": "Management Quality",
        "Result": "Poor management",
        "Trades": 1,
        "Share %": 33.33,
    } in dashboard
    assert {
        "Review Area": "Rule Discipline",
        "Result": "Rule break",
        "Trades": 1,
        "Share %": 33.33,
    } in dashboard


def test_review_dashboard_rows_prefers_structured_review_fields():
    rows = [
        {
            "Outcome": "Good setup / good management",
            "Setup Grade": "D",
            "Management Grade": "A",
            "Rule Score": 4,
        }
    ]

    dashboard = review_dashboard_rows(rows)

    assert {
        "Review Area": "Setup Quality",
        "Result": "Bad setup",
        "Trades": 1,
        "Share %": 100.0,
    } in dashboard
    assert {
        "Review Area": "Management Quality",
        "Result": "Good management",
        "Trades": 1,
        "Share %": 100.0,
    } in dashboard
    assert {
        "Review Area": "Rule Discipline",
        "Result": "Rule break",
        "Trades": 1,
        "Share %": 100.0,
    } in dashboard


def test_filter_journal_rows_filters_by_ticker_direction_outcome_and_date():
    rows = [
        {
            "Ticker": "SPY",
            "Direction": "Bullish",
            "Outcome": "Good setup / good management",
            "Closed": "2026-07-20 03:30:00 PM ET",
        },
        {
            "Ticker": "QQQ",
            "Direction": "Bearish",
            "Outcome": "Rule break",
            "Closed": "2026-07-21 03:30:00 PM ET",
        },
    ]

    filtered = filter_journal_rows(
        rows,
        tickers=["SPY"],
        directions=["Bullish"],
        outcomes=["Good setup / good management"],
        start_date=date(2026, 7, 20),
        end_date=date(2026, 7, 20),
    )

    assert filtered == [rows[0]]


def test_filter_journal_rows_excludes_missing_dates_when_date_filter_is_active():
    rows = [
        {
            "Ticker": "SPY",
            "Direction": "Bullish",
            "Outcome": "Unreviewed",
            "Closed": None,
        }
    ]

    filtered = filter_journal_rows(rows, start_date=date(2026, 7, 20))

    assert filtered == []


def test_review_trend_rows_groups_review_quality_by_month():
    rows = [
        {
            "Closed": "2026-07-20 03:30:00 PM ET",
            "Outcome": "Good setup / good management",
            "Setup Grade": "A",
            "Management Grade": "B",
            "Rule Score": 9,
            "Premium P/L": 150,
        },
        {
            "Closed": "2026-07-21 03:30:00 PM ET",
            "Outcome": "Rule break",
            "Setup Grade": "D",
            "Management Grade": "F",
            "Rule Score": 3,
            "Premium P/L": -50,
        },
    ]

    trend = review_trend_rows(rows)

    assert trend == [
        {
            "Period": "2026-07",
            "Trades": 2,
            "Good Setup %": 50.0,
            "Good Management %": 50.0,
            "Rules Followed %": 50.0,
            "Avg Rule Score": 6.0,
            "Total P/L": 100.0,
        }
    ]
