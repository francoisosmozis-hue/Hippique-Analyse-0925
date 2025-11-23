"""Discover today's PMU meetings and courses from Geny.

This script fetches the list of today's meetings from geny.com and
outputs a JSON document describing the meetings and courses.
"""

from __future__ import annotations

import json
import re
import subprocess
import unicodedata
from datetime import datetime
from typing import Any

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

    meetings_map: dict[str, dict[str, Any]] = {}
    r_counter = 1

    # Find the "prochaines courses" section
    next_races_container = soup.find(id="next-races-container")
    if not next_races_container:
        print("No 'next-races-container' found.")
        print(json.dumps({"date": datetime.today().strftime("%Y-%m-%d"), "meetings": []}, ensure_ascii=False, indent=2))
        return

    # Iterate through each race row
    for row in next_races_container.select("table tbody tr"):
        # Extract meeting name (hippo)
        hippo_el = row.select_one("th.race-name")
        if not hippo_el:
            continue
        hippo = hippo_el.get_text(strip=True)
        slug = _slugify(hippo)

        # Extract course number (c)
        c_el = row.select_one("td.race a")
        if not c_el:
            continue
        c = c_el.get_text(strip=True) # e.g., "C1"

        # Extract course ID (id_course)
        data_id = row.get("id") # e.g., "race_1617526"
        id_course = data_id.replace("race_", "") if data_id else None
        if not id_course:
            # Fallback to href if id is not present or malformed
            href = c_el.get("href", "")
            id_match = re.search(r"(\d+)$", href)
            if id_match:
                id_course = id_match.group(1)

        if not id_course:
            continue

        # Group by meeting
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
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
