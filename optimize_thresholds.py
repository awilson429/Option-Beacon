import pandas as pd

from backtest import (
    SYMBOLS,
    add_indicators,
    backtest_symbol,
    calculate_stats,
    get_data,
)


CALL_THRESHOLDS = [95, 90, 85, 80, 75]
PUT_THRESHOLDS = [95, 90, 85, 80, 75]
MIN_TRADES_FOR_RECOMMENDATION = 5

RESULTS_FILE = "threshold_optimizer_results.csv"
RECOMMENDATIONS_FILE = "threshold_recommendations.csv"


def quality_score(stats):
    if stats["trades"] == 0:
        return -999

    profit_factor = min(stats["profit_factor"], 5)
    trade_depth = min(stats["trades"] / 20, 1)

    return (
        stats["win_rate"] * 0.45
        + profit_factor * 12
        + stats["total_pnl"] * 1.5
        + trade_depth * 10
    )


def optimize_symbol(symbol):
    try:
        prepared_data = add_indicators(get_data(symbol))
    except Exception as exc:
        return pd.DataFrame(
            [
                {
                    "symbol": symbol,
                    "error": str(exc),
                }
            ]
        )

    rows = []

    for call_threshold in CALL_THRESHOLDS:
        for put_threshold in PUT_THRESHOLDS:
            trades = backtest_symbol(
                symbol,
                call_score_threshold=call_threshold,
                put_score_threshold=put_threshold,
                prepared_data=prepared_data,
            )
            stats = calculate_stats(trades)

            rows.append(
                {
                    "symbol": symbol,
                    "call_threshold": call_threshold,
                    "put_threshold": put_threshold,
                    "trades": stats["trades"],
                    "wins": stats["wins"],
                    "losses": stats["losses"],
                    "breakevens": stats["breakevens"],
                    "time_exits": stats["time_exits"],
                    "win_rate": round(stats["win_rate"], 2),
                    "avg_pnl": round(stats["avg_pnl"], 3),
                    "total_pnl": round(stats["total_pnl"], 3),
                    "profit_factor": round(stats["profit_factor"], 2),
                    "quality_score": round(quality_score(stats), 3),
                    "error": "",
                }
            )

    return pd.DataFrame(rows)


def select_recommendations(results):
    valid = results[
        (results["error"] == "")
        & (results["trades"] >= MIN_TRADES_FOR_RECOMMENDATION)
        & (results["profit_factor"] >= 1)
    ].copy()

    if len(valid) == 0:
        return pd.DataFrame(columns=results.columns)

    valid = valid.sort_values(
        ["symbol", "quality_score", "trades"],
        ascending=[True, False, False],
    )
    return valid.groupby("symbol", as_index=False).head(1)


def main():
    all_results = []

    print("\nOPTION BEACON THRESHOLD OPTIMIZER")
    print("=" * 40)
    print(f"Testing call thresholds: {CALL_THRESHOLDS}")
    print(f"Testing put thresholds: {PUT_THRESHOLDS}")

    for symbol in SYMBOLS:
        print(f"\nOptimizing {symbol}...")
        symbol_results = optimize_symbol(symbol)
        all_results.append(symbol_results)

        if "trades" in symbol_results.columns:
            preview = symbol_results.sort_values(
                ["quality_score", "trades"],
                ascending=[False, False],
            ).head(5)
            print(preview[[
                "call_threshold",
                "put_threshold",
                "trades",
                "win_rate",
                "profit_factor",
                "total_pnl",
                "quality_score",
            ]])
        else:
            print(symbol_results)

    results = pd.concat(all_results, ignore_index=True)
    results.to_csv(RESULTS_FILE, index=False)

    recommendations = select_recommendations(results)
    recommendations.to_csv(RECOMMENDATIONS_FILE, index=False)

    print(f"\nSaved full results to {RESULTS_FILE}")
    print(f"Saved recommendations to {RECOMMENDATIONS_FILE}")

    if len(recommendations) > 0:
        print("\nRECOMMENDED THRESHOLDS")
        print("=" * 40)
        print(recommendations[[
            "symbol",
            "call_threshold",
            "put_threshold",
            "trades",
            "win_rate",
            "profit_factor",
            "total_pnl",
        ]])
    else:
        print("\nNo recommendations met the minimum trade/profit-factor filters.")


if __name__ == "__main__":
    main()
