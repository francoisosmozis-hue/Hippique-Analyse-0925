"""
src/time_utils.py - Utilitaires timezone (Europe/Paris <-> UTC)
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from config import get_config

config = get_config()
TZ_PARIS = ZoneInfo(config.timezone)
TZ_UTC = ZoneInfo("UTC")


def parse_local_time(time_str: str) -> datetime.time:
    """
    Parse une heure locale HH:MM.

    Args:
        time_str: "15:20", "09:05", etc.

    Returns:
        datetime.time object
    """
    match = re.match(r"^(\d{1,2}):(\d{2})$", time_str)
    if not match:
        raise ValueError(f"Invalid time format: {time_str}, expected HH:MM")

    hour, minute = match.groups()
    return datetime.strptime(f"{int(hour):02d}:{int(minute):02d}", "%H:%M").time()


def local_datetime_to_utc(local_dt: datetime) -> datetime:
    """
    Convertit un datetime Europe/Paris en UTC.

    Args:
        local_dt: datetime naïf ou avec tzinfo=Europe/Paris

    Returns:
        datetime UTC avec tzinfo=UTC
    """
    if local_dt.tzinfo is None:
        # Assume Europe/Paris si naïf
        local_dt = local_dt.replace(tzinfo=TZ_PARIS)
    elif local_dt.tzinfo != TZ_PARIS:
        # Convertir d'abord en Paris
        local_dt = local_dt.astimezone(TZ_PARIS)

    return local_dt.astimezone(TZ_UTC)


def utc_to_local_datetime(utc_dt: datetime) -> datetime:
    """
    Convertit un datetime UTC en Europe/Paris.

    Args:
        utc_dt: datetime naïf ou avec tzinfo=UTC

    Returns:
        datetime Europe/Paris avec tzinfo=Europe/Paris
    """
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=TZ_UTC)
    elif utc_dt.tzinfo != TZ_UTC:
        utc_dt = utc_dt.astimezone(TZ_UTC)

    return utc_dt.astimezone(TZ_PARIS)


def compute_snapshot_time(
    date: str, race_time_local: str, offset_minutes: int
) -> tuple[datetime, datetime]:
    """
    Calcule l'heure de snapshot (Europe/Paris et UTC) pour une course.

    Args:
        date: YYYY-MM-DD
        race_time_local: HH:MM (Europe/Paris)
        offset_minutes: -30 pour H-30, -5 pour H-5

    Returns:
        (snapshot_local, snapshot_utc)
    """
    race_time = parse_local_time(race_time_local)
    race_dt = datetime.strptime(date, "%Y-%m-%d").replace(
        hour=race_time.hour, minute=race_time.minute, second=0, microsecond=0, tzinfo=TZ_PARIS
    )

    snapshot_local = race_dt + timedelta(minutes=offset_minutes)
    snapshot_utc = local_datetime_to_utc(snapshot_local)

    return snapshot_local, snapshot_utc


def format_rfc3339(dt: datetime) -> str:
    """
    Formate un datetime en RFC3339 pour Cloud Tasks.

    Args:
        dt: datetime avec tzinfo

    Returns:
        "2025-10-15T14:50:00Z" (UTC)
    """
    if dt.tzinfo is None:
        raise ValueError("datetime must have tzinfo")

    # Convertir en UTC
    dt_utc = dt.astimezone(TZ_UTC)
    return dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def now_local() -> datetime:
    """Retourne l'heure actuelle en Europe/Paris."""
    return datetime.now(TZ_PARIS)


def now_utc() -> datetime:
    """Retourne l'heure actuelle en UTC."""
    return datetime.now(TZ_UTC)


def is_past(dt: datetime) -> bool:
    """Vérifie si un datetime est dans le passé."""
    if dt.tzinfo is None:
        raise ValueError("datetime must have tzinfo")

    return dt < now_utc()


def time_until(dt: datetime) -> timedelta:
    """Calcule le délai jusqu'à un datetime futur."""
    if dt.tzinfo is None:
        raise ValueError("datetime must have tzinfo")

    delta = dt - now_utc()
    return delta if delta.total_seconds() > 0 else timedelta(0)
