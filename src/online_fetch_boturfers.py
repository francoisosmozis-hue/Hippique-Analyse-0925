# -*- coding: utf-8 -*-
"""
online_fetch_boturfers.py - Module de scraping pour Boturfers.fr.

Ce module fournit les fonctionnalités pour scraper les données des courses
depuis le site Boturfers.fr.
"""

import argparse
import json
import logging
import re
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36"
}

class BoturfersFetcher:
    """
    Classe pour scraper les données des courses depuis Boturfers.fr.
    """

    def __init__(self, race_url: str):
        if not race_url:
            raise ValueError("L'URL de la course ne peut pas être vide.")
        self.race_url = race_url
        self.soup: Optional[BeautifulSoup] = None

    def _fetch_html(self) -> bool:
        """Télécharge le contenu HTML de la page."""
        try:
            response = requests.get(self.race_url, headers=HTTP_HEADERS, timeout=20)
            response.raise_for_status()
            self.soup = BeautifulSoup(response.content, "lxml")
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"Erreur lors du téléchargement de {self.race_url}: {e}")
            return False

    def _parse_programme(self) -> List[Dict[str, Any]]:
        """Analyse la page du programme pour extraire la liste de toutes les courses."""
        if not self.soup:
            return []
        
        races = []
        
        # Les réunions sont dans des divs avec l'ID r1, r2, etc.
        reunion_tabs = self.soup.select("div.tab-content div.tab-pane[id^='r']")
        
        for reunion_tab in reunion_tabs:
            reunion_title_tag = reunion_tab.select_one("h3.reu-title")
            reunion_id_match = re.search(r"^(R\d+)", reunion_title_tag.text.strip()) if reunion_title_tag else None
            reunion_id = reunion_id_match.group(1) if reunion_id_match else reunion_tab.get("id", "").upper()

            race_table = reunion_tab.select_one("table.table.data.prgm")
            if not race_table:
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
                    runners_count = int(runners_count_tag.text.strip()) if runners_count_tag and runners_count_tag.text.strip().isdigit() else None

                    races.append({
                        "rc": rc_text,
                        "reunion": reunion_id,
                        "name": race_name,
                        "url": absolute_url,
                        "runners_count": runners_count,
                        "start_time": start_time,
                    })
                except Exception as e:
                    logger.warning(f"Impossible d'analyser une ligne de course: {e}. Ligne ignorée.")
                    continue
        
        return races

    def _parse_race_runners(self) -> List[Dict[str, Any]]:
        """Analyse la page d'une course pour extraire les données des partants."""
        if not self.soup:
            return []

        runners = []
        
        # Parser la table HTML des partants
        runners_table = self.soup.select_one("div#partants table.data")
        if not runners_table:
            logger.error("Tableau des partants introuvable.")
            return []

        for row in runners_table.select("tbody tr"):
            try:
                num_tag = row.select_one("th.num")
                if not num_tag or "NP" in num_tag.text.upper(): # Ignore les non-partants
                    continue
                
                # Nettoyer le numéro pour ne garder que le chiffre
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

                runners.append({
                    "num": num,
                    "nom": name,
                    "jockey": jockey,
                    "entraineur": trainer,
                })
            except Exception as e:
                logger.warning(f"Impossible d'analyser une ligne de partant: {e}. Ligne ignorée.")
        
        return runners

    def get_snapshot(self) -> Dict[str, Any]:
        """Orchestre le scraping du programme et retourne la liste des courses."""
        if not self._fetch_html():
            return {"error": "Failed to fetch HTML"}

        races = self._parse_programme()

        if not races:
            logger.error(f"Aucune course n'a pu être extraite de {self.race_url}.")

        return {
            "source": "boturfers",
            "type": "programme",
            "url": self.race_url,
            "scraped_at": datetime.utcnow().isoformat(),
            "races": races,
        }

    def get_race_snapshot(self) -> Dict[str, Any]:
        """Orchestre le scraping d'une course et retourne les partants."""
        if not self._fetch_html():
            return {"error": "Failed to fetch HTML"}

        runners = self._parse_race_runners()

        if not runners:
            logger.error(f"Aucun partant n'a pu être extrait de {self.race_url}.")

        # On pourrait aussi parser les metadonnées de la course ici
        return {
            "source": "boturfers",
            "type": "race_details",
            "url": self.race_url,
            "scraped_at": datetime.utcnow().isoformat(),
            "runners": runners,
        }

