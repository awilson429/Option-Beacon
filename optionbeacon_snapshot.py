import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd


SNAPSHOT_FILE = "latest_results.json"
SNAPSHOT_MAX_AGE_MINUTES = 15


def save_latest_results(results):
    payload = {
        "updated_at": datetime.now(ZoneInfo("America/New_York")).isoformat(),
        "results": results,
    }

    with open(SNAPSHOT_FILE, "w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2)


def load_latest_results(max_age_minutes=SNAPSHOT_MAX_AGE_MINUTES):
    if not os.path.exists(SNAPSHOT_FILE):
        return None, None

    try:
        with open(SNAPSHOT_FILE, "r", encoding="utf-8") as file:
            payload = json.load(file)

        updated_at = pd.Timestamp(payload["updated_at"])
        if updated_at.tzinfo is None:
            updated_at = updated_at.tz_localize("America/New_York")

        now = pd.Timestamp.now(tz="America/New_York")
        age_minutes = (now - updated_at).total_seconds() / 60

        if age_minutes > max_age_minutes:
            return None, updated_at

        return payload.get("results", {}), updated_at
    except Exception:
        return None, None
