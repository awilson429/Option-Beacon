import os


REQUIRED_ENV_KEYS = [
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_PHONE_NUMBER",
    "ALERT_TO_PHONE_NUMBER",
]


def twilio_configured():
    return all(os.getenv(key) for key in REQUIRED_ENV_KEYS)


def send_sms_message(body):
    if not twilio_configured():
        return False, "Twilio environment variables not configured"

    try:
        from twilio.rest import Client
    except ImportError:
        return False, "Twilio package not installed"

    client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
    message = client.messages.create(
        body=body,
        from_=os.getenv("TWILIO_PHONE_NUMBER"),
        to=os.getenv("ALERT_TO_PHONE_NUMBER"),
    )
    return True, f"Sent {message.sid}"


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
