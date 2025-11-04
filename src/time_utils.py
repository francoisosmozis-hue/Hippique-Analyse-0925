"""
src/time_utils.py - Gestion Timezone Europe/Paris

Conversions timezone et formatage RFC3339 pour Cloud Tasks.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

PARIS_TZ = ZoneInfo("Europe/Paris")
UTC_TZ = timezone.utc

def convert_local_to_utc(dt_local: datetime) -> datetime:
    """
    Convertit un datetime Europe/Paris vers UTC.
    
    Args:
        dt_local: Datetime naive ou aware en Europe/Paris
        
    Returns:
        Datetime aware en UTC
        
    Example:
        >>> dt_paris = datetime(2025, 10, 16, 14, 30)  # 14:30 Paris
        >>> dt_utc = convert_local_to_utc(dt_paris)
        >>> dt_utc.hour  # 12 (heure d'été) ou 13 (heure d'hiver)
    """
    if dt_local.tzinfo is None:
        # Naive datetime, assume Europe/Paris
        dt_aware = dt_local.replace(tzinfo=PARIS_TZ)
    elif dt_local.tzinfo != PARIS_TZ:
        # Already aware but not Paris timezone, convert to Paris first
        dt_aware = dt_local.astimezone(PARIS_TZ)
    else:
        dt_aware = dt_local
    
    # Convert to UTC
    return dt_aware.astimezone(UTC_TZ)

def convert_utc_to_local(dt_utc: datetime) -> datetime:
    """
    Convertit un datetime UTC vers Europe/Paris.
    
    Args:
        dt_utc: Datetime aware en UTC
        
    Returns:
        Datetime aware en Europe/Paris
    """
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=UTC_TZ)
    
    return dt_utc.astimezone(PARIS_TZ)

def format_rfc3339(dt: datetime) -> str:
    """
    Format datetime en RFC3339 pour Cloud Tasks.
    
    Args:
        dt: Datetime aware
        
    Returns:
        String RFC3339: "2025-10-16T12:30:00Z"
    """
    if dt.tzinfo is None:
        raise ValueError("Datetime must be timezone-aware")
    
    # Convert to UTC if not already
    dt_utc = dt.astimezone(UTC_TZ)
    
    return dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

def parse_time_local(time_str: str, date_str: str) -> datetime:
    """
    Parse une heure locale (Europe/Paris) avec une date.
    
    Args:
        time_str: "HH:MM" (Europe/Paris)
        date_str: "YYYY-MM-DD"
        
    Returns:
        Datetime aware en Europe/Paris
        
    Example:
        >>> dt = parse_time_local("14:30", "2025-10-16")
        >>> dt.tzinfo == PARIS_TZ
        True
    """
    dt_naive = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    return dt_naive.replace(tzinfo=PARIS_TZ)