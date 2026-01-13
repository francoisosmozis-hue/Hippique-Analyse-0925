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

HTTP_HEADERS = {"User-Agent": "Hippique-Analyse/1.0 (contact: ops@hippique.local)"}


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
        date: str | None = None,
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

        # Race Name (from <h1> tag)
        h1_tag = soup.find("h1", class_="my-3")
        if h1_tag:
            metadata["race_name"] = h1_tag.get_text(strip=True)

        # Date (from URL)
        date_match = re.search(r'courses/(\d{4}-\d{2}-\d{2})', race_url)
        if date_match:
            metadata["date"] = date_match.group(1)

        # RC Label from URL
        rc_match = re.search(r"/(R\d+C\d+)(?:-|$)", race_url)
        if rc_match:
            metadata["rc_label"] = rc_match.group(1)

        # Basic Info Block (e.g., Discipline, Distance, Prize, Start Time)
        info_block = soup.find("div", class_="card-body text-center mb-3")
        if info_block:
            metadata_text = info_block.get_text(strip=True).replace("\n", " ")

            # Discipline
            discipline_match = re.search(r"(Trot|Plat|Obstacle|Steeple|Haies|Cross|Attelé|Monté)", metadata_text, re.IGNORECASE)
            if discipline_match:
                metadata["discipline"] = discipline_match.group(1)

            # Distance
            distance_match = re.search(r"(\d{3,4})\s*mètres", metadata_text)
            if distance_match:
                metadata["distance"] = int(distance_match.group(1))

            # Prize
            prize_match = re.search(r"(\d{1,3}(?:\s?\d{3})*)\s*euros", metadata_text, re.IGNORECASE)
            if prize_match:
                metadata["prize"] = int(prize_match.group(1).replace(" ", ""))

            # Course Type (e.g. Attelé, Monté, Plat, Obstacle) and Corde (e.g. à gauche, à droite)
            conditions_tag = info_block.find("p", class_="card-text")
            if conditions_tag:
                conditions_text = conditions_tag.get_text(strip=True)
                type_match = re.search(r"(Attelé|Monté|Plat|Obstacle)", conditions_text, re.IGNORECASE)
                if type_match:
                    metadata["course_type"] = type_match.group(1)

                corde_match = re.search(r"corde (à gauche|à droite)", conditions_text, re.IGNORECASE)
                if corde_match:
                    metadata["corde"] = "Gauche" if "gauche" in corde_match.group(1) else "Droite"

            # Start Time
            time_match = re.search(r'(\d{1,2}h\d{2})', metadata_text)
            if time_match:
                metadata["start_time"] = time_match.group(1)

        return metadata

    def _parse_race_runners_from_details_page(self, soup: BeautifulSoup) -> list[RunnerData]: # Changed return type
        runners_data: list[RunnerData] = []
        partants_div = soup.find("div", id="partants")
        if not partants_div:
            logger.warning("Could not find 'div' with id 'partants' on the page.")
            return []

        runners_table = partants_div.find("table", class_="table")
        if not runners_table:
            logger.warning("Could not find 'table' with class 'table' within 'div#partants' on the page.")
            return []

        for row in runners_table.select("tbody tr"):
            try:
                cols = row.find_all("td")
                if len(cols) < 7:
                    logger.warning(f"Ligne de partant incomplète: {row.get_text()}. Skipping.", extra={"row_html": str(row)})
                    continue

                num_text = cols[0].get_text(strip=True)
                num = int(num_text) if num_text.isdigit() else None
                if num is None:
                    continue

                name_link = cols[1].find("a")
                name = name_link.get_text(strip=True) if name_link else ""

                jockey = cols[2].find("a").get_text(strip=True) if cols[2].find("a") else None
                trainer = cols[3].find("a").get_text(strip=True) if cols[3].find("a") else None
                musique = cols[4].get_text(strip=True)

                gains_text = cols[5].get_text(strip=True).replace(" ", "").replace("\xa0", "")
                gains = float(gains_text) if gains_text.replace('.', '', 1).isdigit() else None

                cote_span = cols[6].find("span", class_="cote")
                cote_text = cote_span.get_text(strip=True).replace(",", ".") if cote_span else None
                odds_win = float(cote_text) if cote_text and cote_text.replace('.', '', 1).isdigit() else None

                runners_data.append(
                    RunnerData(
                        num=num,
                        name=name,
                        musique=musique,
                        odds_win=odds_win,
                        odds_place=None, # Boturfers does not provide place odds directly in snapshot
                        driver=jockey,
                        trainer=trainer,
                        gains=str(gains) if gains is not None else None,
                        stats=RunnerStats(), # Initialize empty stats
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
