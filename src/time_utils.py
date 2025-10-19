"""Timezone aware helpers for the orchestration service."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def get_timezone(name: str) -> ZoneInfo:
    """Return a ZoneInfo instance for the provided timezone name."""

    return ZoneInfo(name)


def parse_plan_date(value: str, *, tz_name: str = "Europe/Paris") -> date:
    """Parse the schedule date from input."""

    if value.lower() in {"today", "now"}:
        return datetime.now(tz=get_timezone(tz_name)).date()
    return datetime.strptime(value, "%Y-%m-%d").date()


def combine_local_datetime(
    plan_date: date, clock: str, *, tz_name: str = "Europe/Paris"
) -> datetime:
    """Combine a date and an HH:MM string into an aware datetime."""

    hour, minute = map(int, clock.split(":", 1))
    tz = get_timezone(tz_name)
    return datetime.combine(plan_date, time(hour=hour, minute=minute, tzinfo=tz))


def ensure_timezone(dt: datetime, tz_name: str) -> datetime:
    """Ensure a datetime is aware in the provided timezone."""

    tz = get_timezone(tz_name)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def to_utc(dt: datetime) -> datetime:
    """Convert a datetime to UTC."""

    return dt.astimezone(ZoneInfo("UTC"))


def format_rfc3339(dt: datetime) -> str:
    """Return the RFC3339 representation of a datetime."""

    return dt.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z")


def subtract_offsets(
    base: datetime, offsets: Iterable[timedelta]
) -> list[tuple[timedelta, datetime]]:
    """Return offsets applied to the base datetime, sorted soonest first."""

    entries = [(offset, base - offset) for offset in offsets]
    entries.sort(key=lambda item: item[1])
    return entries


def minutes(value: int) -> timedelta:
    """Return a timedelta representing N minutes."""

    return timedelta(minutes=value)


def now_utc() -> datetime:
    """Return current UTC time."""

    return datetime.now(tz=ZoneInfo("UTC"))


def now_local(tz_name: str = "Europe/Paris") -> datetime:
    """Return current time in provided timezone."""

    return datetime.now(tz=get_timezone(tz_name))
