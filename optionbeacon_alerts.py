REQUIRED_SECRET_KEYS = [
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_PHONE_NUMBER",
    "ALERT_TO_PHONE_NUMBER",
]


def twilio_configured(secrets):
    return all(secrets.get(key) for key in REQUIRED_SECRET_KEYS)


def format_trade_alert(result):
    direction = result.get("bias", result.get("signal", "Setup"))
    return (
        f"Option Beacon: {result['symbol']} {direction} opportunity "
        f"at ${result['entry']:.2f}. "
        f"Stop ${result['stop']:.2f}, target ${result['target']:.2f}, "
        f"BE ${result['breakeven']:.2f}. "
        f"Score {result.get('confidence', 'N/A')}/100."
    )


def send_sms_message(body, secrets):
    if not twilio_configured(secrets):
        return False, "Twilio secrets not configured"

    try:
        from twilio.rest import Client
    except ImportError:
        return False, "Twilio package not installed"

    client = Client(secrets["TWILIO_ACCOUNT_SID"], secrets["TWILIO_AUTH_TOKEN"])
    message = client.messages.create(
        body=body,
        from_=secrets["TWILIO_PHONE_NUMBER"],
        to=secrets["ALERT_TO_PHONE_NUMBER"],
    )
    return True, f"Sent {message.sid}"


def send_trade_alert(result, secrets):
    return send_sms_message(format_trade_alert(result), secrets)


def send_test_alert(secrets):
    return send_sms_message("Option Beacon SMS test: alerts are configured and ready.", secrets)
