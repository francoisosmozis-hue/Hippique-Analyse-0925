# hippique_orchestrator/contracts/ids.py
"""
Functions for generating stable, deterministic IDs for races and runners.
"""
import hashlib
import re
import unicodedata



def make_race_uid(
    race_date: str, 
    venue: str, 
    race_number: int, 
    discipline: str, 
    distance_m: int, 
    scheduled_time_local: str
) -> str:
    """
    Generates a stable SHA1-based hash for a race.
    """
    base_string = (
        f"{race_date}-{normalize_name(venue)}-{race_number}-"
        f"{normalize_name(discipline)}-{distance_m}-{scheduled_time_local}"
    )
    return hashlib.sha1(base_string.encode('utf-8')).hexdigest()

def make_runner_uid(race_uid: str, program_number: int, name_norm: str) -> str:
    """
    Generates a stable SHA1-based hash for a runner within a specific race.
    """
    base_string = f"{race_uid}-{program_number}-{name_norm}"
    return hashlib.sha1(base_string.encode('utf-8')).hexdigest()


def normalize_name(name: str) -> str:
    """Normalize horse/race strings into a stable, readable identifier.
    Expected by tests: preserve word boundaries (CHEVAL UN), uppercase, strip accents.
    """
    if not name:
        return ""
    s = str(name).strip()

    # Strip accents
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))

    # Replace any non-alphanumeric with spaces (keeps word boundaries)
    s = re.sub(r"[^A-Za-z0-9]+", " ", s)

    # Collapse spaces and uppercase
    s = re.sub(r"\s+", " ", s).strip().upper()
    return s

