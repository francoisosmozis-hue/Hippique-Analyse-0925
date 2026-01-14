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
        if html_content:
            with open("/home/francoisosmozis/hippique-orchestrator/debug_boturfers_content.log", "w") as f:
                f.write(html_content)
        if not html_content:
            logger.error("Le scraping du programme a échoué ou n'a retourné aucune course.", extra={"correlation_id": correlation_id})
            return []

        soup = BeautifulSoup(html_content, "html.parser")
        races_data = []

        reunion_tabs = soup.select("div.tab-pane[id^=r]")

        for tab in reunion_tabs:
            reunion_id = tab.get("id")
            reunion_label_element = tab.find_previous_sibling("a", {"data-bs-target": f"#{reunion_id}"})
            if reunion_label_element:
                reunion_name = reunion_label_element.get_text(strip=True)
            else:
                reunion_name = f"Réunion {reunion_id.upper()}"

            race_table = tab.find("table", class_="table")
            if not race_table:
                continue

            # Corrected regex for date in title to avoid double escaping
            date_match = re.search(r'(\d{2}/\d{2}/\d{4})', soup.title.string if soup.title else '')
            race_date = date_match.group(1) if date_match else "N/A"

            for row in race_table.select("tbody tr"):
                race_info = {}
                try:
                    # Get all cells, including th
                    cols = row.find_all(['td', 'th'])
                    if len(cols) < 4:
                        continue

                    # RC Label
                    rc_span = cols[1].find('span', class_='rxcx')
                    if rc_span:
                        rc_text = rc_span.get_text(strip=True)
                        race_info["rc"] = rc_text
                        if ' ' in rc_text:
                            race_info["r_label"], race_info["c_label"] = rc_text.split(' ')
                        else: # fallback for R1C1 format
                            match = re.match(r"(R\d+)(C\d+)", rc_text)
                            if match:
                                race_info["r_label"], race_info["c_label"] = match.groups()


                    # Time
                    time_span = cols[0].find('span', class_='txt')
                    if time_span:
                        race_info['start_time'] = time_span.get_text(strip=True)

                    # Name and URL
                    name_link = cols[2].find('a', class_='link')
                    if name_link:
                        race_info['name'] = name_link.get_text(strip=True)
                        race_info['url'] = urljoin("https://www.boturfers.fr", name_link.get('href'))

                    # Runners count
                    runners_cell = cols[3]
                    runners_text = runners_cell.get_text(strip=True)
                    if runners_text.isdigit():
                        race_info['runners_count'] = int(runners_text)
                    else:
                        race_info['runners_count'] = None


                    race_info["reunion_name"] = reunion_name
                    race_info["date"] = race_date

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
        info_block = soup.select_one("div.col-md-6 p.text-center")
        if info_block:
            metadata_text = info_block.get_text(strip=True).replace("\n", " ")
            
            # Discipline et Type
            discipline_match = re.search(r"(Trot Attelé|Trot Monté|Plat|Obstacle|Haies|Steeple-Chase|Cross)", metadata_text, re.IGNORECASE)
            if discipline_match:
                metadata["discipline"] = discipline_match.group(1)
                metadata["course_type"] = discipline_match.group(1)

            # Distance
            distance_match = re.search(r"(\d{3,4})\s*m", metadata_text)
            if distance_match:
                metadata["distance"] = int(distance_match.group(1))

            # Prize
            prize_match = re.search(r"([\d\s]+)€", metadata_text)
            if prize_match:
                metadata["prize"] = prize_match.group(1).replace(" ", "")

            # Corde
            corde_match = re.search(r"Corde à (gauche|droite)", metadata_text, re.IGNORECASE)
            if corde_match:
                metadata["corde"] = "G" if "gauche" in corde_match.group(1).lower() else "D"

        # Date et RC Label depuis l'URL
        date_match = re.search(r'/(\d{4}-\d{2}-\d{2})/', race_url)
        if date_match:
            metadata["date"] = date_match.group(1)
        
        rc_match = re.search(r"/(R\d+C\d+)", race_url)
        if rc_match:
            metadata["rc_label"] = rc_match.group(1)
            
        # Heure de départ
        time_tag = soup.select_one("span.text-danger.fw-bold")
        if time_tag and (time_match := re.search(r'(\d{1,2}h\d{2})', time_tag.text)):
            metadata["start_time"] = time_match.group(1)

        return metadata

    def _parse_race_runners_from_details_page(self, soup: BeautifulSoup) -> list[RunnerData]:
        runners_data: list[RunnerData] = []
        partants_table = soup.select_one("div#partants table.table-striped")
        if not partants_table:
            logger.warning("Could not find runners table ('div#partants table.table-striped') on the page.")
            return []

        for i, row in enumerate(partants_table.select("tbody tr"), 1):
            try:
                cols = row.find_all("td")
                if len(cols) < 4:
                    logger.warning(f"Ligne de partant incomplète (cols={len(cols)}): {row.get_text()}. Skipping.")
                    continue

                # Le numéro est implicite
                num = i

                name_div = cols[0].find("div", class_="runner-name")
                name = name_div.get_text(strip=True) if name_div else ""
                
                musique = cols[1].get_text(strip=True) if len(cols) > 1 else None
                driver = cols[2].get_text(strip=True) if len(cols) > 2 else None
                trainer = cols[3].get_text(strip=True) if len(cols) > 3 else None

                # Les cotes ne sont pas sur la page principale des partants de boturfers.fr
                odds_win = None
                odds_place = None

                if name:
                    runners_data.append(
                        RunnerData(
                            num=num,
                            nom=name,
                            musique=musique,
                            odds_win=odds_win,
                            odds_place=odds_place,
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
