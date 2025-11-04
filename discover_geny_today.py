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
import subprocess

import requests
from bs4 import BeautifulSoup

def _slugify(value: str) -> str:
    """Return a slug suitable for URLs from a human readable string."""
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-z0-9]+", "-", value.lower())
    return value.strip("-")

def _is_fr_meeting(section: BeautifulSoup) -> bool:
    """Determine whether a meeting takes place in France."""
    flag_el = section.select_one("span.flag")
    if flag_el:
        return "flag-fr" in flag_el.get("class", [])
    return True # Assume FR if no flag found


def main() -> None:
    """Fetch the Geny page and print meetings as JSON."""
    today = datetime.today().strftime("%d-%m-%Y")
    url = f"https://www.genybet.fr/reunions/{today}"
    
    try:
        result = subprocess.run(['curl', '-s', url], capture_output=True, text=True, check=True)
        html_content = result.stdout
    except subprocess.CalledProcessError as e:
        print(f"Curl failed: {e.stderr}")
        return

    soup = BeautifulSoup(html_content, "html.parser")

    meetings: List[Dict[str, Any]] = []
    meeting_elements = soup.select("li.prog-meeting-name")
    race_elements = soup.select("div.timeline-container li.meeting")

    for i, section in enumerate(meeting_elements):
        title_el = section.select_one("a.meeting-name-link")
        if not title_el:
            continue
        
        if not _is_fr_meeting(section):
            continue

        title = title_el.get_text(strip=True)
        r_match = re.search(r"R\d+", title)
        if not r_match:
            continue
        r = r_match.group(0)
        hippo = section.select_one("span.nomReunion").get_text(strip=True)
        slug = _slugify(hippo)

        courses: List[Dict[str, Any]] = []
        if i < len(race_elements):
            for row in race_elements[i].select("li.race"):
                course_cell = row.select_one("a")
                if not course_cell:
                    continue
                c = course_cell.get_text(strip=True)

                course_obj: Dict[str, Any] = {"c": c}
                data_id = row.get("data-id")
                if data_id:
                    course_obj["id_course"] = data_id
                
                href = course_cell.get("href", "")
                id_match = re.search(r"(\d+)$", href)
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