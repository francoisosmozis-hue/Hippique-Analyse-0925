"""Timezone utilities for Europe/Paris and UTC conversions."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


TZ_PARIS = ZoneInfo("Europe/Paris")
TZ_UTC = ZoneInfo("UTC")


def now_paris() -> datetime:
    """Current time in Europe/Paris."""
    return datetime.now(TZ_PARIS)


def now_utc() -> datetime:
    """Current time in UTC."""
    return datetime.now(TZ_UTC)


def paris_to_utc(dt: datetime) -> datetime:
    """Convert Paris time to UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_PARIS)
    return dt.astimezone(TZ_UTC)


def utc_to_paris(dt: datetime) -> datetime:
    """Convert UTC to Paris time."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_UTC)
    return dt.astimezone(TZ_PARIS)


def format_rfc3339(dt: datetime) -> str:
    """Format datetime as RFC3339 (for Cloud Tasks scheduleTime)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_PARIS)
    utc_dt = dt.astimezone(TZ_UTC)
    return utc_dt.isoformat().replace("+00:00", "Z")


def parse_time_local(date_str: str, time_str: str) -> datetime:
    """Parse date (YYYY-MM-DD) and time (HH:MM) as Paris timezone."""
    dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    return dt.replace(tzinfo=TZ_PARIS)


def subtract_minutes(dt: datetime, minutes: int) -> datetime:
    """Subtract minutes from datetime."""
    return dt - timedelta(minutes=minutes)
