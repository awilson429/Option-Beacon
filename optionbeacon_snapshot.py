import json
import os
from datetime import datetime
from urllib.request import urlopen
from zoneinfo import ZoneInfo

import pandas as pd


SNAPSHOT_FILE = "latest_results.json"
SNAPSHOT_MAX_AGE_MINUTES = 15
REMOTE_DATA_BASE_URL = os.getenv(
    "OPTION_BEACON_DATA_BASE_URL",
    "https://raw.githubusercontent.com/awilson429/Option-Beacon/scanner-data",
)
REMOTE_SNAPSHOT_URL = f"{REMOTE_DATA_BASE_URL}/{SNAPSHOT_FILE}"


def save_latest_results(results):
    payload = {
        "updated_at": datetime.now(ZoneInfo("America/New_York")).isoformat(),
        "results": results,
    }

    with open(SNAPSHOT_FILE, "w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2)


def parse_snapshot_payload(payload, max_age_minutes):
    updated_at = pd.Timestamp(payload["updated_at"])
    if updated_at.tzinfo is None:
        updated_at = updated_at.tz_localize("America/New_York")

    now = pd.Timestamp.now(tz="America/New_York")
    age_minutes = (now - updated_at).total_seconds() / 60

    if age_minutes > max_age_minutes:
        return None, updated_at

    return payload.get("results", {}), updated_at


def load_local_latest_results(max_age_minutes):
    if not os.path.exists(SNAPSHOT_FILE):
        return None, None

    with open(SNAPSHOT_FILE, "r", encoding="utf-8") as file:
        payload = json.load(file)

    return parse_snapshot_payload(payload, max_age_minutes)


def load_remote_latest_results(max_age_minutes):
    with urlopen(REMOTE_SNAPSHOT_URL, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))

    return parse_snapshot_payload(payload, max_age_minutes)


def load_latest_results(max_age_minutes=SNAPSHOT_MAX_AGE_MINUTES):
    try:
        results, updated_at = load_local_latest_results(max_age_minutes)
        if results:
            return results, updated_at
    except Exception:
        pass

    try:
        return load_remote_latest_results(max_age_minutes)
    except Exception:
        return None, None
