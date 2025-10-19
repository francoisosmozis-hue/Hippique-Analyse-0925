"""
Module d'extraction avancée des données ZEturf
Version intégrée pour l'orchestrateur Cloud Run
"""
import json
import logging
import re
from time import sleep
from typing import Any

import requests
from bs4 import BeautifulSoup

# Configuration du logging standard
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def _extract_start_time(html_content: str, course_id: str = "") -> str | None:
    """
    Extrait l'heure de départ d'une course depuis le HTML ZEturf.
    
    Args:
        html_content: HTML de la page course
        course_id: Identifiant R?C? de la course (optionnel)
    
    Returns:
        Heure au format "HH:MM" ou None
    """
    try:
        soup = BeautifulSoup(html_content, 'html.parser')

        # 1. Chercher dans JSON-LD (métadonnées structurées)
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and 'startDate' in data:
                    # Format ISO: "2025-10-17T14:30:00+02:00"
                    dt = data['startDate']
                    match = re.search(r'T(\d{2}):(\d{2})', dt)
                    if match:
                        time_str = f"{match.group(1)}:{match.group(2)}"
                        logger.info(f"Extracted time from JSON-LD: {time_str}")
                        return time_str
            except (json.JSONDecodeError, TypeError):
                continue

        # 2. Chercher dans les balises <time>
        time_tags = soup.find_all('time')
        for tag in time_tags:
            text = tag.get_text(strip=True)
            # Formats: "14h30", "14:30", "2:30 PM"
            match = re.search(r'(\d{1,2})[h:](\d{2})', text)
            if match:
                time_str = f"{match.group(1).zfill(2)}:{match.group(2)}"
                logger.info(f"Extracted time from <time> tag: {time_str}")
                return time_str

        # 3. Patterns textuels
        patterns = [
            r'Départ[^\d]*(\d{1,2})[h:](\d{2})',
            r'Heure[^\d]*(\d{1,2})[h:](\d{2})',
            r'départ[^\d]*(\d{1,2})[h:](\d{2})',
            r'(\d{1,2})[h:](\d{2})\s*(?:Départ|départ)?',
        ]

        for pattern in patterns:
            match = re.search(pattern, html_content, re.IGNORECASE)
            if match:
                time_str = f"{match.group(1).zfill(2)}:{match.group(2)}"
                logger.info(f"Extracted time from pattern: {time_str}")
                return time_str

        logger.warning(f"No time found for course {course_id}")
        return None

    except Exception as e:
        logger.error(f"Error extracting time: {e}")
        return None


def fetch_course_details(course_url: str, throttle: float = 1.0) -> dict[str, Any]:
    """
    Récupère les détails d'une course (heure, partants, hippodrome).
    
    Args:
        course_url: URL complète de la course ZEturf
        throttle: Délai en secondes entre requêtes (défaut: 1s)
    
    Returns:
        Dict avec métadonnées: {url, start_time, hippodrome, partants_count, error?}
    """
    try:
        headers = {
            'User-Agent': 'HippiqueBot/2.0 (analyse-course; respect-CGU)',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9',
            'Accept-Language': 'fr-FR,fr;q=0.9',
        }

        sleep(throttle)
        logger.info(f"Fetching course details: {course_url}")

        resp = requests.get(course_url, headers=headers, timeout=15)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, 'html.parser')

        # Extraire l'heure
        course_id = course_url.split('/')[-1] if '/' in course_url else ""
        start_time = _extract_start_time(resp.text, course_id)

        # Extraire hippodrome
        hippodrome = None
        h1 = soup.find('h1')
        if h1:
            hippodrome = h1.get_text(strip=True)

        # Compter les partants (approximation)
        partants_count = len(soup.find_all('tr', class_=re.compile(r'partant|runner')))

        return {
            'url': course_url,
            'start_time': start_time,
            'hippodrome': hippodrome,
            'partants_count': partants_count if partants_count > 0 else None,
            'html_size': len(resp.text),
            'status': 'ok'
        }

    except requests.RequestException as e:
        logger.error(f"Request error for {course_url}: {e}")
        return {
            'url': course_url,
            'error': str(e),
            'status': 'error'
        }
    except Exception as e:
        logger.error(f"Unexpected error for {course_url}: {e}")
        return {
            'url': course_url,
            'error': str(e),
            'status': 'error'
        }


if __name__ == "__main__":
    # Test rapide
    test_url = "https://www.zeturf.fr/fr/course/2025-10-17/R1C1-prix-test"
    result = fetch_course_details(test_url)
    print(json.dumps(result, indent=2, ensure_ascii=False))
