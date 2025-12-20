"""
hippique_orchestrator/time_utils.py - Time and timezone utilities.
"""

from datetime import datetime

import pytz

# Centralize timezone definition
_TZ = pytz.timezone('Europe/Paris')


def get_tz():
    """Returns the official project timezone."""
    return _TZ


def get_today_str() -> str:
    """
    Returns the current date as a string (YYYY-MM-DD) in the project's timezone.
    """
    return datetime.now(_TZ).strftime('%Y-%m-%d')


def convert_local_to_utc(local_dt: datetime) -> datetime:
    """
    Converts a datetime (either naive or aware) to a timezone-aware UTC datetime.
    If the datetime is naive, it's assumed to be in the 'Europe/Paris' timezone.
    """
    if local_dt.tzinfo is None or local_dt.tzinfo.utcoffset(local_dt) is None:
        # It's a naive datetime, so we assume it's in the local timezone
        local_aware = _TZ.localize(local_dt)
    else:
        # It's already an aware datetime
        local_aware = local_dt
    return local_aware.astimezone(pytz.utc)


def format_rfc3339(dt: datetime) -> str:
    """
    Formats a datetime object into an RFC3339 string with Z timezone designator.
    e.g., '2025-12-06T14:30:00Z'
    """
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')
