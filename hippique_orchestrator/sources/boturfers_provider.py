from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from hippique_orchestrator.sources_interfaces import SourceProvider
from hippique_orchestrator.logging_utils import get_logger

logger = get_logger(__name__)

HTTP_HEADERS = {"User-Agent": "Hippique-Analyse/1.0 (contact: ops@hippique.local)"}


class BoturfersProvider(SourceProvider):
    """
    Provides racing data from Boturfers (programme and race snapshots).
    """

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
            
            date_match = re.search(r'(\d{2}/\\d{2}/\\d{4})', soup.title.string if soup.title else '')
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
    ) -> dict[str, Any]:
        logger.info(
            "Début du scraping des détails de course.",
            extra={"url": race_url, "phase": phase, "correlation_id": correlation_id},
        )
        html_content = await self._fetch_html(race_url)
        if not html_content:
            logger.error("Le scraping des détails a échoué.", extra={"url": race_url})
            return {}

        soup = BeautifulSoup(html_content, "html.parser")
        snapshot = self._parse_race_details_page(soup, race_url)
        if snapshot and snapshot.get("runners"):
            logger.info(
                f"Scraping des détails réussi. {len(snapshot['runners'])} partants trouvés.",
                extra={"url": race_url, "num_runners": len(snapshot['runners'])},
            )
        else:
            logger.warning(
                "Scraping des détails terminé, mais aucun partant trouvé.",
                extra={"url": race_url},
            )
        return snapshot

    def _parse_race_details_page(self, soup: BeautifulSoup, race_url: str) -> dict[str, Any]:
        # Extract general race metadata
        metadata = self._parse_race_metadata(soup, race_url)
        if not metadata:
            logger.warning(f"Aucune métadonnée de course n'a pu être extraite de {race_url}.")

        # Extract runners and their odds
        runners_data = self._parse_race_runners_from_details_page(soup)

        return {**metadata, "runners": runners_data, "source": "Boturfers", "ts_fetch": datetime.now().isoformat()}

    def _parse_race_metadata(self, soup: BeautifulSoup, race_url: str) -> dict[str, Any]:
        metadata: dict[str, Any] = {}

        # Race Name (from <h1> tag)
        h1_tag = soup.find("h1", class_="my-3")
        if h1_tag:
            metadata["race_name"] = h1_tag.get_text(strip=True)
            logger.debug(f"Found h1_tag content: {metadata['race_name']}")
        else:
            logger.debug("h1_tag with class 'my-3' not found.")

        # Race RC (from breadcrumbs or URL)
        rc_match = re.search(r"/(R\d+C\d+)-", race_url)
        if rc_match:
            metadata["rc_label"] = rc_match.group(1)
            metadata["r_label"] = rc_match.group(1).split('C')[0]
            metadata["c_label"] = rc_match.group(1).split('C')[1]
        
        # Date (from URL)
        date_match = re.search(r'courses/(\d{4}-\d{2}-\d{2})', race_url)
        if date_match:
            metadata["date"] = date_match.group(1)

        # Basic Info Block (e.g., Discipline, Distance, Prize)
        info_block = soup.find("div", class_="card-body text-center mb-3")
        if info_block:
            metadata_text = info_block.get_text(strip=True).replace("\n", " ")
            
            # Discipline
            discipline_match = re.search(r"(Trot|Plat|Obstacle|Steeple|Haies|Cross)", metadata_text, re.IGNORECASE)
            if discipline_match:
                metadata["discipline"] = discipline_match.group(1)
            
            # Distance
            distance_match = re.search(r"(\d{3,4})\s*mètres", metadata_text)
            if distance_match:
                metadata["distance"] = int(distance_match.group(1))

            # Prize
            prize_match = re.search(r"(\d{1,3}(?:\s?\d{3})*)\s*euros", metadata_text, re.IGNORECASE)
            if prize_match:
                # Remove spaces and convert to int
                metadata["prize"] = int(prize_match.group(1).replace(" ", ""))

            # Course Type (e.g. Attelé, Monté, Plat, Obstacle) and Corde (e.g. à gauche, à droite)
            conditions_tag = info_block.find("p", class_="card-text") # Look for more specific tags if available
            if conditions_tag:
                conditions_text = conditions_tag.get_text(strip=True)
                # Try to extract type
                type_match = re.search(r"(Attelé|Monté|Plat|Obstacle)", conditions_text, re.IGNORECASE)
                if type_match:
                    metadata["course_type"] = type_match.group(1)

                # Try to extract corde
                corde_match = re.search(r"corde (à gauche|à droite)", conditions_text, re.IGNORECASE)
                if corde_match:
                    metadata["corde"] = "Gauche" if "gauche" in corde_match.group(1) else "Droite"
                else:
                    metadata["corde"] = "N/A" # Default if not found
            else:
                metadata["corde"] = "N/A"


        return metadata

    def _parse_race_runners_from_details_page(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        runners_data = []
        partants_div = soup.find("div", id="partants")
        if not partants_div:
            logger.warning("Could not find 'div' with id 'partants' on the page.")
            return []
        
        runners_table = partants_div.find("table", class_="table")
        if not runners_table:
            logger.warning("Could not find 'table' with class 'table' within 'div#partants' on the page.")
            return []

        for row in runners_table.select("tbody tr"):
            runner_info: dict[str, Any] = {}
            try:
                cols = row.find_all("td")
                if len(cols) < 7:
                    logger.warning(f"Ligne de partant incomplète: {row.get_text()}. Skipping.", extra={"row_html": str(row)})
                    continue

                # Numéro du cheval (cols[0] est directement le numéro maintenant)
                num_text = cols[0].get_text(strip=True)
                runner_info["num"] = int(num_text) if num_text.isdigit() else None

                # Nom du cheval et URL (cols[1])
                name_link = cols[1].find("a")
                runner_info["name"] = name_link.get_text(strip=True) if name_link else ""
                runner_info["horse_url"] = urljoin(self._http_client.base_url, name_link['href']) if name_link and 'href' in name_link.attrs else ""

                # Jockey/Driver (cols[2])
                jockey_link = cols[2].find("a")
                runner_info["jockey"] = jockey_link.get_text(strip=True) if jockey_link else ""

                # Entraîneur (cols[3])
                trainer_link = cols[3].find("a")
                runner_info["trainer"] = trainer_link.get_text(strip=True) if trainer_link else ""

                # Musique (cols[4])
                musique_span = cols[4]
                runner_info["musique"] = musique_span.get_text(strip=True) if musique_span else ""

                # Gains (cols[5])
                gains_span = cols[5]
                gains_text = gains_span.get_text(strip=True).replace(" ", "").replace("\xa0", "")
                runner_info["gains"] = float(gains_text) if gains_text.replace('.', '', 1).isdigit() else None
                
                # Cote (Win Odds) (cols[6])
                cote_span = cols[6].find("span", class_="cote")
                cote_text = cote_span.get_text(strip=True).replace(",", ".") if cote_span else None
                runner_info["odds_win"] = float(cote_text) if cote_text and cote_text.replace('.', '', 1).isdigit() else None

                # Odds Place (Placeholder)
                runner_info["odds_place"] = None

                runners_data.append(runner_info)
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
    ) -> dict[str, Any]:
        """
        BoturfersProvider does not provide detailed runner statistics directly.
        This method is a placeholder and will return an empty dict.
        Stats fetching will be handled by specific stats providers.
        """
        logger.info(
            "BoturfersProvider does not implement direct runner stats fetching. Returning empty stats.",
            extra={"runner_name": runner_name, "discipline": discipline, "correlation_id": correlation_id},
        )
        return {}
