"""
hippique_orchestrator/scrapers/boturfers.py - Module de scraping pour Boturfers.fr.

Ce module fournit les fonctionnalités pour scraper les données des courses
despuis le site Boturfers.fr.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, TypedDict
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup  # type: ignore

from hippique_orchestrator.logging_utils import correlation_id_var, get_logger

logger = get_logger(__name__)


HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/107.0.0.0 Safari/537.36"
    )
}

class Runner(TypedDict):
    num: int
    nom: str
    jockey: str
    entraineur: str
    odds_win: float | None
    odds_place: float | None
    musique: str | None
    gains: str | None


class RaceProgramEntry(TypedDict):
    rc: str
    name: str
    url: str
    runners_count: int | None
    start_time: str | None
    reunion: str # Added reunion to the RaceProgramEntry


class BoturfersFetcher:
    """
    Classe pour scraper les données des courses depuis Boturfers.fr.
    """

    def __init__(
        self,
        race_url: str,
        correlation_id: str | None = None,
        trace_id: str | None = None,
    ):
        if not race_url:
            raise ValueError("L'URL de la course ne peut pas être vide.")
        self.race_url = race_url
        self.soup: BeautifulSoup | None = None
        self.correlation_id = correlation_id
        self.trace_id = trace_id
        self.log_extra = {"correlation_id": self.correlation_id, "trace_id": self.trace_id}

    async def _fetch_html(self) -> bool:
        """Télécharge le contenu HTML de la page de manière asynchrone."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(self.race_url, headers=HTTP_HEADERS, timeout=20)
                response.raise_for_status()
            self.soup = BeautifulSoup(response.content, "lxml")
            return True
        except httpx.HTTPStatusError as e:
            logger.error(
                f"Erreur HTTP lors du téléchargement de {self.race_url}: {e.response.status_code}",
                extra={"correlation_id": correlation_id_var.get()},
            )
            return False
        except Exception as e:
            logger.exception(
                f"Erreur inattendue lors du fetch HTML de {self.race_url}: {e}",
                extra=self.log_extra,
            )
            return False

    def _parse_race_row(self, row: Any, base_url: str) -> RaceProgramEntry | None:
        """Parses a single race row from the programme table."""
        try:
            rc_tag = row.select_one("th.num span.rxcx")
            logger.debug(f"rc_tag: {rc_tag.text.strip() if rc_tag else 'None'}")
            if not rc_tag:
                return None
            rc_text = rc_tag.text.strip()
            name_tag = row.select_one("td.crs a.link")
            logger.debug(f"name_tag: {name_tag.text.strip() if name_tag else 'None'}")
            if not name_tag:
                return None
            race_name = name_tag.text.strip()
            relative_url = name_tag.get("href")
            logger.debug(f"relative_url: {relative_url}")
            if not relative_url:
                return None
            absolute_url = urljoin(base_url, relative_url)

            time_tag = row.select_one("td.hour")
            logger.debug(f"time_tag: {time_tag.text.strip() if time_tag else 'None'}")
            start_time = None
            if time_tag and time_tag.text.strip():
                time_match = re.search(r"(\d{1,2})[h:](\d{2})", time_tag.text.strip())
                if time_match:
                    start_time = f"{time_match.group(1).zfill(2)}:{time_match.group(2)}"

            runners_count_tag = row.select_one("td.nb")
            logger.debug(f"runners_count_tag: {runners_count_tag.text.strip() if runners_count_tag else 'None'}")
            runners_count = (
                int(runners_count_tag.text.strip())
                if runners_count_tag and runners_count_tag.text.strip().isdigit()
                else None
            )

            race_data: RaceProgramEntry = {
                "rc": rc_text,
                "name": race_name,
                "url": absolute_url,
                "runners_count": runners_count,
                "start_time": start_time,
                "reunion": "N/A" # Will be filled later
            }
            logger.debug(f"Parsed race data in _parse_race_row: {race_data}")
            return race_data

        except Exception as e:
            logger.warning(
                f"Impossible d'analyser une ligne de course: {e}. Ligne ignorée.",
                extra=self.log_extra,
            )
            return None

    def _parse_programme(self) -> list[RaceProgramEntry]:
        """Analyse la page du programme pour extraire la liste de toutes les courses."""
        if not self.soup:
            return []

        races: list[RaceProgramEntry] = []
        reunion_tabs = self.soup.select("div.tab-content div.tab-pane[id^='r']")
        if not reunion_tabs:
            logger.warning(
                "Aucun onglet de réunion ('div.tab-pane[id^=r]') trouvé sur la page du programme.",
                extra=self.log_extra,
            )
            return []

        for reunion_tab in reunion_tabs:
            reunion_id = reunion_tab.get("id", "").upper()  # Directly use the tab ID

            race_table = reunion_tab.select_one("table.table.data.prgm")
            if not race_table:
                logger.warning(
                    (
                        "Tableau des courses ('table.table.data.prgm') introuvable pour la "
                        "réunion %s."
                    ),
                    reunion_id,
                    extra=self.log_extra,
                )
                continue

            for row in race_table.select("tbody tr"):
                race_data = self._parse_race_row(row, self.race_url)
                if race_data:
                    race_data["reunion"] = reunion_id
                    races.append(race_data)
        return races

    def _parse_distance(self) -> int | None:
        """Parses the race distance from the page."""
        if not self.soup:
            return None

        race_info_block = self.soup.select_one("div.info-race")
        if race_info_block:
            text_content = race_info_block.get_text(" ", strip=True).lower()
            distance_match = re.search(r"(\d{3,4})\s*m", text_content, re.IGNORECASE)
            if distance_match:
                return int(distance_match.group(1))

        distance_tag = self.soup.select_one("span.distance")
        if distance_tag:
            distance_match = re.search(r"(\d{3,4})\s*m", distance_tag.text, re.IGNORECASE)
            if distance_match:
                return int(distance_match.group(1))
        return None

    def _parse_race_metadata(self) -> dict[str, Any]:
        """Analyse la page d'une course pour extraire ses métadonnées."""
        if not self.soup:
            return {}

        metadata: dict[str, Any] = {}

        # Race Name
        h1_tag = self.soup.find("h1", class_="title")
        if h1_tag:
            race_full_name = h1_tag.get_text(strip=True)
            # For H1 tag, just get the race name. RC label comes from URL.
            # Remove leading RC label if present (e.g., "C7 Prix De La Croisette")
            race_name_match = re.match(r"^(R\d+C\d+|C\d+)\s(.+)$", race_full_name)
            if race_name_match:
                metadata["race_name"] = race_name_match.group(2)
            else:
                metadata["race_name"] = race_full_name

        # RC Label, R Label, C Label from URL
        rc_from_url_match = re.search(r"/\d+-([Rr]\d+C\d+)-", self.race_url, re.IGNORECASE) # Match numeric ID before RC label
        if rc_from_url_match:
            metadata["rc_label"] = rc_from_url_match.group(1).upper() # Store as uppercase
            metadata["r_label"] = metadata["rc_label"].split('C')[0]
            metadata["c_label"] = metadata["rc_label"].split('C')[1]

        # Date
        date_tag = self.soup.find("div", class_="dep")
        if date_tag:
            date_text = date_tag.get_text(strip=True)
            # Example: "Départ à 16h50 le 14 jan. 2026"
            date_match = re.search(r"le (\d{1,2})\s(jan|fév|mar|avr|mai|juin|juil|aoû|sep|oct|nov|déc)\.\s(\d{4})", date_text)
            if date_match:
                day = date_match.group(1)
                month_abbr = date_match.group(2)
                year = date_match.group(3)

                month_mapping = {
                    "jan": "01", "fév": "02", "mar": "03", "avr": "04", "mai": "05", "juin": "06",
                    "juil": "07", "aoû": "08", "sep": "09", "oct": "10", "nov": "11", "déc": "12"
                }
                month = month_mapping.get(month_abbr, "")
                if month:
                    metadata["date"] = f"{year}-{month}-{day.zfill(2)}"

        # Discipline, Distance, Nb Partants, Corde
        dot_separated_div = self.soup.find("div", class_="dot-separated")
        if dot_separated_div:
            # Discipline
            dot_separated_text_raw = dot_separated_div.get_text()
            discipline_match = re.search(r"(Plat|Trot|Monté|Obstacle)", dot_separated_text_raw, re.IGNORECASE)
            if discipline_match:
                # Prioritize 'Monté' as a specific type of 'Trot' if both are present in text
                if 'Monté' in dot_separated_text_raw: # Check original text to avoid case issues
                    metadata["discipline"] = "Monté"
                elif 'Trot' in dot_separated_text_raw:
                    metadata["discipline"] = "Trot"
                else:
                    metadata["discipline"] = discipline_match.group(1) # Fallback to matched group

            # Distance
            dot_separated_text_raw = dot_separated_div.get_text()
            # Remove all spaces and non-breaking spaces for a clean number match
            dot_separated_text_cleaned = re.sub(r'[\s\xa0]+', '', dot_separated_text_raw)
            distance_match = re.search(r"(\d+)m", dot_separated_text_cleaned)
            if distance_match:
                metadata["distance"] = int(distance_match.group(1))            # Nb Partants
            partants_match = re.search(r"(\d+)\s*partants", dot_separated_div.get_text())
            if partants_match:
                metadata["nb_partants"] = int(partants_match.group(1))

            # Corde
            if "Corde à gauche" in dot_separated_div.get_text():
                metadata["corde"] = "Gauche"
            elif "Corde à droite" in dot_separated_div.get_text():
                metadata["corde"] = "Droite"
            else:
                metadata["corde"] = "N/A"

        if not metadata:
            logger.warning(
                "Aucune métadonnée de course n'a pu être extraite de %s.",
                self.race_url,
                extra=self.log_extra,
            )
        return metadata

    def _parse_race_runners_from_details_page(self) -> list[Runner]:
        """Parses the runners from the race details page."""
        if not self.soup:
            return []

        runners: list[Runner] = []
        # Find the div with id="partants" and then the table within it
        partants_div = self.soup.find("div", id="partants")
        if not partants_div:
            logger.warning("Could not find 'div' with id 'partants'.", extra=self.log_extra)
            return []

        runners_table = partants_div.find("table", class_="table data")
        if not runners_table:
            logger.warning(
                "Could not find 'table' with class 'table data' within 'div#partants'.",
                extra=self.log_extra,
            )
            return []

        for row in runners_table.select("tbody tr"):
            try:
                # Num
                num_tag = row.select_one("th.num")
                num = int(num_tag.text.strip()) if num_tag else None

                # Name and Horse URL
                name_link = row.select_one("td a.link")
                nom = name_link.text.strip() if name_link else ""
                horse_url = urljoin(self.race_url, name_link["href"]) if name_link and "href" in name_link.attrs else ""

                # Jockey and Trainer
                td_jockey_trainer = row.find_all('td')[2] # Get the 3rd td element (index 2)
                jockey = ""
                trainer = ""

                # Get all 'a' tags that are direct or indirect children
                all_links_in_td = td_jockey_trainer.find_all('a')
                for link in all_links_in_td:
                    href = link.get('href', '')
                    if "/jockey/" in href:
                        jockey = link.get_text(strip=True)
                    elif "/entraineur/" in href:
                        trainer = link.get_text(strip=True)

                # Musique
                musique_td = row.find_all('td')[0] # Get the 1st td element (index 0)
                musique = ""
                div_size_m = musique_td.select_one("div.size-m")
                if div_size_m and div_size_m.next_sibling:
                    musique = str(div_size_m.next_sibling).strip()
                musique = musique.replace("p", "").replace("d", "D").strip() # Clean up 'p' for place, 'd' for disqualifié

                # Gains (This column is not directly visible in the "Partants" table, keeping as None for now)
                gains = None # Placeholder, will need to be scraped from another section if available and required

                runners.append(
                    Runner(
                        num=num,
                        nom=nom,
                        horse_url=horse_url,
                        jockey=jockey,
                        entraineur=trainer,
                        odds_win=None,  # Placeholder, will be populated from 'cotes' tab
                        odds_place=None,  # Placeholder, will be populated from 'cotes' tab
                        musique=musique,
                        gains=gains,
                    )
                )
            except (AttributeError, ValueError, IndexError) as e:
                logger.warning(
                    f"Failed to parse a runner row: {e}. Row skipped. HTML: {row}", extra=self.log_extra
                )
                continue

        return runners

    def _parse_odds_from_cotes_tab(self) -> dict[int, dict[str, float]]:
        """Parses odds from the 'Cotes' tab."""
        if not self.soup:
            return {}

        odds_data: dict[int, dict[str, float]] = {}
        cotes_tab_content = self.soup.find("div", id="cotes")
        if not cotes_tab_content:
            logger.warning("Could not find 'div' with id 'cotes'.", extra=self.log_extra)
            return odds_data

        odds_table = cotes_tab_content.find("table", class_="table data")
        if not odds_table:
            logger.warning(
                "Could not find 'table' with class 'table data' within 'div#cotes'.",
                extra=self.log_extra,
            )
            return odds_data

        for row in odds_table.select("tbody tr"):
            try:
                num_tag = row.select_one("th.num")
                runner_num = int(num_tag.text.strip()) if num_tag else None
                if runner_num is None:
                    continue

                # Odds Win - Let's take the PMU.fr odds as an example (5th td, then div.coteval for the current value)
                # This needs careful indexing. Let's re-examine the HTML
                # <th colspan="2" class="bs size-s sort" data-label="pmu"> (3rd section, so td index 4 and 5)
                # <th colspan="2" class="bs size-s sort" data-label="pmufr"> (4th section, so td index 6 and 7)
                # <th colspan="2" class="bs size-s sort" data-label="zeturf"> (5th section, so td index 8 and 9)

                # Assuming PMU.fr is desired for odds_win
                # The td containing the current odds for PMU.fr is the 7th td (index 6)
                pmufr_odds_td = row.select_one("td:nth-of-type(7)")
                odds_win = None
                if pmufr_odds_td:
                    coteval_div = pmufr_odds_td.find("div", class_="coteval")
                    if coteval_div and coteval_div.get("data-val"):
                        odds_win = float(coteval_div["data-val"])
                    else: # Fallback to direct text if no data-val (for the first cote value)
                        try:
                            odds_win = float(pmufr_odds_td.get_text(strip=True).replace(",", "."))
                        except ValueError:
                            pass


                # Odds Place - Often not directly available, but derived. For now, let's look for a specific element
                # If there's a dedicated 'place' odds, it would be in its own span/div.
                # Boturfers seems to only show Win odds on the cotes tab directly.
                # So, for now, we'll keep odds_place as None. If required, a more complex derivation or source might be needed.
                odds_place = None # Not directly available from the current "Cotes" tab structure as explicit 'place' odds

                odds_data[runner_num] = {"odds_win": odds_win, "odds_place": odds_place}

            except (AttributeError, ValueError, IndexError) as e:
                logger.warning(
                    f"Failed to parse odds row: {e}. Row skipped. HTML: {row}", extra=self.log_extra
                )
                continue
        return odds_data

    async def get_snapshot(self) -> dict[str, Any]:
        """Orchestre le scraping du programme et retourne la liste des courses."""
        if not await self._fetch_html():
            return {"error": "Failed to fetch HTML"}
        races = self._parse_programme()
        if not races:
            logger.error(
                "Aucune course n'a pu être extraite de %s.", self.race_url, extra=self.log_extra
            )
        return {
            "source": "boturfers",
            "type": "programme",
            "url": self.race_url,
            "scraped_at": datetime.utcnow().isoformat(),
            "races": races,
        }

    async def get_race_snapshot(self) -> dict[str, Any]:
        """Orchestre le scraping d'une course et retourne les partants."""
        if not await self._fetch_html():
            return {"error": "Failed to fetch HTML"}
        race_metadata = self._parse_race_metadata()
        runners = self._parse_race_runners_from_details_page()
        odds_data = self._parse_odds_from_cotes_tab()

        # Merge odds data into runners
        for runner in runners:
            if runner["num"] in odds_data:
                runner["odds_win"] = odds_data[runner["num"]]["odds_win"]
                runner["odds_place"] = odds_data[runner["num"]]["odds_place"]

        if not runners:
            logger.error(
                "Aucun partant n'a pu être extrait de %s.", self.race_url, extra=self.log_extra
            )
        return {
            "source": "boturfers",
            "type": "race_details",
            "url": self.race_url,
            "scraped_at": datetime.utcnow().isoformat(),
            "race_metadata": race_metadata,
            "runners": runners,
        }


