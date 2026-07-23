import os
from datetime import time

import pandas as pd

from finnhub_universe import active_symbol_groups, flatten_symbol_groups
from live_coach_alerts import load_live_coach_alerts, record_live_coach_alert
from optionbeacon_history import (
    add_high_score_snapshot,
    eastern_now,
    load_high_score_history,
)
from optionbeacon_live import generate_signal
from optionbeacon_snapshot import save_latest_results
from scheduled_trade_coach import run_active_trade_coaching


def is_market_open_now():
    now = eastern_now()

    try:
        import pandas_market_calendars as mcal

        nyse = mcal.get_calendar("NYSE")
        schedule = nyse.schedule(start_date=now.date(), end_date=now.date())

        if schedule.empty:
            return False

        market_open = schedule.iloc[0]["market_open"].tz_convert("America/New_York")
        market_close = schedule.iloc[0]["market_close"].tz_convert("America/New_York")
        return market_open <= pd.Timestamp(now) < market_close
    except Exception:
        current_time = now.time()
        return now.weekday() < 5 and time(9, 30) <= current_time < time(16, 0)


def clean_value(value):
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, list):
        return [clean_value(item) for item in value]
    if isinstance(value, dict):
        return {key: clean_value(item) for key, item in value.items()}
    return value


def scanner_unavailable(symbol, message):
    return {
        "symbol": symbol,
        "signal": "DATA UNAVAILABLE",
        "price": None,
        "confidence": 0,
        "bullish_score": 0,
        "bearish_score": 0,
        "setup_stage": "Unavailable",
        "entry_timing": "Wait",
        "what_next": "Wait.",
        "what_next_reason": message,
        "trade_plan": {},
        "reasons": [message],
    }


def main():
    if os.getenv("OPTION_BEACON_TEST_ALERT", "").lower() == "true":
        print("External test alerts are disabled. Option Beacon now uses in-app guide alerts.")
        return

    if not is_market_open_now():
        print("Market is closed. Skipping scheduled scan.")
        return

    latest_results = {}
    high_score_history = load_high_score_history()
    live_alerts = load_live_coach_alerts()
    symbol_groups, source, error = active_symbol_groups()
    symbols = flatten_symbol_groups(symbol_groups)

    print(f"Scanner universe: {source} ({len(symbols)} symbols)")
    if error:
        print(f"Scanner universe note: {error}")

    for symbol in symbols:
        try:
            result = generate_signal(symbol)
        except Exception as exc:
            result = scanner_unavailable(symbol, f"Data unavailable: {exc}")

        if result is None:
            result = scanner_unavailable(
                symbol,
                "Data unavailable: not enough recent 5-minute candles returned.",
            )

        result = clean_value(result)
        latest_results[symbol] = result

        if result.get("signal") != "DATA UNAVAILABLE":
            added, row = add_high_score_snapshot(result)

            alert_added, alert = record_live_coach_alert(
                result,
                history=high_score_history,
                alerts=live_alerts,
            )
            if alert_added:
                live_alerts = load_live_coach_alerts()
                print(f"{symbol} guide alert logged: {alert['headline']}")

            if added:
                high_score_history = load_high_score_history()

    save_latest_results(latest_results)
    print(f"Saved scheduled scan for {len(latest_results)} symbols.")

    coach_rows = run_active_trade_coaching(
        latest_results=latest_results,
        alerts_enabled=False,
    )
    if coach_rows:
        print(f"Guided {len(coach_rows)} open paper trade(s).")
        for row in coach_rows:
            previous = row["previous_action"] or "None"
            print(
                f"Trade #{row['position_id']} {row['symbol']}: "
                f"{previous} -> {row['coach_action']} "
                f"({row['exit_score']}/100), alert {row['alert_status']}"
            )


if __name__ == "__main__":
    main()
