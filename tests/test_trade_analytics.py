import math
from datetime import datetime, timedelta, timezone

from signal_history import create_trade_record, rewrite_trade_outcomes
from trade_analytics import analyze_trade_outcomes, confidence_bucket


START = datetime(2026, 7, 27, 14, 0, tzinfo=timezone.utc)


def outcome(
    realized_return=2,
    *,
    symbol="SPY",
    setup="Bullish breakout",
    direction="Bullish",
    confidence=85,
    exit_reason="TARGET_1",
    hold_minutes=30,
    mfe=3,
    mae=-1,
):
    record = create_trade_record(
        symbol=symbol,
        direction=direction,
        setup=setup,
        confidence=confidence,
        entry=100,
        stop=95,
        target_1=103,
        target_2=106,
        target_3=109,
        timestamp=START,
        entry_time=START,
    )
    record.exit_time = START + timedelta(minutes=hold_minutes)
    record.exit_reason = exit_reason
    record.realized_return = realized_return
    record.hold_minutes = hold_minutes
    record.max_favorable_excursion = mfe
    record.max_adverse_excursion = mae
    return record


def test_empty_input():
    analytics = analyze_trade_outcomes([])
    overall = analytics["overall"]

    assert overall["total_signals"] == 0
    assert overall["entered_trades"] == 0
    assert overall["closed_trades"] == 0
    assert overall["wins"] == 0
    assert overall["win_rate"] is None
    assert overall["average_return"] is None
    assert analytics["by_symbol"] == []


def test_default_metrics_use_closed_records_only():
    open_record = outcome()
    open_record.exit_time = None
    open_record.exit_reason = None
    open_record.realized_return = 10

    overall = analyze_trade_outcomes([open_record])["overall"]

    assert overall["total_signals"] == 1
    assert overall["entered_trades"] == 1
    assert overall["closed_trades"] == 0
    assert overall["wins"] == 0


def test_wins_losses_and_breakeven_handling():
    overall = analyze_trade_outcomes(
        [outcome(4), outcome(-2, exit_reason="STOP"), outcome(0, exit_reason="TIME_EXIT")]
    )["overall"]

    assert overall["wins"] == 1
    assert overall["losses"] == 1
    assert overall["breakeven"] == 1
    assert overall["win_rate"] == 50
    assert overall["average_winner"] == 4
    assert overall["average_loser"] == -2


def test_profit_factor():
    overall = analyze_trade_outcomes([outcome(4), outcome(2), outcome(-3)])["overall"]

    assert overall["profit_factor"] == 2


def test_expectancy_and_median_return():
    overall = analyze_trade_outcomes([outcome(4), outcome(-2), outcome(1)])["overall"]

    assert overall["expectancy"] == 1
    assert overall["average_return"] == 1
    assert overall["median_return"] == 1


def test_never_triggered_is_counted_but_excluded_from_return_metrics():
    never_triggered = outcome(
        99,
        exit_reason="NEVER_TRIGGERED",
        hold_minutes=60,
    )
    never_triggered.entry_time = None

    overall = analyze_trade_outcomes([outcome(2), never_triggered])["overall"]

    assert overall["total_signals"] == 2
    assert overall["closed_trades"] == 2
    assert overall["never_triggered"] == 1
    assert overall["wins"] == 1
    assert overall["average_return"] == 2


def test_time_exit_counting():
    overall = analyze_trade_outcomes(
        [outcome(1, exit_reason="TIME_EXIT"), outcome(2)]
    )["overall"]

    assert overall["time_exits"] == 1


def test_target_and_stop_counts():
    records = [
        outcome(1, exit_reason="TARGET_1"),
        outcome(2, exit_reason="TARGET_2"),
        outcome(3, exit_reason="TARGET_3"),
        outcome(-1, exit_reason="STOP"),
    ]

    overall = analyze_trade_outcomes(records)["overall"]

    assert overall["target_1_hits"] == 1
    assert overall["target_2_hits"] == 1
    assert overall["target_3_hits"] == 1
    assert overall["stop_hits"] == 1


def test_average_mfe_mae_and_hold_time_ignore_missing_values():
    records = [
        outcome(2, hold_minutes=20, mfe=5, mae=-1),
        outcome(-1, hold_minutes=40, mfe=None, mae=-3),
    ]

    overall = analyze_trade_outcomes(records)["overall"]

    assert overall["average_hold_minutes"] == 30
    assert overall["average_mfe"] == 5
    assert overall["average_mae"] == -2


def test_grouped_analytics_by_symbol():
    analytics = analyze_trade_outcomes(
        [outcome(2, symbol="SPY"), outcome(-1, symbol="QQQ")]
    )

    groups = {row["group"]: row for row in analytics["by_symbol"]}
    assert groups["SPY"]["wins"] == 1
    assert groups["QQQ"]["losses"] == 1


def test_grouped_analytics_by_setup():
    analytics = analyze_trade_outcomes(
        [
            outcome(2, setup="Breakout"),
            outcome(-1, setup="Breakdown", direction="Bearish"),
        ]
    )

    groups = {row["group"]: row for row in analytics["by_setup"]}
    assert groups["Breakout"]["average_return"] == 2
    assert groups["Breakdown"]["expectancy"] == -1


def test_grouped_analytics_by_direction():
    analytics = analyze_trade_outcomes(
        [outcome(2), outcome(-1, direction="Bearish")]
    )

    groups = {row["group"]: row for row in analytics["by_direction"]}
    assert groups["Bullish"]["win_rate"] == 100
    assert groups["Bearish"]["win_rate"] == 0


def test_confidence_bucket_boundaries():
    expected = {
        0: "0-69",
        69: "0-69",
        70: "70-79",
        79: "70-79",
        80: "80-89",
        89: "80-89",
        90: "90-94",
        94: "90-94",
        95: "95-100",
        100: "95-100",
    }

    assert {value: confidence_bucket(value) for value in expected} == expected

    analytics = analyze_trade_outcomes(
        [outcome(1, confidence=value) for value in expected]
    )
    groups = {row["group"]: row["total"] for row in analytics["by_confidence_bucket"]}
    assert groups == {
        "0-69": 2,
        "70-79": 2,
        "80-89": 2,
        "90-94": 2,
        "95-100": 2,
    }


def test_missing_return_values_are_excluded_from_return_arithmetic():
    missing = outcome(None, hold_minutes=20)
    overall = analyze_trade_outcomes([outcome(2, hold_minutes=40), missing])["overall"]

    assert overall["closed_trades"] == 2
    assert overall["wins"] == 1
    assert overall["losses"] == 0
    assert overall["average_return"] == 2
    assert overall["average_hold_minutes"] == 30


def test_only_winners():
    overall = analyze_trade_outcomes([outcome(2), outcome(4)])["overall"]

    assert overall["win_rate"] == 100
    assert overall["profit_factor"] == math.inf
    assert overall["average_loser"] is None


def test_only_losers():
    overall = analyze_trade_outcomes([outcome(-2), outcome(-4)])["overall"]

    assert overall["win_rate"] == 0
    assert overall["profit_factor"] == 0
    assert overall["average_winner"] is None


def test_history_path_input_uses_existing_loader(tmp_path):
    history_file = tmp_path / "signal_history.jsonl"
    rewrite_trade_outcomes([outcome(3, symbol="IWM")], history_file)

    analytics = analyze_trade_outcomes(history_file)

    assert analytics["overall"]["total_signals"] == 1
    assert analytics["by_symbol"][0]["group"] == "IWM"
