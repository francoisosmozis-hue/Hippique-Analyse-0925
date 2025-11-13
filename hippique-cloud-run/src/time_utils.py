from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def parse_local_time(date_str: str, time_str: str, tz_name: str = "Europe/Paris") -> datetime:
    """Parse date + heure locale en datetime aware."""
    dt_naive = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    return dt_naive.replace(tzinfo=ZoneInfo(tz_name))


def compute_snapshot_times(race_time_local: datetime) -> tuple[datetime, datetime]:
    """Calcule H-30 et H-5 depuis heure course (Europe/Paris)."""
    h30 = race_time_local - timedelta(minutes=30)
    h5 = race_time_local - timedelta(minutes=5)
    return h30, h5


def to_utc_rfc3339(dt: datetime) -> str:
    """Convertit datetime aware en UTC RFC3339 pour Cloud Tasks."""
    utc_dt = dt.astimezone(ZoneInfo("UTC"))
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def format_local(dt: datetime) -> str:
    """Format pour affichage local."""
    return dt.strftime("%Y-%m-%d %H:%M %Z")