async def fetch_boturfers_programme(
    url: str,
    correlation_id: str | None = None,
    trace_id: str | None = None,
    *args,
    **kwargs,
) -> dict:
    """Fonction principale pour scraper le programme des courses sur Boturfers."""
    log_extra = {"correlation_id": correlation_id, "trace_id": trace_id, "url": url}
    logger.info("Début du scraping du programme Boturfers.", extra=log_extra)
    if not url:
        logger.error("Aucune URL fournie pour le scraping Boturfers.", extra=log_extra)
        return {}
    try:
        fetcher = BoturfersFetcher(race_url=url, correlation_id=correlation_id, trace_id=trace_id)
        raw_snapshot = await fetcher.get_snapshot()
        if "error" in raw_snapshot or not raw_snapshot.get("races"):
            logger.error(
                "Le scraping du programme a échoué ou n'a retourné aucune course.", extra=log_extra
            )
            return {}
        logger.info(
            ("Scraping du programme Boturfers réussi. %s courses trouvées."),
            len(raw_snapshot.get("races", [])),
            extra=log_extra,
        )
        return raw_snapshot
    except Exception as e:
        logger.exception(
            "Une erreur inattendue est survenue lors du scraping de %s: %s",
            url,
            e,
            extra=log_extra,
        )
        return {}


