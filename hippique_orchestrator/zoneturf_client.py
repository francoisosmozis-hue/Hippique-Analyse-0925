# hippique_orchestrator/zoneturf_client.py
import logging
import re
import unicodedata
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)
BASE_URL = "https://www.zone-turf.fr"
# Simple in-memory cache. A persistent cache (like Firestore) is recommended for production.
ID_CACHE: Dict[str, Optional[str]] = {}
CHRONO_CACHE: Dict[str, Optional[Dict[str, Any]]] = {}


def _normalize_name(s: str) -> str:
    """Normalizes a horse name for comparison."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().strip().split())


def _parse_rk_string(rk_string: str) -> Optional[float]:
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


def resolve_horse_id(horse_name: str, session: requests.Session, max_pages: int = 20) -> Optional[str]:
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
            logger.warning(f"Failed to resolve Zone-Turf ID for {horse_name} due to network error: {e}")
            break
    
    logger.warning(f"Could not find Zone-Turf ID for '{horse_name}' after searching pages.")
    ID_CACHE[normalized_name] = None # Cache failure to avoid retries
    return None


def fetch_chrono_from_html(html_content: str) -> Optional[Dict[str, Any]]:
    """
    Parses the HTML content of a Zone-Turf horse page to extract chrono data.
    """
    if not html_content:
        return None

    soup = BeautifulSoup(html_content, 'html.parser')
    
    record_attelé = None
    last_3_chronos: List[float] = []

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
                    record_attelé = _parse_rk_string(record_str.strip())
                break
        if record_attelé:
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
    
    if not record_attelé and not last_3_chronos:
        return None

    return {
        'record_attelé': record_attelé,
        'last_3_chrono': last_3_chronos
    }

def get_chrono_stats(horse_name: str, horse_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
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
                logger.error(f"Failed to fetch Zone-Turf page for {horse_name} (ID: {zt_id}) with status {response.status_code}")
                CHRONO_CACHE[cache_key] = None
                return None
            
            chrono_data = fetch_chrono_from_html(response.text)
            CHRONO_CACHE[cache_key] = chrono_data
            return chrono_data

        except requests.RequestException as e:
            logger.error(f"Failed to fetch Zone-Turf page for {horse_name} due to network error: {e}")
            CHRONO_CACHE[cache_key] = None
            return None
