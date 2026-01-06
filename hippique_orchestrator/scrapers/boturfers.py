"""
hippique_orchestrator/scrapers/boturfers.py - Module de scraping pour Boturfers.fr.

Ce module fournit les fonctionnalités pour scraper les données des courses
depuis le site Boturfers.fr.
"""

import logging
import re
from datetime import datetime
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from hippique_orchestrator.logging_utils import correlation_id_var, get_logger

logger = get_logger(__name__)


HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/107.0.0.0 Safari/537.36"
    )
}


class BoturfersFetcher:
    """
    Classe pour scraper les données des courses depuis Boturfers.fr.
    """

    def __init__(
        self, race_url: str, correlation_id: str | None = None, trace_id: str | None = None
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

    def _parse_race_row(self, row: Any, base_url: str) -> dict[str, Any] | None:
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

            race_data = {
                "rc": rc_text,
                "name": race_name,
                "url": absolute_url,
                "runners_count": runners_count,
                "start_time": start_time,
            }
            logger.debug(f"Parsed race data in _parse_race_row: {race_data}")
            return race_data

        except Exception as e:
            logger.warning(
                f"Impossible d'analyser une ligne de course: {e}. Ligne ignorée.",
                extra=self.log_extra,
            )
            return None

    def _parse_programme(self) -> list[dict[str, Any]]:
        """Analyse la page du programme pour extraire la liste de toutes les courses."""
        if not self.soup:
            return []

        races = []
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

        metadata = {}
        distance = self._parse_distance()
        if distance:
            metadata["distance"] = distance

        race_info_block = self.soup.select_one("div.info-race")
        if race_info_block:
            text_content = race_info_block.get_text(" ", strip=True).lower()
            course_types = {
                "attelé": "Attelé",
                "monté": "Monté",
                "plat": "Plat",
                "obstacle": "Obstacle",
            }
            for key, value in course_types.items():
                if key in text_content:
                    metadata["type_course"] = value
                    break

            if "corde à gauche" in text_content:
                metadata["corde"] = "Gauche"
            elif "corde à droite" in text_content:
                metadata["corde"] = "Droite"
            else:
                metadata["corde"] = "N/A"

            conditions_tag = self.soup.select_one("div.conditions-course")
            if conditions_tag:
                metadata["conditions"] = conditions_tag.get_text(" ", strip=True)
            else:
                snippet_start = text_content.find("conditions")
                if snippet_start != -1:
                    metadata["conditions"] = text_content[snippet_start:].split("\n")[0].strip()

        if not metadata:
            logger.warning(
                "Aucune métadonnée de course n'a pu être extraite de %s.",
                self.race_url,
                extra=self.log_extra,
            )
        return metadata

    def _parse_race_runners_from_details_page(self) -> list[dict[str, Any]]:
        """Parses the runners from the race details page."""
        if not self.soup:
            return []

        runners = []
        runners_table = self.soup.select_one("table.data")
        if not runners_table:
            logger.warning(
                "Could not find runners table ('table.data') on the page.", extra=self.log_extra
            )
            return []

        for row in runners_table.select("tbody tr"):
            try:
                num = row.select_one("th.num").text.strip()
                nom = row.select_one("td.tl > a.link").text.strip()

                links = row.select("td.tl a.link")
                jockey = links[1].text.strip()
                trainer = links[2].text.strip()

                odds_win_tag = row.select_one("td.cote-gagnant span.c")
                odds_win = float(odds_win_tag.text.replace(",", ".")) if odds_win_tag else None

                odds_place_tag = row.select_one("td.cote-place span.c")
                odds_place = (
                    float(odds_place_tag.text.replace(",", ".")) if odds_place_tag else None
                )

                musique_tag = row.select_one("td.musique")
                musique = musique_tag.text.strip() if musique_tag else None

                gains_tag = row.select_one("td.gains")
                gains = gains_tag.text.strip().replace(" ", "") if gains_tag else None

                runners.append(
                    {
                        "num": num,
                        "nom": nom,
                        "jockey": jockey,
                        "entraineur": trainer,
                        "odds_win": odds_win,
                        "odds_place": odds_place,
                        "musique": musique,
                        "gains": gains,
                    }
                )
            except (AttributeError, ValueError, IndexError) as e:
                logger.warning(
                    f"Failed to parse a runner row: {e}. Row skipped.", extra=self.log_extra
                )
                continue

        return runners

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
    url: str, correlation_id: str | None = None, trace_id: str | None = None, *args, **kwargs
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
    url: str, correlation_id: str | None = None, trace_id: str | None = None, *args, **kwargs
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
