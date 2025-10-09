"""
fetch_french_races_week.py
===================================

This script retrieves the PMU race programmes for the current day and the next
six days (a full week) and extracts only those races taking place on French
soil.  It uses the undocumented PMU turfinfo API that powers their mobile and
tablet applications, attempting multiple hosts and client IDs as fallbacks.

The extracted data includes the date, reunion number, racecourse name,
course number, race name, discipline and scheduled start time.  Results are
printed to standard output.

Usage:

    python fetch_french_races_week.py

Note: The PMU turfinfo API is not officially documented and may impose
restrictions.  This script makes a best-effort attempt to retrieve data;
if all hosts return 403 errors, consider running it from an environment
where the turfinfo endpoints are allowed.
"""

import datetime
import json
from typing import Dict, List, Optional

try:
    import requests  # type: ignore
except ImportError:
    raise ImportError("The 'requests' library is required. Please install it with 'pip install requests'.")


HOSTS: List[str] = [
    "offline.turfinfo.api.pmu.fr",
    "online.turfinfo.api.pmu.fr",
    "tablette.turfinfo.api.pmu.fr",
]

# Different client identifiers have been observed in the wild.  We try a
# couple of these; if one fails, the next one might succeed.
CLIENT_IDS: List[int] = [7, 61]


def fetch_program(date: datetime.date) -> Optional[Dict]:
    """
    Attempt to fetch the PMU race programme for the given date.  The API
    expects dates in the format DDMMYYYY.  Multiple hosts and client IDs
    are tried in sequence; the first successful JSON response is returned.

    Args:
        date: The date of the programme to fetch.

    Returns:
        The deserialised JSON payload if retrieval is successful; None
        otherwise.
    """
    date_str = date.strftime("%d%m%Y")
    for host in HOSTS:
        for client_id in CLIENT_IDS:
            url = f"https://{host}/rest/client/{client_id}/programme/{date_str}"
            try:
                response = requests.get(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (compatible; PMUDataFetcher/1.0)",
                        "Referer": "https://www.pmu.fr/",
                    },
                    timeout=10,
                )
                if response.status_code == 200:
                    try:
                        return response.json()
                    except json.JSONDecodeError:
                        # Unexpected content; continue trying.
                        continue
            except requests.RequestException:
                # Networking issue or forbidden; try next host/client.
                continue
    return None


def extract_french_courses(program: Dict) -> List[Dict[str, str]]:
    """
    Extract all courses held in France from a programme payload.

    Args:
        program: The JSON payload returned by the turfinfo API.

    Returns:
        A list of dictionaries containing course details for French races.
    """
    results: List[Dict[str, str]] = []

    # The JSON structure can vary slightly; handle both top-level and nested
    # 'programme' keys.  We normalise the structure into a list of reunions.
    reunions: Optional[List[Dict]] = None
    if isinstance(program, dict):
        if "programme" in program and isinstance(program["programme"], dict):
            reunions = program["programme"].get("reunions")
            date_str = program["programme"].get("dateJournee")
        else:
            reunions = program.get("reunions")
            date_str = program.get("dateJournee")
    else:
        return results  # unexpected format

    if not reunions:
        return results

    for reunion in reunions:
        # Determine country code.  The country may be nested differently depending
        # on the version of the API.
        pays_code = None
        # Some payloads nest the hippodrome under 'hippodrome' -> 'pays' -> 'code'
        hippo = reunion.get("hippodrome", {}) if isinstance(reunion, dict) else {}
        if isinstance(hippo, dict):
            pays_code = hippo.get("pays", {}).get("code")
            hippodrome_name = hippo.get("libelleLong") or hippo.get("libelle")
        # Fallback directly under 'pays'
        if pays_code is None:
            pays_code = reunion.get("pays", {}).get("code")
            hippodrome_name = reunion.get("hippodrome", "")

        if pays_code != "FRA":
            continue

        # Reunion number and start time may be present at different keys.
        reunion_num = reunion.get("numReunion") or reunion.get("numOrdre") or "?"

        # Extract courses list; may be missing if meeting is cancelled.
        courses = reunion.get("courses", [])
        for course in courses:
            # Each course has a number, name, discipline and scheduled start time.
            course_num = course.get("numOrdre") or course.get("numeroOrdre", "?")
            race_name = course.get("libelle") or "(libellé inconnu)"
            discipline = course.get("discipline") or course.get("specialite") or "?"
            heure = course.get("heureDepart") or course.get("departTheorique") or "?"
            results.append(
                {
                    "date": date_str or "",
                    "reunion_num": str(reunion_num),
                    "hippodrome": hippodrome_name or "",
                    "course_num": str(course_num),
                    "race_name": race_name,
                    "discipline": discipline,
                    "time": heure,
                }
            )
    return results


def main() -> None:
    """
    Fetch French horse race programmes for today and the following six days.
    For each day, print a summary of French races to stdout.  If no data is
    available for a given date, a notice is printed instead.
    """
    today = datetime.date.today()
    for offset in range(7):
        current_date = today + datetime.timedelta(days=offset)
        program = fetch_program(current_date)
        print("\n=== {}".format(current_date.strftime("%Y-%m-%d")))
        if not program:
            print("Aucune donnée disponible ou accès refusé pour cette date.")
            continue
        courses = extract_french_courses(program)
        if not courses:
            print("Aucune course française trouvée pour cette date.")
            continue
        # Group by reunion for nicer output
        courses.sort(key=lambda c: (c["reunion_num"], c["course_num"]))
        current_reunion = None
        for c in courses:
            if c["reunion_num"] != current_reunion:
                current_reunion = c["reunion_num"]
                print(f"\nRéunion {current_reunion} – {c['hippodrome']}:")
            print(
                f"  R{c['reunion_num']}C{c['course_num']} – {c['race_name']} "
                f"({c['discipline']}) à {c['time']}"
            )


if __name__ == "__main__":
    main()
