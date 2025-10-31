
# -*- coding: utf-8 -*-
"""
online_fetch_zeturf.py - Module de scraping fonctionnel pour Zeturf.

Ce module remplace la version bouchonnée de test pour fournir des données
de course réelles scrapées depuis le site Zeturf.
"""

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException, WebDriverException

logger = logging.getLogger(__name__)

# Headers pour simuler un navigateur réel et éviter un blocage HTTP 403
HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36"
}

class ZeturfFetcher:
    """
    Classe pour scraper les données d'une course spécifique sur Zeturf.
    """

    def __init__(self, race_url: str):
        if not race_url:
            raise ValueError("L'URL de la course ne peut pas être vide.")
        self.race_url = race_url
        self.soup: Optional[BeautifulSoup] = None

    def _fetch_html(self) -> bool:
        """Télécharge le contenu HTML de la page de la course en utilisant Selenium pour gérer le JavaScript et les bannières de cookies."""
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument(f"user-agent={HTTP_HEADERS['User-Agent']}")

        driver = None
        try:
            driver = webdriver.Chrome(options=chrome_options)
            driver.get(self.race_url)

            # Étape 1: Gérer la bannière de cookies
            try:
                cookie_button_id = "CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll"
                cookie_wait = WebDriverWait(driver, 10) # Attendre 10s max pour la bannière
                accept_button = cookie_wait.until(
                    EC.element_to_be_clickable((By.ID, cookie_button_id))
                )
                accept_button.click()
                logger.info("Bannière de cookies acceptée.")
            except TimeoutException:
                logger.warning("La bannière de cookies n'est pas apparue ou n'a pas été trouvée en 10s. Continuation...")
            except Exception as e:
                logger.warning(f"Impossible de cliquer sur le bouton des cookies: {e}. Continuation...")

            # Étape 2: Attendre que la table des partants soit chargée
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.partants-table-wrapper"))
            )

            self.soup = BeautifulSoup(driver.page_source, "lxml")
            return True
        except TimeoutException:
            logger.error(f"Timeout en attendant le conteneur des partants sur {self.race_url}")
            if driver:
                with open("debug_timeout_page.html", "w", encoding="utf-8") as f:
                    f.write(driver.page_source)
                logger.error("Le code source de la page au moment du timeout a été sauvegardé dans debug_timeout_page.html")
            return False
        except WebDriverException as e:
            logger.error(f"Erreur WebDriver: {e}. Assurez-vous que chromedriver est installé et dans le PATH.")
            return False
        except Exception as e:
            logger.error(f"Une erreur inattendue est survenue avec Selenium pour {self.race_url}: {e}")
            return False
        finally:
            if driver:
                driver.quit()

    def _parse_race_metadata(self) -> Dict[str, Any]:
        """Analyse les métadonnées de la course (discipline, heure, etc.)."""
        if not self.soup:
            return {}

        metadata = {}
        try:
            header = self.soup.select_one("div.course-infos-header")
            if header:
                title_text = header.get_text(separator=" ", strip=True)
                rc_match = re.search(r"(R\d+C\d+)", title_text)
                if rc_match:
                    metadata["rc"] = rc_match.group(1)
                
                hippo_tag = header.select_one("span.hippodrome")
                if hippo_tag:
                    metadata["hippodrome"] = hippo_tag.text.replace("-", "").strip()

            discipline_tag = self.soup.select_one("p.race-type")
            if discipline_tag:
                 metadata["discipline"] = discipline_tag.text.strip()

        except Exception as e:
            logger.warning(f"Impossible d'extraire les métadonnées: {e}")

        if "rc" not in metadata:
            rc_match = re.search(r"/(R\d+C\d+)-", self.race_url)
            if rc_match:
                metadata["rc"] = rc_match.group(1)

        return metadata

    def _parse_runners_and_odds(self) -> List[Dict[str, Any]]:
        """Analyse la table des partants et le JSON embarqué pour les cotes."""
        if not self.soup:
            return []

        odds_map = {}
        try:
            scripts = self.soup.find_all("script")
            for script in scripts:
                if script.string and "Course.init" in script.string:
                    content = script.string
                    json_match = re.search(r"Course\.init\((\{.*?\})\);", content, re.DOTALL)
                    if json_match:
                        course_data = json.loads(json_match.group(1))
                        cotes_infos = course_data.get("cotesInfos", {})
                        for num, data in cotes_infos.items():
                            if isinstance(data, dict) and data.get("odds"):
                                odds_map[num] = data["odds"].get("reference")
                        break
        except Exception as e:
            logger.warning(f"Impossible d'extraire les cotes du JSON embarqué: {e}")

        runners = []
        # Stratégie finale : trouver la première table qui contient des partants
        runners_table = None
        for table in self.soup.find_all("table"):
            if table.select_one("tr[data-runner]"):
                runners_table = table
                break

        if not runners_table:
            logger.warning("Aucune table avec des partants ('tr[data-runner]') n'a été trouvée.")
            return []

        for row in runners_table.select("tbody tr[data-runner]"):
            try:
                num_tag = row.select_one("td.numero span.partant")
                num = num_tag.text.strip() if num_tag else None

                nom_tag = row.select_one("td.cheval a.horse-name")
                nom = nom_tag.text.strip() if nom_tag else None

                if not num or not nom:
                    continue
                
                runners.append({
                    "num": num,
                    "nom": nom,
                    "cote": odds_map.get(num),
                })
            except Exception as e:
                logger.warning(f"Impossible d'analyser une ligne de partant: {e}. Ligne ignorée.")
                continue
        
        return runners

    def get_snapshot(self) -> Dict[str, Any]:
        """Orchestre le scraping et retourne un snapshot complet de la course."""
        if not self._fetch_html():
            return {"error": "Failed to fetch HTML"}

        metadata = self._parse_race_metadata()
        runners = self._parse_runners_and_odds()

        if not runners:
            logger.error(f"Aucun partant n'a pu être extrait de {self.race_url}.")

        return {
            "source": "zeturf",
            "url": self.race_url,
            "scraped_at": datetime.utcnow().isoformat(),
            **metadata,
            "runners": runners,
        }

