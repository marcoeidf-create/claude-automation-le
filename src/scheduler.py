"""
Send timing scheduler.

Determines the prospect's timezone from their jurisdiction, then calculates
the next optimal send window: Tuesday–Thursday, 7:30–8:29am local time.
That is the window before shift briefing when LE executives read email.
"""

import os
import random
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from google import genai

STATE_TIMEZONES = {
    "ME": "America/New_York", "NH": "America/New_York", "VT": "America/New_York",
    "MA": "America/New_York", "RI": "America/New_York", "CT": "America/New_York",
    "NY": "America/New_York", "NJ": "America/New_York", "PA": "America/New_York",
    "DE": "America/New_York", "MD": "America/New_York", "DC": "America/New_York",
    "VA": "America/New_York", "WV": "America/New_York", "NC": "America/New_York",
    "SC": "America/New_York", "GA": "America/New_York", "FL": "America/New_York",
    "OH": "America/New_York", "MI": "America/New_York",
    "IN": "America/Chicago", "IL": "America/Chicago", "WI": "America/Chicago",
    "MN": "America/Chicago", "IA": "America/Chicago", "MO": "America/Chicago",
    "AR": "America/Chicago", "LA": "America/Chicago", "MS": "America/Chicago",
    "AL": "America/Chicago", "TN": "America/Chicago", "KY": "America/Chicago",
    "ND": "America/Chicago", "SD": "America/Chicago", "NE": "America/Chicago",
    "KS": "America/Chicago", "OK": "America/Chicago", "TX": "America/Chicago",
    "MT": "America/Denver", "WY": "America/Denver", "CO": "America/Denver",
    "NM": "America/Denver", "UT": "America/Denver", "ID": "America/Denver",
    "AZ": "America/Phoenix",
    "WA": "America/Los_Angeles", "OR": "America/Los_Angeles",
    "CA": "America/Los_Angeles", "NV": "America/Los_Angeles",
    "AK": "America/Anchorage",
    "HI": "Pacific/Honolulu",
}

_VALID_SEND_DAYS = {1, 2, 3}  # Tue, Wed, Thu (Mon=0)


def _extract_state_abbr(jurisdiction: str) -> str:
    for pattern in [r",\s*([A-Z]{2})\b", r"\b([A-Z]{2})\b"]:
        m = re.search(pattern, jurisdiction.upper())
        if m and m.group(1) in STATE_TIMEZONES:
            return m.group(1)
    return ""


def get_timezone_for_jurisdiction(jurisdiction: str, agency: str = "") -> str:
    """Return an IANA timezone string for a given jurisdiction."""
    if jurisdiction:
        state = _extract_state_abbr(jurisdiction)
        if state:
            return STATE_TIMEZONES[state]

    api_key = os.environ.get("GOOGLE_API_KEY")
    if api_key and (jurisdiction or agency):
        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=(
                    f"What is the IANA timezone string for this US law enforcement jurisdiction?\n"
                    f"Jurisdiction: {jurisdiction or 'unknown'}\n"
                    f"Agency: {agency or 'unknown'}\n"
                    f"Reply with only the IANA timezone string (e.g. America/Chicago). Nothing else."
                ),
            )
            tz_str = response.text.strip().strip('"').strip("'")
            ZoneInfo(tz_str)
            return tz_str
        except (ZoneInfoNotFoundError, Exception):
            pass

    return "America/New_York"


def get_next_send_window(timezone_str: str) -> datetime:
    """
    Return the next Tue–Thu 7:30–8:29am slot in the given timezone as UTC.
    The exact minute is randomised within the window.
    """
    try:
        tz = ZoneInfo(timezone_str)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("America/New_York")

    now_local = datetime.now(tz)
    offset_from_730 = random.randint(0, 59)
    total_minutes = 7 * 60 + 30 + offset_from_730
    send_hour = total_minutes // 60
    send_minute = total_minutes % 60

    for days_offset in range(14):
        candidate = (now_local + timedelta(days=days_offset)).replace(
            hour=send_hour, minute=send_minute, second=0, microsecond=0
        )
        if (candidate.weekday() in _VALID_SEND_DAYS
                and candidate > now_local + timedelta(hours=1)):
            return candidate.astimezone(timezone.utc)

    days_until_tue = (1 - now_local.weekday()) % 7 or 7
    fallback = (now_local + timedelta(days=days_until_tue)).replace(
        hour=7, minute=45, second=0, microsecond=0
    )
    return fallback.astimezone(timezone.utc)


def format_send_time(utc_dt: datetime, timezone_str: str) -> str:
    """Format a UTC datetime as a human-readable local time string."""
    try:
        tz = ZoneInfo(timezone_str)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("America/New_York")

    local = utc_dt.astimezone(tz)
    day = local.strftime("%a %b %-d")
    hour = local.hour % 12 or 12
    minute = f"{local.minute:02d}"
    ampm = "am" if local.hour < 12 else "pm"
    tz_labels = {
        "America/New_York": "ET", "America/Chicago": "CT",
        "America/Denver": "MT", "America/Phoenix": "MT",
        "America/Los_Angeles": "PT", "America/Anchorage": "AKT",
        "Pacific/Honolulu": "HT",
    }
    tz_label = tz_labels.get(timezone_str, timezone_str.split("/")[-1].replace("_", " "))
    return f"{day} at {hour}:{minute}{ampm} {tz_label}"
