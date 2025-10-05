"""Discover today's PMU meetings and courses from Geny.

This script fetches the list of today's meetings from geny.com and
outputs a JSON document describing the meetings and courses.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from typing import List, Dict, Any

import requests
from bs4 import BeautifulSoup

URL = "https://www.geny.com/reunions-courses-pmu/_daujourdhui"


def _slugify(value: str) -> str:
    """Return a slug suitable for URLs from a human readable string."""
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-z0-9]+", "-", value.lower())
    return value.strip("-")


def _is_fr_meeting(hippo: str) -> bool:
    """Determine whether a meeting takes place in France.

    The hippo string often ends with a country code wrapped in parentheses
    such as ``"Paris-Vincennes (FR)"``. If a country code is present and
    differs from ``FR`` the meeting is considered foreign.
    """

    match = re.search(r"\(([A-Z]{2})\)$", hippo)
    if match:
        return match.group(1) == "FR"
    return True


def main() -> None:
    """Fetch the Geny page and print meetings as JSON."""
    resp = requests.get(URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    meetings: List[Dict[str, Any]] = []
    for section in soup.select("section.reunion"):
        title_el = section.select_one("h2")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        r_match = re.search(r"R\d+", title)
        if not r_match:
            continue
        r = r_match.group(0)
        hippo = title[r_match.end() :].strip()
        if not _is_fr_meeting(hippo):
            continue
        slug = _slugify(hippo)

        courses: List[Dict[str, Any]] = []
        for a in section.select("a"):
            text = a.get_text(strip=True)
            c_match = re.search(r"C\d+", text)
            if not c_match:
                continue
            c = c_match.group(0)
            href = a.get("href", "")
            id_match = re.search(r"(\d+)(?:\.html)?$", href)
            course_obj: Dict[str, Any] = {"c": c}
            if id_match:
                course_obj["id_course"] = id_match.group(1)
            courses.append(course_obj)

        meetings.append({"r": r, "hippo": hippo, "slug": slug, "courses": courses})

    data = {
        "date": datetime.today().strftime("%Y-%m-%d"),
        "meetings": meetings,
    }
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
