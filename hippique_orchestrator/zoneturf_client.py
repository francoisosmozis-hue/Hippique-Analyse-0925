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
PERSON_ID_CACHE: dict[str, str | None] = {}
PERSON_STATS_CACHE: dict[str, dict[str, Any] | None] = {}


def _normalize_name(s: str) -> str:
    """Normalizes a horse name for comparison by removing parentheses, apostrophes,
    replacing hyphens with spaces, converting to lowercase, and handling unicode."""
    if not s:
        return ""
    # Remove content within parentheses
    s = re.sub(r"\(.*\)", "", s)
    # Remove apostrophes
    s = s.replace("'", "")
    # Replace hyphens with spaces
    s = s.replace("-", " ")
    # Normalize unicode characters
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    # Convert to lowercase, strip leading/trailing whitespace, and collapse multiple spaces
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


def resolve_horse_id(horse_name: str, max_pages: int = 20) -> str | None:
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
    with requests.Session() as session:
        for page_num in range(1, max_pages + 1):
            url = f"{BASE_URL}/cheval/lettre-{first_letter}.html?p={page_num}"
            try:
                response = session.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
                if response.status_code != 200:
                    logger.warning(
                        f"Received non-200 status code {response.status_code} for URL: {url}"
                    )
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
            except requests.exceptions.RequestException as e:
                logger.warning(f"Failed to fetch page {url}: {e}")
                break
    ID_CACHE[normalized_name] = None
    return None


def fetch_chrono_from_html(html_content: str, horse_name: str) -> dict[str, Any] | None:
    """
    Parses the HTML of a horse's page to extract chrono information.
    """
    if not html_content:
        return None

    soup = BeautifulSoup(html_content, "html.parser")
    result: dict[str, Any] = {"last_3_chrono": []}
    normalized_horse_name = _normalize_name(horse_name)

    # Locate the "Informations générales" card-body for the record
    info_card_header = soup.find(
        "div", class_="card-header", string=re.compile(r"\s*Informations générales\s*")
    )
    if info_card_header:
        info_card_body = info_card_header.find_next_sibling("div", class_="card-body")
        if info_card_body:
            record_tag = None
            for p_tag in info_card_body.find_all("p"):
                if p_tag.strong and "Record Attelé" in p_tag.strong.get_text():
                    record_tag = p_tag
                    break

            if record_tag and record_tag.strong:
                record_text = (
                    record_tag.strong.next_sibling
                )  # Use next_sibling to get the text after the strong tag
                if record_text:  # Add a check to ensure record_text is not None before stripping
                    result["record_attele"] = _parse_rk_string(record_text.strip())

    # Locate the "Performances détaillées" section
    performance_card_header = soup.find(
        "div", class_="card-header", string=re.compile(r"\s*Performances détaillées\s*")
    )
    if performance_card_header:
        performance_card_body = performance_card_header.find_next_sibling("div", class_="card-body")
        if performance_card_body:
            performance_list = performance_card_body.find("ul", class_="list-group")
            if performance_list:
                for li in performance_list.find_all("li", class_="list-group-item"):
                    # Check if it's an "Attelé" race within the list item's text
                    if "Attelé" in li.get_text():
                        table = li.find("table")
                        if table:
                            # Find the index of the 'Red.Km' column
                            headers = [
                                th.get_text(strip=True) for th in table.find("thead").find_all("th")
                            ]
                            try:
                                red_km_idx = headers.index("Red.Km")
                            except ValueError:
                                logger.debug(
                                    "Red.Km column not found in table headers. Skipping this table."
                                )
                                continue

                            for row in table.find("tbody").find_all("tr"):
                                cells = row.find_all("td")
                                if len(cells) > 1:  # Ensure there's at least the horse name column (index 1)
                                    name_in_row = _normalize_name(cells[1].get_text(strip=True)) # Corrected index for horse name
                                    if name_in_row == normalized_horse_name:
                                        if len(cells) > red_km_idx:
                                            chrono_str = cells[red_km_idx].get_text(strip=True)
                                            chrono = _parse_rk_string(chrono_str)
                                            if chrono is not None:
                                                result["last_3_chrono"].append(chrono)
                                        # Stop searching if we have found 3 chronos for this horse
                                        if len(result["last_3_chrono"]) >= 3:
                                            break  # Breaks the inner 'for row' loop

                    if len(result["last_3_chrono"]) >= 3:
                        break  # Breaks the outer 'for li' loop

    # Filter to the first 3 chronos (most recent)
    result["last_3_chrono"] = result["last_3_chrono"][:3]

    # Return result even if mostly empty, so subsequent calls don't fail on NoneType
    return result


