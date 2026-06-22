# Option Beacon

Paper-trading Streamlit dashboard for ETF and single-stock option signal scanning.

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

## Threshold optimizer

Run the optimizer locally to compare per-ticker call and put score thresholds before changing the live scanner:

```bash
python optimize_thresholds.py
```

It writes:

- `threshold_optimizer_results.csv`
- `threshold_recommendations.csv`

These generated files are ignored by Git.
