# Option Beacon

Paper-trading Streamlit dashboard for SPY, QQQ, IWM, and DIA option signal scanning.

## License and use

Copyright (c) 2026 Option Beacon LLC. All rights reserved.

This project is proprietary. The code, trading logic, branding, and related materials may not be copied, modified, distributed, or used without written permission from Option Beacon LLC.

## Streamlit secrets

SMS alerts use Twilio and should be configured in Streamlit Community Cloud secrets, not committed to GitHub:

```toml
TWILIO_ACCOUNT_SID = "your-account-sid"
TWILIO_AUTH_TOKEN = "your-auth-token"
TWILIO_PHONE_NUMBER = "+15555550100"
ALERT_TO_PHONE_NUMBER = "+15555550101"
```

When these values are missing, the dashboard keeps running and SMS alerts stay off.

## Optional app access code

To require a password before the dashboard loads, add this optional secret in Streamlit Community Cloud:

```toml
APP_ACCESS_CODE = "choose-a-strong-private-code"
```

If `APP_ACCESS_CODE` is missing, the app remains publicly viewable.
