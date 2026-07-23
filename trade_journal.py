import re
from collections import Counter
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
