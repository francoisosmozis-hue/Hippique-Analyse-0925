"""
hippique_orchestrator/scrapers/boturfers.py - Module de scraping pour Boturfers.fr.

Ce module fournit les fonctionnalités pour scraper les données des courses
depuis le site Boturfers.fr.
"""

import argparse
import json
import logging
import re
import sys
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36"
}

class BoturfersFetcher:
    """
    Classe pour scraper les données des courses depuis Boturfers.fr.
    """

    def __init__(self, race_url: str, correlation_id: str | None = None, trace_id: str | None = None):
        if not race_url:
            raise ValueError("L'URL de la course ne peut pas être vide.")
        self.race_url = race_url
        self.soup: BeautifulSoup | None = None
        self.correlation_id = correlation_id
        self.trace_id = trace_id
        self.log_extra = {"correlation_id": self.correlation_id, "trace_id": self.trace_id}

    def _fetch_html(self) -> bool:
        """Télécharge le contenu HTML de la page."""
        try:
            response = requests.get(self.race_url, headers=HTTP_HEADERS, timeout=20)
            response.raise_for_status()
            self.soup = BeautifulSoup(response.content, "lxml")
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"Erreur lors du téléchargement de {self.race_url}: {e}", extra=self.log_extra)
            return False

    def _parse_programme(self) -> list[dict[str, Any]]:
        """Analyse la page du programme pour extraire la liste de toutes les courses."""
        if not self.soup:
            return []

        races = []
        reunion_tabs = self.soup.select("div.tab-content div.tab-pane[id^='r']")
        if not reunion_tabs:
            logger.warning("Aucun onglet de réunion ('div.tab-pane[id^=r]') trouvé sur la page du programme.", extra=self.log_extra)
            return []

        for reunion_tab in reunion_tabs:
            reunion_title_tag = reunion_tab.select_one("h3.reu-title")
            reunion_id_match = re.search(r"^(R\d+)", reunion_title_tag.text.strip()) if reunion_title_tag else None
            reunion_id = reunion_id_match.group(1) if reunion_id_match else reunion_tab.get("id", "").upper()

            race_table = reunion_tab.select_one("table.table.data.prgm")
            if not race_table:
                logger.warning(f"Tableau des courses ('table.table.data.prgm') introuvable pour la réunion {reunion_id}.", extra=self.log_extra)
                continue

            for row in race_table.select("tbody tr"):
                try:
                    # ... (parsing logic remains the same)
                    rc_tag = row.select_one("th.num span.rxcx")
                    if not rc_tag:
                        logger.warning("Tag RC ('th.num span.rxcx') introuvable pour une ligne de course. Ligne ignorée.", extra=self.log_extra)
                        continue
                    rc_text = rc_tag.text.strip()
                    name_tag = row.select_one("td.crs a.link")
                    if not name_tag:
                        logger.warning(f"Tag du nom de course ('td.crs a.link') introuvable pour {rc_text}. Ligne ignorée.", extra=self.log_extra)
                        continue
                    race_name = name_tag.text.strip()
                    relative_url = name_tag.get("href")
                    if not relative_url:
                        logger.warning(f"URL relative introuvable pour {rc_text}. Ligne ignorée.", extra=self.log_extra)
                        continue
                    absolute_url = urljoin(self.race_url, relative_url)
                    time_tag = row.select_one("td.hour")
                    start_time = None
                    if time_tag and time_tag.text.strip():
                        time_match = re.search(r'(\d{1,2})[h:](\d{2})', time_tag.text.strip())
                        if time_match:
                            start_time = f"{time_match.group(1).zfill(2)}:{time_match.group(2)}"
                    runners_count_tag = row.select_one("td.nb")
                    runners_count = int(runners_count_tag.text.strip()) if runners_count_tag and runners_count_tag.text.strip().isdigit() else None
                    races.append({
                        "rc": rc_text, "reunion": reunion_id, "name": race_name,
                        "url": absolute_url, "runners_count": runners_count, "start_time": start_time,
                    })
                except Exception as e:
                    logger.warning(f"Impossible d'analyser une ligne de course: {e}. Ligne ignorée.", extra=self.log_extra)
                    continue
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
                # ... (parsing logic remains the same)
                num_tag = row.select_one("th.num")
                if not num_tag or "NP" in num_tag.text.upper():
                    continue
                num_match = re.search(r'\d+', num_tag.text)
                num = num_match.group(0) if num_match else None
                if not num:
                    logger.warning("Numéro du partant introuvable dans une ligne. Ligne ignorée.", extra=self.log_extra)
                    continue
                name_tag = row.select_one("td.tl a.link")
                if not name_tag:
                    logger.warning(f"Nom du partant introuvable pour le numéro {num}. Ligne ignorée.", extra=self.log_extra)
                    continue
                name = name_tag.text.strip()
                jockey_tag = row.select_one("td.tl > div.size-s > a.link")
                jockey = jockey_tag.text.strip() if jockey_tag else None
                trainer_tag = row.select_one("td.tl > a.link.lg")
                trainer = trainer_tag.text.strip() if trainer_tag else None
                runners.append({"num": num, "nom": name, "jockey": jockey, "entraineur": trainer})
            except Exception as e:
                logger.warning(f"Impossible d'analyser une ligne de partant: {e}. Ligne ignorée.", extra=self.log_extra)
        return runners

    def get_snapshot(self) -> dict[str, Any]:
        """Orchestre le scraping du programme et retourne la liste des courses."""
        if not self._fetch_html():
            return {"error": "Failed to fetch HTML"}
        races = self._parse_programme()
        if not races:
            logger.error(f"Aucune course n'a pu être extraite de {self.race_url}.", extra=self.log_extra)
        return {"source": "boturfers", "type": "programme", "url": self.race_url, "scraped_at": datetime.utcnow().isoformat(), "races": races}

    def get_race_snapshot(self) -> dict[str, Any]:
        """Orchestre le scraping d'une course et retourne les partants."""
        if not self._fetch_html():
            return {"error": "Failed to fetch HTML"}
        runners = self._parse_race_runners()
        if not runners:
            logger.error(f"Aucun partant n'a pu être extrait de {self.race_url}.", extra=self.log_extra)
        return {"source": "boturfers", "type": "race_details", "url": self.race_url, "scraped_at": datetime.utcnow().isoformat(), "runners": runners}