def resolve_person_id(person_name: str, person_type: str, max_pages: int = 20) -> str | None:
    """
    Finds the Zone-Turf ID for a person (jockey or entraineur) by scraping the alphabetical search pages.
    Uses a cache to avoid repeated lookups.
    """
    normalized_name = _normalize_name(person_name)
    if not normalized_name:
        return None

    cache_key = f"{person_type}_{normalized_name}"
    if cache_key in PERSON_ID_CACHE:
        return PERSON_ID_CACHE[cache_key]

    first_letter = next((c for c in normalized_name if c.isalpha()), None)
    if not first_letter:
        PERSON_ID_CACHE[cache_key] = None
        return None

    logger.info(
        f"Resolving Zone-Turf ID for '{person_name}' ({person_type}) via alphabetical pages..."
    )
    with requests.Session() as session:
        for page_num in range(1, max_pages + 1):
            url = f"{BASE_URL}/{person_type}/lettre-{first_letter}.html?p={page_num}"
            try:
                response = session.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
                if response.status_code != 200:
                    logger.warning(
                        f"Received non-200 status code {response.status_code} for URL: {url}"
                    )
                    break

                soup = BeautifulSoup(response.text, "html.parser")
                for a_tag in soup.find_all("a", href=True):
                    tag_text = _normalize_name(a_tag.get_text(" ", strip=True))
                    if tag_text == normalized_name and f"/{person_type}/" in a_tag["href"]:
                        match = re.search(r"-(\d+)/?$", a_tag["href"])
                        if match:
                            found_id = match.group(1)
                            logger.info(f"Resolved '{person_name}' to ID: {found_id}")
                            PERSON_ID_CACHE[cache_key] = found_id
                            return found_id
            except requests.exceptions.RequestException as e:
                logger.warning(f"Failed to fetch page {url}: {e}")
                break

    PERSON_ID_CACHE[cache_key] = None
    return None


def fetch_person_stats_from_html(html_content: str, person_type: str) -> dict[str, Any] | None:
    """
    Parses the HTML of a person's page to extract their stats.
    """
    if not html_content:
        return None

    soup = BeautifulSoup(html_content, "html.parser")
    stats_div = soup.find("div", class_="infos-personne clearfix")
    if not stats_div:
        return None

    win_rate = None
    place_rate = None

    # Search in ul.infos-personne-perf for "Réussite à la gagne" and "Réussite à la place"
    perf_list = stats_div.find("ul", class_="infos-personne-perf")
    if perf_list:
        for li_tag in perf_list.find_all("li"):
            li_text = li_tag.get_text().strip()
            if "Réussite à la gagne" in li_text:
                win_rate_match = re.search(r"Réussite à la gagne\s*:\s*(\d+[.,]?\d*)?%", li_text)
                if win_rate_match and win_rate_match.group(1):
                    win_rate = float(win_rate_match.group(1).replace(",", "."))
            elif "Réussite à la place" in li_text:
                place_rate_match = re.search(r"Réussite à la place\s*:\s*(\d+[.,]?\d*)?%", li_text)
                if place_rate_match and place_rate_match.group(1):
                    place_rate = float(place_rate_match.group(1).replace(",", "."))

    num_races = None
    num_wins = None
    num_places = None

    # Search in ul.infos-personne-general for "Courses courues", "Nb de victoires", "Nb de places"
    general_list = stats_div.find("ul", class_="infos-personne-general")
    if general_list:
        for li_tag in general_list.find_all("li"):
            li_text = li_tag.get_text().strip()
            if "Courses courues" in li_text:
                num_races_match = re.search(r"Courses courues\s*:\s*(\d+)", li_text)
                if num_races_match:
                    num_races = int(num_races_match.group(1))
            elif "Nb de victoires" in li_text:
                num_wins_match = re.search(r"Nb de victoires\s*:\s*(\d+)", li_text)
                if num_wins_match:
                    num_wins = int(num_wins_match.group(1))
            elif "Nb de places" in li_text:
                num_places_match = re.search(r"Nb de places\s*:\s*(\d+)", li_text)
                if num_places_match:
                    num_places = int(num_places_match.group(1))

    if not all(
        [
            place_rate is not None, # Win rate can be None
            num_races is not None,
            num_places is not None, # Num wins can be None
        ]
    ):
        return None

    return {
        "win_rate": win_rate,
        "place_rate": place_rate,
        "num_races": num_races,
        "num_wins": num_wins,
        "num_places": num_places,
    }