def normalize_snapshot(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalise le snapshot brut scrapé en un format standardisé attendu
    par le reste de l'application.
    """
    if not payload or not payload.get("runners"):
        return {}

    runners = payload.get("runners", [])
    
    # Création des mappings id -> nom et id -> cote
    id2name = {str(r["num"]): r["nom"] for r in runners if "num" in r and "nom" in r}
    odds = {str(r["num"]): r["cote"] for r in runners if "num" in r and "cote" in r and r["cote"] is not None}

    return {
        "rc": payload.get("rc"),
        "hippodrome": payload.get("hippodrome"),
        "discipline": payload.get("discipline"),
        "date": payload.get("date", datetime.utcnow().strftime('%Y-%m-%d')),
        "runners": runners,
        "id2name": id2name,
        "odds": odds,
    }

def fetch_race_snapshot(reunion: str, course: str, phase: str, url: str | None = None, *_, **kwargs) -> dict:
    """
    Fonction principale qui remplace le mock.
    Prend une URL de course Zeturf et retourne un snapshot de données normalisé.
    """
    logger.info(f"Début du scraping Zeturf pour {reunion}{course} (Phase: {phase}) sur l'URL: {url}")
    
    if not url:
        logger.error("Aucune URL fournie pour le scraping Zeturf.")
        # Retourne une structure vide pour ne pas faire planter la chaîne
        return normalize_snapshot({})

    try:
        fetcher = ZeturfFetcher(race_url=url)
        raw_snapshot = fetcher.get_snapshot()
        
        if "error" in raw_snapshot or not raw_snapshot.get("runners"):
            logger.error(f"Le scraping a échoué ou n'a retourné aucun partant pour {url}.")
            return normalize_snapshot({})

        # Ajout des informations manquantes si possible
        raw_snapshot.setdefault("rc", f"{reunion}{course}")
        raw_snapshot.setdefault("phase", phase)

        normalized_data = normalize_snapshot(raw_snapshot)
        logger.info(f"Scraping réussi pour {reunion}{course}. {len(normalized_data.get('runners',[]))} partants trouvés.")
        
        return normalized_data

    except Exception as e:
        logger.exception(f"Une erreur inattendue est survenue lors du scraping de {url}: {e}")
        return normalize_snapshot({})

# --- Fonctions utilitaires potentiellement importées ailleurs ---

def write_snapshot_from_geny(*args: Any, **kwargs: Any) -> None:
    """
    Placeholder pour une fonction qui pourrait être utilisée pour un autre scraper (Geny).
    Actuellement non implémentée.
    """
    logger.warning("La fonction 'write_snapshot_from_geny' n'est pas implémentée.")
    pass

