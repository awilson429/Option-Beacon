# Option Beacon

Paper-trading Streamlit dashboard for SPY and QQQ option signal scanning.

## Streamlit secrets

SMS alerts use Twilio and should be configured in Streamlit Community Cloud secrets, not committed to GitHub:

```toml
TWILIO_ACCOUNT_SID = "your-account-sid"
TWILIO_AUTH_TOKEN = "your-auth-token"
TWILIO_PHONE_NUMBER = "+15555550100"
ALERT_TO_PHONE_NUMBER = "+15555550101"
```

When these values are missing, the dashboard keeps running and SMS alerts stay off.
