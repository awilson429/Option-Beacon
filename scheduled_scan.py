import os
from datetime import time

import pandas as pd

from optionbeacon_alerts import send_high_score_alert, send_sms_message, twilio_configured
from optionbeacon_history import (
    add_high_score_snapshot,
    eastern_now,
    load_high_score_history,
    previous_symbol_bias,
)
from optionbeacon_live import SYMBOLS, generate_signal
from optionbeacon_snapshot import save_latest_results


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
        "reasons": [message],
    }


def main():
    if os.getenv("OPTION_BEACON_TEST_ALERT", "").lower() == "true":
        test_time = eastern_now().strftime("%I:%M %p ET")
        sent, status = send_sms_message(f"Option Beacon test alert: SPY-Bullish 92/100 @ {test_time}")
        print(f"Test alert: {status}")
        if not sent:
            raise RuntimeError(status)
        return

    if not is_market_open_now():
        print("Market is closed. Skipping scheduled scan.")
        return

    latest_results = {}
    high_score_history = load_high_score_history()
    alerts_enabled = twilio_configured()

    for symbol in SYMBOLS:
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
            previous_bias = previous_symbol_bias(high_score_history, symbol)
            added, row = add_high_score_snapshot(result)

            if added:
                high_score_history = load_high_score_history()

                should_alert = previous_bias is None or previous_bias != row["bias"]
                if alerts_enabled and should_alert:
                    sent, status = send_high_score_alert(row, previous_bias=previous_bias)
                    print(f"{symbol} alert: {status}")
                elif should_alert:
                    print(f"{symbol} alert skipped: Twilio not configured")

    save_latest_results(latest_results)
    print(f"Saved scheduled scan for {len(latest_results)} symbols.")


if __name__ == "__main__":
    main()
