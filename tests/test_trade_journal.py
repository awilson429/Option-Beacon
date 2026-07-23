from trade_journal import (
    lesson_pattern_rows,
    outcome_review_rows,
    review_dashboard_rows,
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
