# hippique_orchestrator/zoneturf_client.py
import logging
import re
import unicodedata
from typing import Any

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)
BASE_URL = "https://www.zone-turf.fr"
# Simple in-memory cache. A persistent cache (like Firestore) is recommended for production.
ID_CACHE: dict[str, str | None] = {}
CHRONO_CACHE: dict[str, dict[str, Any] | None] = {}


def _normalize_name(s: str) -> str:
    """Normalizes a horse name for comparison."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().strip().split())


def _parse_rk_string(rk_string: str) -> float | None:
    """Parses a reduction kilometer string like "1'11"6" or "1'11''6" into seconds."""
    if not isinstance(rk_string, str) or not rk_string.strip():
        return None
    # Handles 1'11"6, 1'11''6 and other variations
    match = re.match(r"(\d+)'(\d{2})[',\"]+(\d+)", rk_string.strip())
    if not match:
        return None
    try:
        minutes, seconds, tenths = map(int, match.groups())
        return minutes * 60 + seconds + tenths / 10.0
    except (ValueError, TypeError):
        return None


def resolve_horse_id(horse_name: str, session: requests.Session, max_pages: int = 20) -> str | None:
    """
    Finds the Zone-Turf ID for a horse by scraping the alphabetical search pages.
    Uses a cache to avoid repeated lookups.
    """
    normalized_name = _normalize_name(horse_name)
    if not normalized_name:
        return None

    if normalized_name in ID_CACHE:
        return ID_CACHE[normalized_name]

    first_letter = next((c for c in normalized_name if c.isalpha()), None)
    if not first_letter:
        ID_CACHE[normalized_name] = None
        return None

    logger.info(f"Resolving Zone-Turf ID for '{horse_name}' via alphabetical pages...")
    for page_num in range(1, max_pages + 1):
        url = f"{BASE_URL}/cheval/lettre-{first_letter}.html?p={page_num}"
        try:
            response = session.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            if response.status_code != 200:
                break

            soup = BeautifulSoup(response.text, "html.parser")
            for a_tag in soup.find_all("a", href=True):
                tag_text = _normalize_name(a_tag.get_text(" ", strip=True))
                                    if tag_text == normalized_name and "/cheval/" in a_tag["href"]:
                                        match = re.search(r"-(\d+)/?$", a_tag["href"])
                                        if match:
                                            found_id = match.group(1)
                                            logger.info(f"Resolved '{horse_name}' to ID: {found_id}")
                                            ID_CACHE[normalized_name] = found_id
                                            return found_id
