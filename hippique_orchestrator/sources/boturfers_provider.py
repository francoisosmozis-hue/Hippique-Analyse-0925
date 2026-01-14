from __future__ import annotations

import re
from datetime import date
from datetime import time as dt_time
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from hippique_orchestrator.data_contract import (
    RaceData,
    RaceSnapshotNormalized,
    RunnerData,
    RunnerStats,
)
from hippique_orchestrator.logging_utils import get_logger
from hippique_orchestrator.sources_interfaces import SourceProvider

logger = get_logger(__name__)

HTTP_HEADERS = {"User-Agent": "Mozilla/5.0"}


class BoturfersProvider(SourceProvider):
    """
    Provides racing data from Boturfers (programme and race snapshots).
    """

    name = "Boturfers"

    def __init__(self):
        self._http_client = httpx.AsyncClient(headers=HTTP_HEADERS, timeout=20)

    async def _fetch_html(self, url: str) -> str | None:
        try:
            response = await self._http_client.get(url)
            response.raise_for_status()
            return response.text
        except httpx.HTTPStatusError as e:
            logger.error(
                f"Erreur HTTP lors du téléchargement de {url}: {e.response.status_code}",
                extra={"url": url, "status_code": e.response.status_code},
            )
            return None
        except httpx.RequestError as e:
            logger.error(
                f"Erreur inattendue lors du fetch HTML de {url}: {e}",
                extra={"url": url, "error": str(e)},
            )
            return None

    async def fetch_programme(
        self,
        url: str,
        correlation_id: str | None = None,
        trace_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if not url:
            logger.error("Aucune URL fournie pour le scraping Boturfers.", extra={"correlation_id": correlation_id})
            return []

        logger.info("Début du scraping du programme Boturfers.", extra={"url": url, "correlation_id": correlation_id})
        html_content = await self._fetch_html(url)
        if not html_content:
            logger.error("Le scraping du programme a échoué ou n'a retourné aucune course.", extra={"correlation_id": correlation_id})
            return []

        soup = BeautifulSoup(html_content, "lxml")
        races_data = []

        reunion_tabs_content = soup.select("div.tab-content#reunions-content div.tab-pane")

        for tab_content in reunion_tabs_content:
            meeting_title_tag = tab_content.select_one("h3.reu-title")
            if not meeting_title_tag:
                continue
            
            meeting_full_title = meeting_title_tag.get_text(strip=True)
            meeting_match = re.match(r"(R\d+)\s*-\s*(.+)", meeting_full_title)
            if not meeting_match:
                continue
            
            reunion_r_label = meeting_match.group(1)
            reunion_name = meeting_match.group(2)

            race_table = tab_content.find("table", class_="table data prgm")
            if not race_table:
                continue

            for row in race_table.select("tbody tr"):
                race_info = {}
                try:
                    time_span = row.select_one("td.hour span.txt")
                    if time_span:
                        race_info['start_time'] = time_span.get_text(strip=True)

                    rc_span = row.select_one("th.num span.rxcx")
                    if rc_span:
                        rc_text = rc_span.get_text(strip=True)
                        rc_match = re.match(r"(R\d+)\s*(C\d+)", rc_text)
                        if rc_match:
                            race_info["r_label"] = rc_match.group(1)
                            race_info["c_label"] = rc_match.group(2)
                            race_info["rc"] = f"{race_info['r_label']}{race_info['c_label']}"
                        else:
                            rc_match_no_space = re.match(r"(R\d+)(C\d+)", rc_text)
                            if rc_match_no_space:
                                race_info["r_label"] = rc_match_no_space.group(1)
                                race_info["c_label"] = rc_match_no_space.group(2)
                                race_info["rc"] = rc_text
                            else:
                                logger.warning(f"Could not parse RC label from '{rc_text}'. Skipping.")
                                continue
                    else:
                        logger.warning(f"No RC span found in row. Skipping.")
                        continue
                    
                    name_link = row.select_one("td.crs span.name a.link")
                    if name_link:
                        race_info['name'] = name_link.get_text(strip=True)
                        race_info['url'] = urljoin("https://www.boturfers.fr", name_link.get('href'))
                    else:
                        logger.warning(f"Could not find name_link for a race. Skipping.")
                        continue

                    runners_cell = row.select_one("td.nb")
                    if runners_cell:
                        runners_text = runners_cell.get_text(strip=True)
                        if runners_text.isdigit():
                            race_info['runners_count'] = int(runners_text)
                        else:
                            race_info['runners_count'] = None
                    else:
                        race_info['runners_count'] = None

                    race_info["reunion_name"] = reunion_name

                    races_data.append(race_info)
                except Exception as e:
                    logger.error(
                        f"Erreur lors du parsing d'une ligne de course: {e}",
                        exc_info=True,
                        extra={"row_html": str(row), "correlation_id": correlation_id},
                    )

        return races_data

    async def fetch_snapshot(
        self,
        race_url: str,
        *,
        phase: str = "H30",
        date_str: str | None = None,
        correlation_id: str | None = None,
        trace_id: str | None = None,
    ) -> RaceSnapshotNormalized:
        logger.info(
            "Début du scraping des détails de course Boturfers.", # Changed log message
            extra={"url": race_url, "phase": phase, "correlation_id": correlation_id},
        )
        html_content = await self._fetch_html(race_url)
        if not html_content:
            logger.error("Le scraping des détails Boturfers a échoué.", extra={"url": race_url}) # Changed log message
            # Return an empty or minimal snapshot to allow fallback
            return RaceSnapshotNormalized(
                race=RaceData(date=date.today(), rc_label="UNKNOWN_RC"),
                runners=[],
                source_snapshot="Boturfers_Failed",
            )

        soup = BeautifulSoup(html_content, "html.parser")

        # Extract general race metadata
        metadata = self._parse_race_metadata(soup, race_url)
        if not metadata:
            logger.warning(f"Aucune métadonnée de course n'a pu être extraite de {race_url}.")

        race_date = date.fromisoformat(metadata.get("date")) if metadata.get("date") else date.today()
        rc_label = metadata.get("rc_label") or self._extract_rc_label_from_url(race_url) or "UNKNOWN_RC"

        start_time_str = metadata.get("start_time")
        start_time_local = None
        if start_time_str:
            time_match = re.search(r'(\d{1,2})h(\d{2})', start_time_str)
            if time_match:
                hour, minute = int(time_match.group(1)), int(time_match.group(2))
                start_time_local = dt_time(hour, minute)

        race_data = RaceData(
            date=race_date,
            rc_label=rc_label,
            discipline=metadata.get("discipline"),
            distance=metadata.get("distance"),
            corde=metadata.get("corde"),
            type_course=metadata.get("course_type"),
            prize=str(metadata.get("prize")) if metadata.get("prize") else None,
            start_time_local=start_time_local,
        )

        # Extract runners and their odds
        runners_data = self._parse_race_runners_from_details_page(soup)

        return RaceSnapshotNormalized(
            race=race_data,
            runners=runners_data,
            source_snapshot="Boturfers",
        )

    def _extract_rc_label_from_url(self, url: str) -> str | None:
        """Extracts R1C1-like label from Boturfers URL."""
        match = re.search(r"/(R\d+C\d+)(?:-|$)", url, re.IGNORECASE)
        if match:
            return match.group(1)
        return None

    def _parse_race_metadata(self, soup: BeautifulSoup, race_url: str) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        
        # Main info block
        info_block = soup.select_one("div.dot-separated")
        if info_block:
            metadata_text = info_block.get_text(" | ", strip=True)
            parts = [p.strip() for p in metadata_text.split('|')]
            
            discipline_match = re.search(r"(Attelé|Monté|Plat|Obstacle|Haies|Steeple-Chase|Cross)", metadata_text, re.IGNORECASE)
            if discipline_match:
                discipline = discipline_match.group(1)
                if discipline.lower() in ["attelé", "monté"]:
                    metadata["discipline"] = f"Trot {discipline.capitalize()}"
                else:
                    metadata["discipline"] = discipline.capitalize()
                metadata["course_type"] = metadata["discipline"]
            if len(parts) > 1 and "m" in parts[1]:
                metadata["distance"] = int(re.search(r"(\d+)", parts[1]).group(1))
            if len(parts) > 2 and "partants" in parts[2]:
                metadata["partants"] = int(re.search(r"(\d+)", parts[2]).group(1))
            if len(parts) > 5 and "Corde" in parts[5]:
                metadata["corde"] = "G" if "gauche" in parts[5] else "D"
        
        # Prize money
        if info_block and (prize_match := re.search(r"([\d\s]+)€", info_block.get_text())):
             metadata["prize"] = prize_match.group(1).replace('\xa0', '').replace(' ', '')


        # Date and RC Label from URL
        date_match = re.search(r'/(\d{4}-\d{2}-\d{2})/', race_url)
        if date_match:
            metadata["date"] = date_match.group(1)
        
        rc_match = re.search(r"/(R\d+C\d+)", race_url)
        if rc_match:
            metadata["rc_label"] = rc_match.group(1)

        # Start Time
        dep_tag = soup.select_one("div.dep")
        if dep_tag and (time_match := re.search(r'(\d{1,2}h\d{2})', dep_tag.text)):
            metadata["start_time"] = time_match.group(1)

        return metadata

    def _parse_race_runners_from_details_page(self, soup: BeautifulSoup) -> list[RunnerData]:
        runners_data: list[RunnerData] = []
        partants_table = soup.select_one("div#partants table.data")
        if not partants_table:
            logger.warning("Could not find runners table ('div#partants table.data') on the page.")
            return []

        for row in partants_table.select("tbody tr"):
            try:
                num_th = row.find("th", class_="num")
                if not num_th:
                    continue
                
                num = int(num_th.get_text(strip=True))

                cols = row.find_all("td")
                if len(cols) < 3:
                    continue

                name_cell = cols[0]
                name = name_cell.find("a", class_="link").get_text(strip=True)
                musique_raw = name_cell.get_text(" ", strip=True).replace(name, "").strip()

                jockey_trainer_cell = cols[2]
                driver = jockey_trainer_cell.find("a", href=lambda h: h and "/jockey/" in h).get_text(strip=True)
                trainer = jockey_trainer_cell.find("a", href=lambda h: h and "/entraineur/" in h).get_text(strip=True)

                runners_data.append(
                    RunnerData(
                        num=num,
                        nom=name,
                        musique=musique_raw,
                        driver=driver,
                        trainer=trainer,
                    )
                )
            except Exception as e:
                logger.warning(
                    f"Failed to parse a runner row: {e}. Row skipped.",
                    exc_info=True,
                    extra={"row_html": str(row)},
                )
        return runners_data

    async def fetch_stats_for_runner(
        self,
        runner_name: str,
        discipline: str,
        runner_data: dict[str, Any],
        correlation_id: str | None = None,
        trace_id: str | None = None,
    ) -> RunnerStats: # Changed return type
        """
        BoturfersProvider does not provide detailed runner statistics directly.
        This method is a placeholder and will return an empty RunnerStats object.
        Stats fetching will be handled by specific stats providers.
        """
        logger.info(
            "BoturfersProvider does not implement direct runner stats fetching. Returning empty stats.",
            extra={"runner_name": runner_name, "discipline": discipline, "correlation_id": correlation_id},
        )
        return RunnerStats() # Returns an empty RunnerStats object
