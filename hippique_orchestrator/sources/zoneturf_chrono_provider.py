from __future__ import annotations

import asyncio
import re
import unicodedata
from datetime import datetime, timedelta
from typing import Any

import requests
from bs4 import BeautifulSoup

from hippique_orchestrator.data_contract import RunnerStats
from hippique_orchestrator.logging_utils import get_logger
from hippique_orchestrator.sources_interfaces import SourceProvider

logger = get_logger(__name__)

BASE_URL = "https://www.zone-turf.fr"

# In-memory mock for a persistent cache. In a real-world scenario,
# this would be replaced with Firestore, Redis, or another persistent storage.
_PERSISTENT_CACHE: dict[str, Any] = {}
CACHE_TTL_SECONDS = 3600  # 1 hour


class ZoneTurfChronoProvider(SourceProvider):
    """
    Provides horse chrono statistics from zone-turf.fr.
    Implements StatsFetcher for chrono stats.
    """

    name = "ZoneTurfChrono"

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "Mozilla/5.0"})

    async def fetch_programme(
        self,
        url: str,
        correlation_id: str | None = None,
        trace_id: str | None = None,
    ) -> list[dict[str, Any]]:
        logger.info(
            "ZoneTurfChronoProvider does not implement programme fetching. Returning empty list.",
            extra={"url": url, "correlation_id": correlation_id},
        )
        return []

    async def fetch_snapshot(
        self,
        race_url: str,
        *,
        phase: str = "H30",
        date: str | None = None,
        correlation_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        logger.info(
            "ZoneTurfChronoProvider does not implement snapshot fetching. Returning empty dict.",
            extra={"url": race_url, "correlation_id": correlation_id},
        )
        return {}

    async def fetch_stats_for_runner(
        self,
        runner_name: str,
        discipline: str,
        runner_data: dict[str, Any],
        correlation_id: str | None = None,
        trace_id: str | None = None,
    ) -> RunnerStats:
        """
        Fetches chrono stats for a given horse (runner_name).
        Discipline is not used for chrono stats from Zone-Turf.
        """
        normalized_name = self._normalize_name(runner_name)
        if not normalized_name:
            return RunnerStats()

        cache_key = f"chrono_{normalized_name}"
        cached_data = self._get_from_cache(cache_key)
        if cached_data:
            return RunnerStats(
                record_rk=cached_data.get("record_attele"),
                last_3_chrono=cached_data.get("last_3_chrono", []),
                source_stats=self.name,
            )

        horse_id = await self._resolve_horse_id(runner_name)
        if not horse_id:
            logger.warning(f"Could not get Zone-Turf ID for horse: {runner_name}", extra={"correlation_id": correlation_id})
            return RunnerStats()

        url = f"{BASE_URL}/cheval/{normalized_name.replace(' ', '-')}-{horse_id}/"
        try:
            response = await asyncio.to_thread(self._session.get, url, timeout=15)
            response.raise_for_status()
            stats_dict = self._fetch_chrono_from_html(response.text, runner_name)
            if stats_dict:
                self._set_to_cache(cache_key, stats_dict)
                return RunnerStats(
                    record_rk=stats_dict.get("record_attele"),
                    last_3_chrono=stats_dict.get("last_3_chrono", []),
                    source_stats=self.name,
                )
            return RunnerStats()
        except requests.exceptions.RequestException as e:
            logger.warning(f"Failed to fetch Zone-Turf page for {runner_name} due to network error: {e}", extra={"correlation_id": correlation_id, "url": url})
            return RunnerStats()
        except Exception as e:
            logger.error(f"An unexpected error occurred while fetching chrono stats for {runner_name}: {e}", exc_info=True, extra={"correlation_id": correlation_id})
            return RunnerStats()

    def _normalize_name(self, s: str) -> str:
        """Normalizes a horse name for comparison."""
        if not s:
            return ""
        s = re.sub(r"(.*?)", "", s)
        s = s.replace("'", "")
        s = s.replace("-", " ")
        s = unicodedata.normalize("NFKD", s)
        s = "".join(c for c in s if not unicodedata.combining(c))
        return " ".join(s.lower().strip().split())

    def _parse_rk_string(self, rk_string: str) -> float | None:
        """Parses a reduction kilometer string like "1'11"6" into seconds."""
        if not isinstance(rk_string, str) or not rk_string.strip():
            return None
        match = re.match(r"(\d+)'(\d{2})[',\"]+(\d+)", rk_string.strip())
        if not match:
            return None
        try:
            minutes, seconds, tenths = map(int, match.groups())
            return minutes * 60 + seconds + tenths / 10.0
        except (ValueError, TypeError):
            return None

    async def _resolve_horse_id(self, horse_name: str, max_pages: int = 20) -> str | None:
        normalized_name = self._normalize_name(horse_name)
        if not normalized_name:
            return None

        cache_key = f"horse_id_{normalized_name}"
        cached_id = self._get_from_cache(cache_key)
        if cached_id:
            return cached_id

        first_letter = next((c for c in normalized_name if c.isalpha()), None)
        if not first_letter:
            self._set_to_cache(cache_key, None)
            return None

        for page_num in range(1, max_pages + 1):
            url = f"{BASE_URL}/cheval/lettre-{first_letter}.html?p={page_num}"
            try:
                response = await asyncio.to_thread(self._session.get, url, timeout=15)
                if response.status_code != 200:
                    logger.warning(f"Received non-200 status code {response.status_code} for URL: {url}")
                    break

                soup = BeautifulSoup(response.text, "html.parser")
                for a_tag in soup.find_all("a", href=True):
                    tag_text = self._normalize_name(a_tag.get_text(" ", strip=True))
                    if tag_text == normalized_name and "/cheval/" in a_tag["href"]:
                        match = re.search(r"-(\d+)/?$", a_tag["href"])
                        if match:
                            found_id = match.group(1)
                            logger.info(f"Resolved '{horse_name}' to ID: {found_id}")
                            self._set_to_cache(cache_key, found_id)
                            return found_id
            except requests.exceptions.RequestException as e:
                logger.warning(f"Failed to fetch page {url}: {e}")
                break
        self._set_to_cache(cache_key, None)
        return None

    def _fetch_chrono_from_html(self, html_content: str, horse_name: str) -> dict[str, Any] | None:
        """
        Parses the HTML of a horse's page to extract chrono information.
        """
        if not html_content:
            return None

        soup = BeautifulSoup(html_content, "html.parser")
        result: dict[str, Any] = {"last_3_chrono": []}
        normalized_horse_name = self._normalize_name(horse_name)

        info_card_header = soup.find("div", class_="card-header", string=re.compile(r"\s*Informations générales\s*"))
        if info_card_header:
            info_card_body = info_card_header.find_next_sibling("div", class_="card-body")
            if info_card_body:
                record_tag = None
                for p_tag in info_card_body.find_all("p"):
                    if p_tag.strong and "Record Attelé" in p_tag.strong.get_text():
                        record_tag = p_tag
                        break

                if record_tag and record_tag.strong:
                    record_text = record_tag.strong.next_sibling
                    if record_text:
                        result["record_attele"] = self._parse_rk_string(record_text.strip())

        performance_card_header = soup.find("div", class_="card-header", string=re.compile(r"\s*Performances détaillées\s*"))
        if performance_card_header:
            performance_card_body = performance_card_header.find_next_sibling("div", class_="card-body")
            if performance_card_body:
                performance_list = performance_card_body.find("ul", class_="list-group")
                if performance_list:
                    for li in performance_list.find_all("li", class_="list-group-item"):
                        if "Attelé" in li.get_text():
                            table = li.find("table")
                            if table:
                                headers = [th.get_text(strip=True) for th in table.find("thead").find_all("th")]
                                try:
                                    red_km_idx = headers.index("Red.Km")
                                except ValueError:
                                    logger.debug("Red.Km column not found in table headers. Skipping this table.")
                                    continue

                                for row in table.find("tbody").find_all("tr"):
                                    cells = row.find_all("td")
                                    if len(cells) > 1:
                                        name_in_row = self._normalize_name(cells[1].get_text(strip=True))
                                        if name_in_row == normalized_horse_name:
                                            if len(cells) > red_km_idx:
                                                chrono_str = cells[red_km_idx].get_text(strip=True)
                                                chrono = self._parse_rk_string(chrono_str)
                                                if chrono is not None:
                                                    result["last_3_chrono"].append(chrono)
                                            if len(result["last_3_chrono"]) >= 3:
                                                break

                        if len(result["last_3_chrono"]) >= 3:
                            break

        result["last_3_chrono"] = result["last_3_chrono"][:3]
        return result

    def _get_from_cache(self, key: str) -> Any | None:
        """Retrieves data from the mock persistent cache if not expired."""
        if key in _PERSISTENT_CACHE:
            data, timestamp = _PERSISTENT_CACHE[key]
            if datetime.now() - timestamp < timedelta(seconds=CACHE_TTL_SECONDS):
                return data
            else:
                del _PERSISTENT_CACHE[key] # Expire cache
        return None

    def _set_to_cache(self, key: str, value: Any):
        """Saves data to the mock persistent cache with a timestamp."""
        _PERSISTENT_CACHE[key] = (value, datetime.now())