def normalize_snapshot(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalise le snapshot brut du programme. Pour l'instant, retourne les données brutes.
    """
    if not payload or (not payload.get("races") and not payload.get("runners")):
        return {}
    
    return payload

def fetch_boturfers_programme(url: str, *args, **kwargs) -> dict:
    """
    Fonction principale pour scraper le programme des courses sur Boturfers.
    """
    logger.info(f"Début du scraping du programme Boturfers pour l'URL: {url}")
    
    if not url:
        logger.error("Aucune URL fournie pour le scraping Boturfers.")
        return normalize_snapshot({})

    try:
        fetcher = BoturfersFetcher(race_url=url)
        raw_snapshot = fetcher.get_snapshot()
        
        if "error" in raw_snapshot or not raw_snapshot.get("races"):
            logger.error(f"Le scraping du programme a échoué ou n'a retourné aucune course pour {url}.")
            return normalize_snapshot({})

        normalized_data = normalize_snapshot(raw_snapshot)
        logger.info(f"Scraping du programme Boturfers réussi pour {url}. {len(normalized_data.get('races',[]))} courses trouvées.")
        
        return normalized_data

    except Exception as e:
        logger.exception(f"Une erreur inattendue est survenue lors du scraping de {url}: {e}")
        return normalize_snapshot({})

def fetch_boturfers_race_details(url: str, *args, **kwargs) -> dict:
    """
    Fonction principale pour scraper les détails d'une course sur Boturfers.
    """
    logger.info(f"Début du scraping des détails de course pour l'URL: {url}")
    
    if not url:
        logger.error("Aucune URL fournie pour le scraping des détails de course.")
        return {}

    try:
        fetcher = BoturfersFetcher(race_url=url)
        raw_snapshot = fetcher.get_race_snapshot()
        
        if "error" in raw_snapshot or not raw_snapshot.get("runners"):
            logger.error(f"Le scraping des détails a échoué pour {url}.")
            return {}

        # La normalisation pour les détails de la course pourrait être différente
        # Pour l'instant, on retourne les données brutes.
        logger.info(f"Scraping des détails réussi pour {url}. {len(raw_snapshot.get('runners',[]))} partants trouvés.")
        
        return raw_snapshot

    except Exception as e:
        logger.exception(f"Une erreur inattendue est survenue lors du scraping des détails de {url}: {e}")
        return {}

def main():
    """Point d'entrée principal pour l'exécution en ligne de commande."""
    parser = argparse.ArgumentParser(description="Scraper pour Boturfers.fr.")
    parser.add_argument("--reunion", required=True, help="ID de la réunion (ex: R1)")
    parser.add_argument("--course", required=True, help="ID de la course (ex: C1)")
    parser.add_argument("--output", required=True, help="Chemin du fichier de sortie JSON pour le snapshot.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    # 1. Scraper le programme pour trouver l'URL de la course
    programme_url = "https://www.boturfers.fr/programme-pmu-du-jour"
    programme_data = fetch_boturfers_programme(programme_url)

    race_url = None
    target_rc = f"{args.reunion}{args.course}"
    if programme_data and programme_data.get("races"):
        for race in programme_data["races"]:
            if race.get("rc", "").replace(" ", "") == target_rc.replace(" ", ""):
                race_url = race.get("url")
                break
    
    if not race_url:
        logger.error(f"Course {target_rc} introuvable sur le programme de Boturfers.")
        sys.exit(1)

    # 2. Scraper les détails de la course spécifique
    race_details = fetch_boturfers_race_details(race_url)

    if not race_details or "error" in race_details:
        logger.error(f"Échec du scraping des détails pour {race_url}")
        sys.exit(1)

    # 3. Sauvegarder le snapshot
    try:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(race_details, f, ensure_ascii=False, indent=2)
        logger.info(f"Snapshot pour {target_rc} sauvegardé dans {args.output}")
    except IOError as e:
        logger.error(f"Impossible d'écrire le fichier de sortie {args.output}: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
