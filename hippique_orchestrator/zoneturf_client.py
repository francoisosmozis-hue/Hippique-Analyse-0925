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

            if not soup.find(string=re.compile("page suivante", re.I)):
                break
        except requests.RequestException as e:
            logger.warning(
                f"Failed to resolve Zone-Turf ID for {horse_name} due to network error: {e}"
            )
            break

    logger.warning(f"Could not find Zone-Turf ID for '{horse_name}' after searching pages.")
    ID_CACHE[normalized_name] = None  # Cache failure to avoid retries
    return None

PERSON_ID_CACHE: dict[str, str | None] = {}

def resolve_person_id(person_name: str, person_type: str, session: requests.Session, max_pages: int = 20) -> str | None:
    """
    Finds the Zone-Turf ID for a jockey or trainer by scraping alphabetical search pages.
    Uses a cache to avoid repeated lookups.
    `person_type` should be 'jockey' or 'entraineur'.
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

    logger.info(f"Resolving Zone-Turf ID for '{person_name}' ({person_type}) via alphabetical pages...")
    for page_num in range(1, max_pages + 1):
        # Adjust URL path based on person_type
        url = f"{BASE_URL}/{person_type}/lettre-{first_letter}.html?p={page_num}"
        try:
            response = session.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            if response.status_code != 200:
                break

            soup = BeautifulSoup(response.text, "html.parser")
            for a_tag in soup.find_all("a", href=True):
                tag_text = _normalize_name(a_tag.get_text(" ", strip=True))
                if tag_text == normalized_name and f"/{person_type}/" in a_tag["href"]:
                    match = re.search(r"-(\d+)/?$", a_tag["href"])
                    if match:
                        found_id = match.group(1)
                        logger.info(f"Resolved '{person_name}' ({person_type}) to ID: {found_id}")
                        PERSON_ID_CACHE[cache_key] = found_id
                        return found_id

            if not soup.find(string=re.compile("page suivante", re.I)):
                break
        except requests.RequestException as e:
            logger.warning(
                f"Failed to resolve Zone-Turf ID for {person_name} ({person_type}) due to network error: {e}"
            )
            break

    logger.warning(f"Could not find Zone-Turf ID for '{person_name}' ({person_type}) after searching pages.")
    PERSON_ID_CACHE[cache_key] = None
    return None


def fetch_chrono_from_html(html_content: str) -> dict[str, Any] | None:
    """
    Parses the HTML content of a Zone-Turf horse page to extract chrono data.
    """
    if not html_content:
        return None

    soup = BeautifulSoup(html_content, 'html.parser')

    record_attele = None
    last_3_chronos: list[float] = []

    # 1. Find the record ("Record Attelé")
    # It's in a <p> tag within a <div class="card-body">
    card_bodies = soup.find_all('div', class_='card-body')
    for body in card_bodies:
        p_tags = body.find_all('p')
        for p in p_tags:
            strong_tag = p.find('strong')
            if strong_tag and 'Record Attelé' in strong_tag.text:
                # The value is the text immediately after the <strong> tag
                record_str = strong_tag.next_sibling
                if record_str:
                    record_attele = _parse_rk_string(record_str.strip())
                break
        if record_attele:
            break

    # 2. Find the last 3 chronos from the performance tables
    # The performances are in a list of `li` tags, each with its own table
    perf_list = soup.find('ul', class_='list-group')
    if perf_list:
        list_items = perf_list.find_all('li', class_='list-group-item')
        for item in list_items:
            if len(last_3_chronos) >= 3:
                break

            # Check if the race is "Attelé"
            # The discipline is in a <p> tag like "19 000€ - Prix Axius - Attelé - ..."
            discipline_p = item.find('p', string=re.compile(r'Attelé'))
            if not discipline_p:
                continue

            perf_table = item.find('table', class_='table')
            if perf_table and perf_table.thead and perf_table.tbody:
                header_cells = perf_table.thead.find_all('th')
                rk_index = -1
                for i, cell in enumerate(header_cells):
                    if 'Red.Km' in cell.text:
                        rk_index = i
                        break

                if rk_index != -1:
                    rows = perf_table.tbody.find_all('tr')
                    for row in rows:
                        cells = row.find_all('td')
                        if len(cells) > rk_index:
                            # Check if this row is for the horse "Jullou"
                            if 'Jullou' in row.text:
                                chrono_str = cells[rk_index].text.strip()
                                parsed_chrono = _parse_rk_string(chrono_str)
                                if parsed_chrono:
                                    last_3_chronos.append(parsed_chrono)
                                    # Found the chrono for this race, break from inner loop
                                    break

    if not record_attele and not last_3_chronos:
        return None

    return {'record_attele': record_attele, 'last_3_chrono': last_3_chronos}

def fetch_person_stats_from_html(html_content: str, person_type: str) -> dict[str, Any] | None:
    """
    Parses the HTML content of a Zone-Turf jockey/trainer page to extract performance data.
    Assumes person_type is 'jockey' or 'entraineur'.
    """
    if not html_content:
        return None

    soup = BeautifulSoup(html_content, 'html.parser')
    stats = {}

    # Look for common patterns for statistics (e.g., in a "stats-block" or similar div)
    # This is a generic approach; specific selectors might be needed after inspecting the actual page.
    stats_block = soup.find('div', class_='stats-block') or soup.find('div', class_='card-body')

    if stats_block:
        # Example: Try to find "Taux de réussite" or "Pourcentage"
        success_rate_match = re.search(r'(taux\s+de\s+réussite|pourcentage)\s*:\s*(\d+(\.\d+)?)\s*%', stats_block.get_text(), re.IGNORECASE)
        if success_rate_match:
            stats['win_rate'] = float(success_rate_match.group(2)) # Assuming 'win_rate' for now

        # Example: Try to find "Taux de réussite Place" or similar
        place_rate_match = re.search(r'(taux\s+de\s+réussite\s+place|pourcentage\s+placé)\s*:\s*(\d+(\.\d+)?)\s*%', stats_block.get_text(), re.IGNORECASE)
        if place_rate_match:
            stats['place_rate'] = float(place_rate_match.group(2))

        # Often, detailed stats are in tables. Let's look for common table headers.
        table = stats_block.find('table', class_='table')
        if table:
            # Example: look for <th> like "Victoires", "Places", "Courses"
            headers = [th.get_text(" ", strip=True) for th in table.find_all('th')]
            rows = table.find_all('tr')
            for row in rows:
                cols = row.find_all('td')
                if len(cols) == len(headers):
                    row_data = {headers[i]: cols[i].get_text(" ", strip=True) for i in range(len(headers))}
                    # Look for specific stats like 'nb courses', 'nb victoires', 'nb places'
                    if 'Courses' in row_data:
                        stats['num_races'] = int(row_data['Courses']) if row_data['Courses'].isdigit() else 0
                    if 'Victoires' in row_data:
                        stats['num_wins'] = int(row_data['Victoires']) if row_data['Victoires'].isdigit() else 0
                    if 'Places' in row_data:
                        stats['num_places'] = int(row_data['Places']) if row_data['Places'].isdigit() else 0

    if not stats:
        logger.warning(f"Could not extract any stats for {person_type} from HTML content.")
        return None

    return stats


def get_chrono_stats(horse_name: str, horse_id: str | None = None) -> dict[str, Any] | None:
    """
    Orchestrator function to get chrono stats for a horse.
    Resolves ID if not provided, then scrapes the page. Caches results.
    """
    cache_key = f"{horse_name}|{horse_id}"
    if cache_key in CHRONO_CACHE:
        return CHRONO_CACHE[cache_key]

    with requests.Session() as session:
        # Use provided ID or resolve it
        zt_id = horse_id or resolve_horse_id(horse_name, session)

        if not zt_id:
            logger.warning(f"Could not get Zone-Turf ID for horse: {horse_name}")
            CHRONO_CACHE[cache_key] = None
            return None
        # Slugify name for URL, simple version
        slug_name = _normalize_name(horse_name).replace(' ', '-')
        url = f"{BASE_URL}/cheval/{slug_name}-{zt_id}/"

        try:
            logger.info(f"Fetching chrono stats from Zone-Turf for {horse_name} at {url}")
            response = session.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            if response.status_code != 200:
                logger.error(
                    f"Failed to fetch Zone-Turf page for {horse_name} (ID: {zt_id}) with status {response.status_code}"
                )
                CHRONO_CACHE[cache_key] = None
                return None

            chrono_data = fetch_chrono_from_html(response.text)
            CHRONO_CACHE[cache_key] = chrono_data
            return chrono_data

        except requests.RequestException as e:
            logger.error(
                f"Failed to fetch Zone-Turf page for {horse_name} due to network error: {e}"
            )
            CHRONO_CACHE[cache_key] = None
            return None


PERSON_STATS_CACHE: dict[str, dict[str, Any] | None] = {}

def get_jockey_trainer_stats(person_name: str, person_type: str, person_id: str | None = None) -> dict[str, Any] | None:
    """
    Orchestrator function to get performance stats for a jockey or trainer.
    Resolves ID if not provided, then scrapes the page. Caches results.
    `person_type` should be 'jockey' or 'entraineur'.
    """
    cache_key = f"{person_type}_{person_name}|{person_id}"
    if cache_key in PERSON_STATS_CACHE:
        return PERSON_STATS_CACHE[cache_key]

    with requests.Session() as session:
        zt_id = person_id or resolve_person_id(person_name, person_type, session)

        if not zt_id:
            logger.warning(f"Could not get Zone-Turf ID for {person_type}: {person_name}")
            PERSON_STATS_CACHE[cache_key] = None
            return None

        slug_name = _normalize_name(person_name).replace(' ', '-')
        url = f"{BASE_URL}/{person_type}/{slug_name}-{zt_id}/"

        try:
            logger.info(f"Fetching stats from Zone-Turf for {person_type} {person_name} at {url}")
            response = session.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            if response.status_code != 200:
                logger.error(
                    f"Failed to fetch Zone-Turf page for {person_type} {person_name} (ID: {zt_id}) with status {response.status_code}"
                )
                PERSON_STATS_CACHE[cache_key] = None
                return None

            person_stats = fetch_person_stats_from_html(response.text, person_type)
            PERSON_STATS_CACHE[cache_key] = person_stats
            return person_stats

        except requests.RequestException as e:
            logger.error(
                f"Failed to fetch Zone-Turf page for {person_type} {person_name} due to network error: {e}"
            )
            PERSON_STATS_CACHE[cache_key] = None
            return None
