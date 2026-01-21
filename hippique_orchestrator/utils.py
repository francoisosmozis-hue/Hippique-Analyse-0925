# hippique_orchestrator/utils.py
"""
Utility functions for ID generation, normalization, and other helpers.
"""
import hashlib
import unicodedata

def normalize_name(name: str) -> str:
    """
    Normalizes a name by converting to uppercase, removing accents, and stripping whitespace.
    """
    if not name:
        return ""
    # NFD normalization splits characters and their accents
    # We then filter out non-spacing marks (the accents)
    nfkd_form = unicodedata.normalize('NFD', name)
    only_ascii = "".join([c for c in nfkd_form if not unicodedata.combining(c)])
    return only_ascii.upper().strip()


def generate_race_uid(
    race_date: str, 
    venue: str, 
    race_number: int, 
    discipline: str, 
    distance: int, 
    scheduled_time: str
) -> str:
    """
    Generates a stable, unique ID for a race.
    Inputs should be normalized/stringified before calling.
    """
    base_string = (
        f"{race_date}-{normalize_name(venue)}-{race_number}-"
        f"{normalize_name(discipline)}-{distance}-{scheduled_time}"
    )
    return hashlib.sha256(base_string.encode('utf-8')).hexdigest()[:16]


def generate_runner_uid(race_uid: str, program_number: int, name_norm: str) -> str:
    """
    Generates a stable, unique ID for a runner within a specific race.
    """
    base_string = f"{race_uid}-{program_number}-{name_norm}"
    return hashlib.sha256(base_string.encode('utf-8')).hexdigest()[:16]