def get_chrono_stats(horse_name: str) -> dict[str, Any] | None:
    """
    Fetches chrono stats for a given horse.
    """
    normalized_name = _normalize_name(horse_name)
    if not normalized_name:
        return None

    if normalized_name in CHRONO_CACHE:
        return CHRONO_CACHE[normalized_name]

    with requests.Session() as session:
        horse_id = resolve_horse_id(horse_name)
        if not horse_id:
            logger.warning(f"Could not get Zone-Turf ID for horse: {horse_name}")
            CHRONO_CACHE[normalized_name] = None
            return None

        url = f"{BASE_URL}/cheval/{normalized_name.replace(' ', '-')}-{horse_id}/"
        try:
            response = session.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            if response.status_code != 200:
                logger.warning(
                    f"Failed to fetch Zone-Turf page for {horse_name} (ID: {horse_id}) with status {response.status_code}"
                )
                CHRONO_CACHE[normalized_name] = None
                return None
            stats = fetch_chrono_from_html(response.text, horse_name)
            CHRONO_CACHE[normalized_name] = stats
            return stats
        except requests.RequestException:
            logger.warning(f"Failed to fetch Zone-Turf page for {horse_name} due to network error")
            CHRONO_CACHE[normalized_name] = None
            return None


def get_jockey_trainer_stats(person_name: str, person_type: str) -> dict[str, Any] | None:
    """
    Fetches stats for a given jockey or trainer.
    """
    normalized_name = _normalize_name(person_name)
    if not normalized_name:
        return None

    cache_key = f"{person_type}_{normalized_name}"
    if cache_key in PERSON_STATS_CACHE:
        return PERSON_STATS_CACHE[cache_key]

    with requests.Session() as session:
        person_id = resolve_person_id(person_name, person_type)
        if not person_id:
            logger.warning(f"Could not get Zone-Turf ID for {person_type}: {person_name}")
            PERSON_STATS_CACHE[cache_key] = None
            return None

        url = f"{BASE_URL}/{person_type}/{normalized_name.replace(' ', '-')}-{person_id}/"
        try:
            response = session.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            if response.status_code != 200:
                logger.warning(
                    f"Failed to fetch Zone-Turf page for {person_type} {person_name} (ID: {person_id}) with status {response.status_code}"
                )
                PERSON_STATS_CACHE[cache_key] = None
                return None
            stats = fetch_person_stats_from_html(response.text, person_type)
            PERSON_STATS_CACHE[cache_key] = stats
            return stats
        except requests.RequestException:
            logger.warning(
                f"Failed to fetch Zone-Turf page for {person_type} {person_name} due to network error"
            )
            PERSON_STATS_CACHE[cache_key] = None
            return None
