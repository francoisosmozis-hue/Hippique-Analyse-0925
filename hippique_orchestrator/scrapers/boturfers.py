"""
hippique_orchestrator/scrapers/boturfers.py - Module de scraping pour Boturfers.fr.

Ce module fournit les fonctionnalités pour scraper les données des courses
depuis le site Boturfers.fr.
"""

import logging
import re
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36"
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
        except httpx.RequestError as e:
            logger.error(
                f"Erreur HTTP lors du téléchargement de {self.race_url}: {e}", extra=self.log_extra
            )
            return False
        except Exception as e:
            logger.exception(
                f"Erreur inattendue lors du fetch HTML de {self.race_url}: {e}",
                extra=self.log_extra,
            )
            return False

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
            reunion_title_tag = reunion_tab.select_one("h3.reu-title")
            reunion_id_match = (
                re.search(r"^(R\d+)", reunion_title_tag.text.strip()) if reunion_title_tag else None
            )
            reunion_id = (
                reunion_id_match.group(1) if reunion_id_match else reunion_tab.get("id", "").upper()
            )

            race_table = reunion_tab.select_one("table.table.data.prgm")
            if not race_table:
                logger.warning(
                    f"Tableau des courses ('table.table.data.prgm') introuvable pour la réunion {reunion_id}.",
                    extra=self.log_extra,
                )
                continue

            for row in race_table.select("tbody tr"):
                try:
                    rc_tag = row.select_one("th.num span.rxcx")
                    if not rc_tag:
                        continue
                    rc_text = rc_tag.text.strip()
                    name_tag = row.select_one("td.crs a.link")
                    if not name_tag:
                        continue
                    race_name = name_tag.text.strip()
                    relative_url = name_tag.get("href")
                    if not relative_url:
                        continue
                    absolute_url = urljoin(self.race_url, relative_url)
                    time_tag = row.select_one("td.hour")
                    start_time = None
                    if time_tag and time_tag.text.strip():
                        time_match = re.search(r'(\d{1,2})[h:](\d{2})', time_tag.text.strip())
                        if time_match:
                            start_time = f"{time_match.group(1).zfill(2)}:{time_match.group(2)}"
                    runners_count_tag = row.select_one("td.nb")
                    runners_count = (
                        int(runners_count_tag.text.strip())
                        if runners_count_tag and runners_count_tag.text.strip().isdigit()
                        else None
                    )
                    races.append(
                        {
                            "rc": rc_text,
                            "reunion": reunion_id,
                            "name": race_name,
                            "url": absolute_url,
                            "runners_count": runners_count,
                            "start_time": start_time,
                        }
                    )
                except Exception as e:
                    logger.warning(
                        f"Impossible d'analyser une ligne de course: {e}. Ligne ignorée.",
                        extra=self.log_extra,
                    )
        return races

    def _parse_race_runners(self) -> list[dict[str, Any]]:
        """Analyse la page d'une course pour extraire les données des partants."""
        if not self.soup:
            return []
        runners = []
        runners_table = self.soup.select_one("table.data")
        if not runners_table:
            logger.error("Tableau des partants ('table.data') introuvable.", extra=self.log_extra)
            return []
        for row in runners_table.select("tbody tr"):
            try:
                num_tag = row.select_one("th.num")
                if not num_tag or "NP" in num_tag.text.upper():
                    continue
                num_match = re.search(r'\d+', num_tag.text)
                num = num_match.group(0) if num_match else None
                if not num:
                    continue
                name_tag = row.select_one("td.tl a.link")
                if not name_tag:
                    continue
                name = name_tag.text.strip()
                jockey_tag = row.select_one("td.tl > div.size-s > a.link")
                jockey = jockey_tag.text.strip() if jockey_tag else None
                trainer_tag = row.select_one("td.tl > a.link.lg")
                trainer = trainer_tag.text.strip() if trainer_tag else None
                odds_win_tag = row.select_one("td.cote-gagnant span.c")
                odds_win = float(odds_win_tag.text.strip().replace(',', '.')) if odds_win_tag and odds_win_tag.text.strip() else None
                odds_place_tag = row.select_one("td.cote-place span.c")
                odds_place = float(odds_place_tag.text.strip().replace(',', '.')) if odds_place_tag and odds_place_tag.text.strip() else None
                musique_tag = row.select_one("td.musique")
                musique = musique_tag.text.strip() if musique_tag else None
                gains_tag = row.select_one("td.gains")
                gains_text = gains_tag.text.strip().replace(' ', '') if gains_tag else None
                gains = float(gains_text) if gains_text and gains_text.replace('.', '', 1).isdigit() else None
                runners.append({
                    "num": num, "nom": name, "jockey": jockey, "entraineur": trainer,
                    "odds_win": odds_win, "odds_place": odds_place, "musique": musique,
                    "gains": gains, "dai": False, "volatility": "NEUTRE",
                    "chronos": None, "indicators_track_corde_distance": None,
                })
            except Exception as e:
                logger.warning(
                    f"Impossible d'analyser une ligne de partant: {e}. Ligne ignorée.",
                    extra=self.log_extra,
                )
        return runners

    def _parse_race_metadata(self) -> dict[str, Any]:
        """Analyse la page d'une course pour extraire ses métadonnées."""
        if not self.soup: return {}
        metadata = {}
        race_info_block = self.soup.select_one("div.info-race")
        if race_info_block:
            text_content = race_info_block.get_text(" ", strip=True)
            distance_match = re.search(r'(\d{3,4})\s*m', text_content, re.IGNORECASE)
            if distance_match: metadata['distance'] = int(distance_match.group(1))
            if "attelé" in text_content.lower(): metadata['type_course'] = "Attelé"
            elif "monté" in text_content.lower(): metadata['type_course'] = "Monté"
            elif "plat" in text_content.lower(): metadata['type_course'] = "Plat"
            elif "obstacle" in text_content.lower(): metadata['type_course'] = "Obstacle"
            if "corde à gauche" in text_content.lower(): metadata['corde'] = "Gauche"
            elif "corde à droite" in text_content.lower(): metadata['corde'] = "Droite"
            else: metadata['corde'] = "N/A"
            conditions_tag = self.soup.select_one("div.conditions-course")
            if conditions_tag: metadata['conditions'] = conditions_tag.get_text(" ", strip=True)
            elif race_info_block:
                snippet_start = text_content.find("Conditions")
                if snippet_start != -1:
                    metadata['conditions'] = text_content[snippet_start:].split('\n')[0].strip()
        if 'distance' not in metadata:
            distance_tag = self.soup.select_one("span.distance")
            if distance_tag:
                distance_match = re.search(r'(\d{3,4})\s*m', distance_tag.text, re.IGNORECASE)
                if distance_match: metadata['distance'] = int(distance_match.group(1))
        if not metadata:
            logger.warning(f"Aucune métadonnée de course n'a pu être extraite de {self.race_url}.", extra=self.log_extra)
        return metadata

    async def get_snapshot(self) -> dict[str, Any]:
        """Orchestre le scraping du programme et retourne la liste des courses."""
        if not await self._fetch_html():
            return {"error": "Failed to fetch HTML"}
        races = self._parse_programme()
        if not races:
            logger.error(f"Aucune course n'a pu être extraite de {self.race_url}.", extra=self.log_extra)
        return {
            "source": "boturfers", "type": "programme", "url": self.race_url,
            "scraped_at": datetime.utcnow().isoformat(), "races": races,
        }

    async def get_race_snapshot(self) -> dict[str, Any]:
        """Orchestre le scraping d'une course et retourne les partants."""
        if not await self._fetch_html():
            return {"error": "Failed to fetch HTML"}
        race_metadata = self._parse_race_metadata()
        runners = self._parse_race_runners()
        if not runners:
            logger.error(f"Aucun partant n'a pu être extrait de {self.race_url}.", extra=self.log_extra)
        return {
            "source": "boturfers", "type": "race_details", "url": self.race_url,
            "scraped_at": datetime.utcnow().isoformat(),
            "race_metadata": race_metadata, "runners": runners,
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
            logger.error("Le scraping du programme a échoué ou n'a retourné aucune course.", extra=log_extra)
            return {}
        logger.info(f"Scraping du programme Boturfers réussi. {len(raw_snapshot.get('races', []))} courses trouvées.", extra=log_extra)
        return raw_snapshot
    except Exception as e:
        logger.exception(f"Une erreur inattendue est survenue lors du scraping de {url}: {e}", extra=log_extra)
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
    if not url.endswith('/partant'):
        url = url.rstrip('/') + '/partant'
    try:
        fetcher = BoturfersFetcher(race_url=url, correlation_id=correlation_id, trace_id=trace_id)
        raw_snapshot = await fetcher.get_race_snapshot()
        if "error" in raw_snapshot or not raw_snapshot.get("runners"):
            logger.error("Le scraping des détails a échoué.", extra=log_extra)
            return {}
        logger.info(f"Scraping des détails réussi. {len(raw_snapshot.get('runners', []))} partants trouvés.", extra=log_extra)
        return raw_snapshot
    except Exception as e:
        logger.exception(f"Une erreur inattendue est survenue lors du scraping des détails de {url}: {e}", extra=log_extra)
        return {}
