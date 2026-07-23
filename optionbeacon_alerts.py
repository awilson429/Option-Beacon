import os


REQUIRED_ENV_KEYS = [
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_PHONE_NUMBER",
    "ALERT_TO_PHONE_NUMBER",
]


def twilio_configured():
    return all(config_value(key) for key in REQUIRED_ENV_KEYS)


def config_value(key, default=""):
    value = os.getenv(key)
    if value:
        return value

    try:
        import streamlit as st

        return st.secrets.get(key, default)
    except Exception:
        return default


def alert_phone_numbers():
    raw_numbers = config_value("ALERT_TO_PHONE_NUMBER", "")
    return [number.strip() for number in raw_numbers.split(",") if number.strip()]


def send_sms_message(body):
    if not twilio_configured():
        return False, "Twilio environment variables not configured"

    recipients = alert_phone_numbers()
    if not recipients:
        return False, "No alert phone numbers configured"

    try:
        from twilio.rest import Client
    except ImportError:
        return False, "Twilio package not installed"

    client = Client(config_value("TWILIO_ACCOUNT_SID"), config_value("TWILIO_AUTH_TOKEN"))
    sent_ids = []

    for recipient in recipients:
        message = client.messages.create(
            body=body,
            from_=config_value("TWILIO_PHONE_NUMBER"),
            to=recipient,
        )
        sent_ids.append(message.sid)

    return True, f"Sent {len(sent_ids)} message(s): {', '.join(sent_ids)}"


def format_high_score_alert(row, previous_bias=None):
    symbol = row["symbol"]
    bias = row["bias"]
    score = row["score"]
    price = row["price"]
    price_label = f"${price}" if price else "N/A"
    reason = row["reason"] or "High scanner score"

    if previous_bias and previous_bias != bias:
        return (
            f"Option Beacon reversal watch: {symbol} shifted from {previous_bias} "
            f"to {bias}. Score {score}/100 at {price_label}. Reason: {reason}."
        )

    return (
        f"Option Beacon high score: {symbol} {bias} score {score}/100 "
        f"at {price_label}. Reason: {reason}."
    )


def send_high_score_alert(row, previous_bias=None):
    return send_sms_message(format_high_score_alert(row, previous_bias=previous_bias))


def format_trade_coach_alert(position, recommendation, previous_action=None):
    symbol = position.get("symbol", "Unknown")
    direction = position.get("direction", "Trade")
    action = recommendation.get("coach_action", "Review")
    score = recommendation.get("exit_score", "N/A")
    current_profit = recommendation.get("current_profit_percent")
    peak_profit = recommendation.get("peak_profit_percent")
    suggested_stop = recommendation.get("suggested_stop")
    next_step = recommendation.get("coach_next_step", "Review the trade plan.")

    if current_profit is None:
        profit_label = "P/L N/A"
    else:
        profit_label = f"P/L {current_profit}%"

    if peak_profit is None:
        peak_label = "peak N/A"
    else:
        peak_label = f"peak {peak_profit}%"

    if previous_action and previous_action != action:
        change_label = f"{previous_action} -> {action}"
    else:
        change_label = action

    stop_label = ""
    if suggested_stop:
        stop_label = f" Suggested stop ${suggested_stop}."

    return (
        f"Option Beacon trade coach: {symbol} {direction} {change_label}. "
        f"Exit score {score}/100, {profit_label}, {peak_label}.{stop_label} {next_step}"
    )


def send_trade_coach_alert(position, recommendation, previous_action=None):
    return send_sms_message(
        format_trade_coach_alert(
            position,
            recommendation,
            previous_action=previous_action,
        )
    )
