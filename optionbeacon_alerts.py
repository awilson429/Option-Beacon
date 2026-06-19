REQUIRED_SECRET_KEYS = [
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_PHONE_NUMBER",
    "ALERT_TO_PHONE_NUMBER",
]


def twilio_configured(secrets):
    return all(secrets.get(key) for key in REQUIRED_SECRET_KEYS)


def format_trade_alert(result):
    return (
        f"Option Beacon: {result['symbol']} {result['signal']} "
        f"at ${result['entry']:.2f}. "
        f"Stop ${result['stop']:.2f}, target ${result['target']:.2f}, "
        f"BE ${result['breakeven']:.2f}. "
        f"Confidence {result.get('confidence', 'N/A')}%."
    )


def send_trade_alert(result, secrets):
    if not twilio_configured(secrets):
        return False, "Twilio secrets not configured"

    try:
        from twilio.rest import Client
    except ImportError:
        return False, "Twilio package not installed"

    client = Client(secrets["TWILIO_ACCOUNT_SID"], secrets["TWILIO_AUTH_TOKEN"])
    message = client.messages.create(
        body=format_trade_alert(result),
        from_=secrets["TWILIO_PHONE_NUMBER"],
        to=secrets["ALERT_TO_PHONE_NUMBER"],
    )
    return True, f"Sent {message.sid}"
