import re
from collections import Counter
from datetime import datetime
from math import isnan


LESSON_STOP_WORDS = {
    "about",
    "after",
    "again",
    "against",
    "and",
    "before",
    "better",
    "could",
    "from",
    "into",
    "next",
    "not",
    "only",
    "should",
    "that",
    "the",
    "then",
    "this",
    "trade",
    "was",
    "when",
    "with",
}


def _clean_text(value, default="Unreviewed"):
    if value is None:
        return default

    try:
        if isnan(value):
            return default
    except TypeError:
        pass

    text = str(value).strip()
    return text if text else default


def _number_or_none(value):
    if value is None:
        return None

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    return None if isnan(number) else number


def _date_or_none(value):
    if value is None:
        return None

    try:
        if isnan(value):
            return None
    except TypeError:
        pass

    text = str(value).strip()
    if not text:
        return None

    for fmt in ("%Y-%m-%d %I:%M:%S %p ET", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass

    return None


def filter_journal_rows(
    journal_rows,
    tickers=None,
    directions=None,
    outcomes=None,
    start_date=None,
    end_date=None,
):
    tickers = set(tickers or [])
    directions = set(directions or [])
    outcomes = set(outcomes or [])
    filtered = []

    for row in journal_rows:
        if tickers and row.get("Ticker") not in tickers:
            continue
        if directions and row.get("Direction") not in directions:
            continue
        if outcomes and _clean_text(row.get("Outcome")) not in outcomes:
            continue

        closed_date = _date_or_none(row.get("Closed"))
        if (start_date or end_date) and closed_date is None:
            continue
        if start_date and closed_date and closed_date < start_date:
            continue
        if end_date and closed_date and closed_date > end_date:
            continue

        filtered.append(row)

    return filtered


def outcome_review_rows(journal_rows):
    outcomes = {}
    for row in journal_rows:
        outcome = _clean_text(row.get("Outcome"))
        pnl = _number_or_none(row.get("Premium P/L"))

        if outcome not in outcomes:
            outcomes[outcome] = {
                "Outcome": outcome,
                "Trades": 0,
                "Wins": 0,
                "Losses": 0,
                "Total P/L": 0,
            }

        outcomes[outcome]["Trades"] += 1
        if pnl is not None:
            outcomes[outcome]["Total P/L"] += pnl
            if pnl > 0:
                outcomes[outcome]["Wins"] += 1
            elif pnl < 0:
                outcomes[outcome]["Losses"] += 1

    rows = []
    for outcome in outcomes.values():
        trades = outcome["Trades"]
        win_rate = round((outcome["Wins"] / trades) * 100, 2) if trades else 0
        rows.append(
            {
                **outcome,
                "Win Rate %": win_rate,
                "Total P/L": round(outcome["Total P/L"], 2),
            }
        )

    return sorted(rows, key=lambda row: row["Trades"], reverse=True)


def _quality_labels(outcome):
    outcome = _clean_text(outcome)

    setup_quality = "Unreviewed"
    management_quality = "Unreviewed"
    rule_discipline = "Rules followed"

    if "Good setup" in outcome:
        setup_quality = "Good setup"
    elif "Bad setup" in outcome:
        setup_quality = "Bad setup"
    elif outcome == "Breakeven":
        setup_quality = "Neutral setup"

    if "good management" in outcome:
        management_quality = "Good management"
    elif "poor management" in outcome:
        management_quality = "Poor management"
    elif "avoided worse loss" in outcome:
        management_quality = "Good management"
    elif outcome == "Breakeven":
        management_quality = "Neutral management"

    if outcome == "Rule break":
        setup_quality = "Unclear setup"
        management_quality = "Rule break"
        rule_discipline = "Rule break"
    elif outcome == "Unreviewed":
        rule_discipline = "Unreviewed"

    return setup_quality, management_quality, rule_discipline


def _grade_bucket(grade, positive_label, negative_label):
    grade = _clean_text(grade)
    if grade in {"A", "B"}:
        return positive_label
    if grade in {"C"}:
        return "Neutral"
    if grade in {"D", "F"}:
        return negative_label
    return None


def _rule_bucket(score):
    score = _number_or_none(score)
    if score is None:
        return None
    if score >= 8:
        return "Rules followed"
    if score >= 5:
        return "Rules mixed"
    return "Rule break"


def review_dashboard_rows(journal_rows):
    buckets = {
        "Setup Quality": Counter(),
        "Management Quality": Counter(),
        "Rule Discipline": Counter(),
    }

    for row in journal_rows:
        fallback_setup, fallback_management, fallback_discipline = _quality_labels(
            row.get("Outcome")
        )
        setup_quality = _grade_bucket(
            row.get("Setup Grade"),
            "Good setup",
            "Bad setup",
        ) or fallback_setup
        management_quality = _grade_bucket(
            row.get("Management Grade"),
            "Good management",
            "Poor management",
        ) or fallback_management
        rule_discipline = _rule_bucket(row.get("Rule Score")) or fallback_discipline
        buckets["Setup Quality"][setup_quality] += 1
        buckets["Management Quality"][management_quality] += 1
        buckets["Rule Discipline"][rule_discipline] += 1

    rows = []
    for category, counter in buckets.items():
        total = sum(counter.values())
        for label, count in counter.most_common():
            percent = round((count / total) * 100, 2) if total else 0
            rows.append(
                {
                    "Review Area": category,
                    "Result": label,
                    "Trades": count,
                    "Share %": percent,
                }
            )

    return rows


def lesson_pattern_rows(journal_rows, limit=10):
    words = Counter()
    for row in journal_rows:
        lesson = _clean_text(row.get("Lessons Learned"), default="")
        for word in re.findall(r"[A-Za-z][A-Za-z']+", lesson.lower()):
            if len(word) > 3 and word not in LESSON_STOP_WORDS:
                words[word] += 1

    return [
        {"Pattern": word, "Mentions": count}
        for word, count in words.most_common(limit)
    ]
