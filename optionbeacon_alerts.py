import os


REQUIRED_ENV_KEYS = [
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_PHONE_NUMBER",
    "ALERT_TO_PHONE_NUMBER",
]


def twilio_configured():
    return all(os.getenv(key) for key in REQUIRED_ENV_KEYS)


def alert_phone_numbers():
    raw_numbers = os.getenv("ALERT_TO_PHONE_NUMBER", "")
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

    client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
    sent_ids = []

    for recipient in recipients:
        message = client.messages.create(
            body=body,
            from_=os.getenv("TWILIO_PHONE_NUMBER"),
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