def fetch_boturfers_programme(url: str, correlation_id: str | None = None, trace_id: str | None = None, *args, **kwargs) -> dict:
    """Fonction principale pour scraper le programme des courses sur Boturfers."""
    log_extra = {"correlation_id": correlation_id, "trace_id": trace_id, "url": url}
    logger.info("Début du scraping du programme Boturfers.", extra=log_extra)
    if not url:
        logger.error("Aucune URL fournie pour le scraping Boturfers.", extra=log_extra)
        return {}
    try:
        fetcher = BoturfersFetcher(race_url=url, correlation_id=correlation_id, trace_id=trace_id)
        raw_snapshot = fetcher.get_snapshot()
        if "error" in raw_snapshot or not raw_snapshot.get("races"):
            logger.error("Le scraping du programme a échoué ou n'a retourné aucune course.", extra=log_extra)
            return {}
        logger.info(f"Scraping du programme Boturfers réussi. {len(raw_snapshot.get('races',[]))} courses trouvées.", extra=log_extra)
        return raw_snapshot
    except Exception as e:
        logger.exception(f"Une erreur inattendue est survenue lors du scraping de {url}: {e}", extra=log_extra)
        return {}


def fetch_boturfers_race_details(url: str, correlation_id: str | None = None, trace_id: str | None = None, *args, **kwargs) -> dict:
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
        raw_snapshot = fetcher.get_race_snapshot()
        if "error" in raw_snapshot or not raw_snapshot.get("runners"):
            logger.error("Le scraping des détails a échoué.", extra=log_extra)
            return {}
        logger.info(f"Scraping des détails réussi. {len(raw_snapshot.get('runners',[]))} partants trouvés.", extra=log_extra)
        return raw_snapshot
    except Exception as e:
        logger.exception(f"Une erreur inattendue est survenue lors du scraping des détails de {url}: {e}", extra=log_extra)
        return {}

# main() function is removed as it's not used by the orchestrator
# and was for command-line testing which is now obsolete with the new structure.