async def fetch_boturfers_race_details(
    url: str,
    correlation_id: str | None = None,
    trace_id: str | None = None,
    *args,
    **kwargs,
) -> dict:
    """Fonction principale pour scraper les détails d'une course sur Boturfers."""
    log_extra = {"correlation_id": correlation_id, "trace_id": trace_id, "url": url}
    logger.info("Début du scraping des détails de course.", extra=log_extra)
    if not url:
        logger.error("Aucune URL fournie pour le scraping des détails de course.", extra=log_extra)
        return {}
    host = urlparse(url).netloc.lower()
    # Boturfers: endpoint /partant ; ZEturf/autres: ne pas modifier l'URL
    if 'boturfers.fr' in host:
        if not url.endswith('/partant'):
            url = url.rstrip('/') + '/partant'
    else:
        url = url.rstrip('/')
    try:
        fetcher = BoturfersFetcher(race_url=url, correlation_id=correlation_id, trace_id=trace_id)
        raw_snapshot = await fetcher.get_race_snapshot()
        if "error" in raw_snapshot or not raw_snapshot.get("runners"):
            logger.error("Le scraping des détails a échoué.", extra=log_extra)
            return {}
        logger.info(
            "Scraping des détails réussi. %s partants trouvés.",
            len(raw_snapshot.get("runners", [])),
            extra=log_extra,
        )
        return raw_snapshot
    except Exception as e:
        logger.exception(
            ("Une erreur inattendue est survenue lors du scraping des détails de %s: %s"),
            url,
            e,
            extra=log_extra,
        )
        return {}
