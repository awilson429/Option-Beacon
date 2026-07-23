from trade_management import coach_recommendation
from trade_storage import (
    DB_FILE,
    latest_recommendation,
    load_open_positions,
    record_recommendation,
)


def scanner_unavailable(symbol, message):
    return {
        "symbol": symbol,
        "signal": "DATA UNAVAILABLE",
        "price": None,
        "reasons": [message],
    }


def result_for_position(position, latest_results=None):
    latest_results = latest_results or {}
    symbol = position["symbol"]

    if symbol in latest_results:
        return latest_results[symbol]

    try:
        from optionbeacon_live import generate_signal

        result = generate_signal(symbol)
    except Exception as exc:
        return scanner_unavailable(symbol, f"Data unavailable: {exc}")

    return result or scanner_unavailable(
        symbol,
        "Data unavailable: not enough recent 5-minute candles returned.",
    )


def run_active_trade_coaching(
    *,
    latest_results=None,
    db_file=DB_FILE,
    alerts_enabled=None,
):
    positions = load_open_positions(db_file=db_file)
    rows = []

    for position in positions:
        scanner_result = result_for_position(position, latest_results=latest_results)
        recommendation = coach_recommendation(position, scanner_result)
        previous = latest_recommendation(position["id"], db_file=db_file)
        recommendation_id = record_recommendation(
            position["id"],
            recommendation,
            db_file=db_file,
        )
        previous_action = previous.get("coach_action") if previous else None
        rows.append(
            {
                "position_id": position["id"],
                "symbol": position["symbol"],
                "coach_action": recommendation["coach_action"],
                "exit_score": recommendation["exit_score"],
                "recommendation_id": recommendation_id,
                "previous_action": previous_action,
                "alert_status": "in-app only",
            }
        )

    return rows


def main():
    rows = run_active_trade_coaching()
    if not rows:
        print("No open trades to coach.")
        return

    for row in rows:
        previous = row["previous_action"] or "None"
        print(
            f"#{row['position_id']} {row['symbol']}: "
            f"{previous} -> {row['coach_action']} "
            f"({row['exit_score']}/100), alert {row['alert_status']}"
        )


if __name__ == "__main__":
    main()
