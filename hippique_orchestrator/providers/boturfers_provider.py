# hippique_orchestrator/providers/boturfers_provider.py
from datetime import datetime
from typing import List, Dict, Any
import httpx
from bs4 import BeautifulSoup
import re

from hippique_orchestrator.contracts.models import Race
from hippique_orchestrator.providers.base_provider import BaseProgrammeProvider, BaseSnapshotProvider
from hippique_orchestrator.logging_utils import get_logger

logger = get_logger(__name__)

class BoturfersProvider(BaseProgrammeProvider, BaseSnapshotProvider):
    """Live implementation for Boturfers."""

    def __init__(self, base_url: str, timeout_seconds: int = 30):
        super().__init__()
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds

    @property
    def name(self) -> str:
        return "Boturfers-Live"

    def get_programme(self, target_date: str) -> List[Dict[str, Any]]:
        programme_url = f"{self.base_url}/programme-pmu-du-jour"
        races_data = []
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.get(programme_url)
                response.raise_for_status()

            logger.info(f"Fetched Boturfers programme for {target_date}. URL: {programme_url}, Status: {response.status_code}")

            soup = BeautifulSoup(response.text, 'lxml')
            
            # The correct selector for race links based on current Boturfers HTML.
            race_rows = soup.select('table.table-programme tbody tr')

            logger.info(f"Found {len(race_rows)} race rows on Boturfers programme page.")

            for row in race_rows:
                # Extract URL and race name
                link_element = row.select_one('td.crs div.details a.link')
                if not link_element:
                    logger.warning("Race link element not found in row, skipping.")
                    continue
                
                url = link_element['href']
                if not url.startswith('http'):
                    url = f"{self.base_url}{url}"
                
                race_name = link_element.get_text(strip=True)

                # Extract R/C string (e.g., "R1C6")
                rc_element = row.select_one('th.num span.rxcx')
                if not rc_element:
                    # Fallback to URL parsing if direct element not found
                    match = re.search(r'(R\d+C\d+)', url, re.IGNORECASE)
                    if not match:
                        logger.warning(f"Could not extract R/C from URL or element for: {url}")
                        continue
                    rc_str = match.group(1).upper()
                else:
                    rc_str = rc_element.get_text(strip=True).replace(' ', '')
                
                # Parse reunion_id and race_id
                match_rc = re.search(r'R(\d+)C(\d+)', rc_str)
                if not match_rc:
                    logger.warning(f"Could not parse reunion_id and race_id from: {rc_str}")
                    continue
                reunion_id = int(match_rc.group(1))
                race_id = int(match_rc.group(2)) # Note: model expects race_number: int, not race_id: str

                # Extract scheduled_time_local (Unix timestamp)
                hour_element = row.select_one('td.hour')
                scheduled_timestamp = None
                if hour_element and 'data-timestamp' in hour_element.attrs:
                    try:
                        scheduled_timestamp = int(hour_element['data-timestamp'])
                        scheduled_time_local = datetime.fromtimestamp(scheduled_timestamp)
                    except (ValueError, TypeError):
                        logger.warning(f"Could not parse scheduled_time_local from timestamp: {hour_element['data-timestamp']}")
                        scheduled_time_local = None
                else:
                    logger.warning("Scheduled time element or timestamp not found.")
                    scheduled_time_local = None

                # Extract discipline and distance_m
                carac_element = row.select_one('span.carac')
                discipline = None
                distance_m = None
                if carac_element:
                    carac_text = carac_element.get_text(strip=True)
                    discipline_match = re.search(r'^(Plate|Trot Attelé|Haies|Steeple-chase)', carac_text, re.IGNORECASE) # Adjust as needed for specific disciplines
                    if discipline_match:
                        discipline = discipline_match.group(0)

                    distance_match = re.search(r'(\d+)\s?m', carac_text)
                    if distance_match:
                        try:
                            distance_m = int(distance_match.group(1))
                        except ValueError:
                            pass
                # Collect race data
                if all([
                    url, race_name, reunion_id, race_id, scheduled_time_local, discipline, distance_m
                ]):
                    races_data.append({
                        "url": url,
                        "name": race_name,
                        "reunion_id": reunion_id,
                        "race_id": race_id,
                        "scheduled_time_local": scheduled_time_local.isoformat() if scheduled_time_local else None,
                        "discipline": discipline,
                        "distance_m": distance_m,
                        "source": self.name,
                    })
                else:
                    logger.warning(
                        f"Skipping race due to missing data: URL={url}, Name={race_name}, Reunion={reunion_id}, "
                        f"Race={race_id}, Time={scheduled_time_local}, Discipline={discipline}, Distance={distance_m}"
                    )
            return races_data

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching programme for {target_date}: {e}")
            return []
        except httpx.RequestError as e:
            logger.error(f"Request error fetching programme for {target_date}: {e}")
            return []
        except Exception as e:
            logger.error(f"An unexpected error occurred: {e}", exc_info=True)
            return []
