"""
Scraper for Geny.com to fetch daily race programs.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Any

import httpx
from bs4 import BeautifulSoup

from hippique_orchestrator.logging_utils import get_logger

logger = get_logger(__name__)

def _slugify(value: str) -> str:
    """Return a slug suitable for URLs from a human readable string."""
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-z0-9]+", "-", value.lower())
    return value.strip("-")

def fetch_geny_programme() -> dict[str, Any]:
    """
    Fetches the Geny page for today's races and returns them as a dictionary.

    Returns:
        A dictionary containing the date and a list of meetings, or an empty
        structure if fetching fails.
        {
            "date": "2025-10-16",
            "meetings": [
                {
                    "r": "R1",
                    "hippo": "Paris-Vincennes (FR)",
                    "slug": "paris-vincennes",
                    "courses": [
                        {"c": "C1", "id_course": "12345"},
                        ...
                    ]
                }
            ]
        }
    """
    today = datetime.today().strftime("%d-%m-%Y")
    url = f"https://www.genybet.fr/reunions/{today}"
    empty_response = {"date": datetime.today().strftime("%Y-%m-%d"), "meetings": []}

    try:
        response = httpx.get(url, follow_redirects=True, timeout=10.0)
        response.raise_for_status()
        html_content = response.text
    except httpx.RequestError as e:
        logger.error(f"An error occurred while requesting {e.request.url!r}: {e}")
        return empty_response
    except httpx.HTTPStatusError as e:
        logger.error(f"Error response {e.response.status_code} while requesting {e.request.url!r}: {e}")
        return empty_response

    soup = BeautifulSoup(html_content, "html.parser")

    meetings_map: dict[str, dict[str, Any]] = {}
    r_counter = 1

    next_races_container = soup.find(id="next-races-container")
    if not next_races_container:
        logger.warning("No 'next-races-container' found on Geny page.")
        return empty_response

    for row in next_races_container.select("table tbody tr"):
        hippo_el = row.select_one("th.race-name")
        if not hippo_el:
            logger.warning("Could not find meeting element 'th.race-name' in a row. Skipping row.")
            continue
        hippo = hippo_el.get_text(strip=True)
        slug = _slugify(hippo)

        c_el = row.select_one("td a")
        if not c_el:
            continue
        c = c_el.get_text(strip=True)

        data_id = row.get("id")
        id_course = data_id.replace("race_", "") if data_id else None
        if not id_course:
            href = c_el.get("href", "")
            id_match = re.search(r"(\d+)$", href)
            if id_match:
                id_course = id_match.group(1)

        if hippo not in meetings_map:
            meetings_map[hippo] = {
                "r": f"R{r_counter}",
                "hippo": hippo,
                "slug": slug,
                "courses": []
            }
            r_counter += 1

        meetings_map[hippo]["courses"].append({"c": c, "id_course": id_course})

    meetings = list(meetings_map.values())

    data = {
        "date": datetime.today().strftime("%Y-%m-%d"),
        "meetings": meetings,
    }

    logger.info(f"Discovered {len(meetings)} meetings from Geny")
    return data
