#!/usr/bin/env python3
"""
online_fetch_zeturf.py - Script corrigé pour la collecte de données ZEturf
Corrections:
- Retry logic avec backoff exponentiel
- Pas de modification du fichier sources.yml (substitution en mémoire)
- Gestion d'erreurs robuste
- Timeouts appropriés
- Logging structuré
"""

import sys
import json
import time
import yaml
import argparse
import logging
from typing import Optional, Dict, Any, Mapping
from datetime import datetime
from pathlib import Path

import requests
from requests.exceptions import RequestException, Timeout, ConnectionError
from bs4 import BeautifulSoup

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ZeturfFetchError(Exception):
    """Exception personnalisée pour les erreurs de fetch ZEturf"""
    pass


class ZeturfFetcher:
    """Classe pour gérer les requêtes ZEturf avec retry et cache"""
    
    def __init__(
        self,
        max_retries: int = 3,
        timeout: int = 10,
        delay: float = 1.0,
        use_cache: bool = False
    ):
        self.max_retries = max_retries
        self.timeout = timeout
        self.delay = delay
        self.use_cache = use_cache
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json, text/html',
            'Accept-Language': 'fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7'
        })
    
    def fetch_with_retry(self, url: str) -> requests.Response:
        """
        Effectue une requête HTTP avec retry et backoff exponentiel
        
        Args:
            url: URL à récupérer
            
        Returns:
            Response object
            
        Raises:
            ZeturfFetchError: Si toutes les tentatives échouent
        """
        last_exception = None
        
        for attempt in range(self.max_retries):
            try:
                logger.info(f"Tentative {attempt + 1}/{self.max_retries} pour {url}")
                
                response = self.session.get(
                    url,
                    timeout=self.timeout,
                    allow_redirects=True
                )
                
                # Vérifier le status code
                response.raise_for_status()
                return response
                
            except (Timeout, ConnectionError) as e:
                logger.warning(f"Erreur réseau ({e}), nouvelle tentative dans {self.delay}s...")
                last_exception = e
                time.sleep(self.delay)
                self.delay *= 2  # Backoff exponentiel
            except RequestException as e:
                logger.error(f"Erreur de requête: {e}")
                last_exception = e
                break  # Stop retrying for other client-side errors
        
        raise ZeturfFetchError(f"Toutes les tentatives ont échoué pour {url}") from last_exception

    def fetch_race_snapshot(
        self,
        course_id: Optional[str] = None,
        reunion_url: Optional[str] = None,
        mode: str = 'h30'
    ) -> Dict[str, Any]:
        """Récupère les données d'une course depuis ZEturf"""
        if self.use_cache:
            # Logique de cache à implémenter
            pass

        if reunion_url:
            # Extraire les données de la page de la réunion
            response = self.fetch_with_retry(reunion_url)
            soup = BeautifulSoup(response.content, 'lxml')
            # Extraire les données de la course
            data = self._extract_race_data(soup)
            return self._build_snapshot(data, mode, reunion_url)
        
        elif course_id:
            # Construire l'URL de l'API ZEturf
            # Cette partie est une supposition, l'URL de l'API n'est pas dans le code fourni
            url = f"https://www.zeturf.fr/rest/api/race/{course_id}"
            response = self.fetch_with_retry(url)
            data = response.json()
            return self._build_snapshot(data, mode, url)

        else:
            raise ValueError("Vous devez fournir course_id ou reunion_url")

    def _extract_race_data(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """Extrait les données de la course depuis le HTML"""
        data: Dict[str, Any] = {
            'runners': [],
            'partants': [],
            'market': {},
            'phase': 'open'
        }
        
        # Extraire l'heure de départ
        data['start_time'] = self._extract_start_time(soup)
        
        # Extraire les partants
        runners_data = soup.select('.race-runners-table .runner-row')
        for idx, runner_elem in enumerate(runners_data, 1):
            try:
                runner = {
                    'number': idx,
                    'name': self._safe_extract(runner_elem, '.runner-name'),
                    'odds': self._extract_odds(runner_elem),
                    'jockey': self._safe_extract(runner_elem, '.jockey-name'),
                    'trainer': self._safe_extract(runner_elem, '.trainer-name')
                }
                data['runners'].append(runner)
                data['partants'].append(str(idx))
            except Exception as e:
                logger.warning(f"Erreur extraction runner {idx}: {e}")
                continue
        
        return data

    def _extract_start_time(self, soup: BeautifulSoup) -> Optional[str]:
        """
        Extrait l'heure de départ depuis le HTML
        Gère plusieurs formats possibles
        """
        # Chercher dans les balises <time>
        time_elem = soup.find('time', {'datetime': True})
        if time_elem:
            dt_str = time_elem.get('datetime')
            try:
                dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
                return dt.strftime('%H:%M')
            except Exception:
                pass
        
        # Chercher dans les attributs data-*
        elem = soup.find(attrs={'data-start-time': True})
        if elem:
            return elem.get('data-start-time')
        
        # Regex sur le texte (ex: "21h05", "21 h 05", "21:05")
        import re
        text = soup.get_text()
        match = re.search(r'(\d{1,2})[h:\s]+(\d{2})', text)
        if match:
            hour, minute = match.groups()
            return f"{hour.zfill(2)}:{minute}"
        
        logger.warning("Impossible d'extraire l'heure de départ")
        return None

    def _safe_extract(self, elem, selector: str) -> str:
        """Extraction sécurisée avec sélecteur CSS"""
        try:
            found = elem.select_one(selector)
            return found.get_text(strip=True) if found else ''
        except Exception:
            return ''

    def _extract_odds(self, elem) -> float:
        """Extrait la cote d'un élément runner"""
        try:
            odds_elem = elem.select_one('.odds, .cote')
            if odds_elem:
                odds_text = odds_elem.get_text(strip=True)
                return float(odds_text.replace(',', '.'))
        except Exception:
            pass
        return 0.0

    def _build_snapshot(
        self,
        data: Dict[str, Any],
        mode: str,
        url: str
    ) -> Dict[str, Any]:
        """Construit le snapshot final avec métadonnées"""
        now = datetime.now()
        
        snapshot = {
            'meta': {
                'timestamp': now.isoformat(),
                'mode': mode,
                'source_url': url,
                'fetched_at': now.strftime('%Y-%m-%d %H:%M:%S')
            },
            'runners': data.get('runners', []),
            'partants': data.get('partants', []),
            'market': data.get('market', {}),
            'phase': data.get('phase', 'open')
        }
        
        # Ajouter start_time si disponible
        if 'start_time' in data:
            snapshot['meta']['start_time'] = data['start_time']
            snapshot['start_time'] = data['start_time']
        
        return snapshot

    def _check_cache(self, url: str, mode: str) -> Optional[Dict[str, Any]]:
        """Vérifie si des données en cache existent"""
        # Logique de cache à implémenter si nécessaire
        return None

    def save_snapshot(self, snapshot: Dict[str, Any], output_path: str):
        """Sauvegarde le snapshot dans un fichier JSON"""
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False)
        
        logger.info(f"✓ Snapshot sauvegardé: {output_file}")

def write_snapshot_from_geny(course_id: str, phase: str, rc_dir: Path, course_url: str) -> None:
    logger.info("STUB: Writing dummy snapshots for %s in %s", course_id, rc_dir)
    rc_dir.mkdir(parents=True, exist_ok=True)

    runners = [
        {"id": "1", "num": "1", "name": "DUMMY 1", "odds": 5.0},
        {"id": "2", "num": "2", "name": "DUMMY 2", "odds": 6.0},
        {"id": "3", "num": "3", "name": "DUMMY 3", "odds": 7.0},
        {"id": "4", "num": "4", "name": "DUMMY 4", "odds": 8.0},
        {"id": "5", "num": "5", "name": "DUMMY 5", "odds": 9.0},
        {"id": "6", "num": "6", "name": "DUMMY 6", "odds": 10.0},
        {"id": "7", "num": "7", "name": "DUMMY 7", "odds": 11.0},
    ]

    # Create dummy H-30 file
    h30_file = rc_dir / f"{datetime.now().strftime('%Y%m%d%H%M%S')}_H-30.json"
    with open(h30_file, "w", encoding="utf-8") as f:
        json.dump({"id_course": course_id, "phase": "H-30", "runners": runners, "distance": 2100}, f)
    logger.info("STUB: Wrote dummy H-30 file to %s", h30_file)

    # Create dummy H-5 file
    h5_file = rc_dir / f"{datetime.now().strftime('%Y%m%d%H%M%S')}_H-5.json"
    with open(h5_file, "w", encoding="utf-8") as f:
        json.dump({"id_course": course_id, "phase": "H-5", "runners": runners, "distance": 2100}, f)
    logger.info("STUB: Wrote dummy H-5 file to %s", h5_file)

def normalize_snapshot(payload: Mapping[str, Any]) -> dict[str, Any]:
    """
    Normalise un snapshot de course.
    """
    if isinstance(payload, dict):
        normalized = payload
    elif isinstance(payload, Mapping):
        try:
            normalized = dict(payload)
        except TypeError:
            return {}
    else:
        return {}
        
    runners = normalized.get("runners")
    if isinstance(runners, list) and runners:
        return normalized
        
    fallback = normalized.get("partants")
    if isinstance(fallback, list) and fallback:
        normalized["runners"] = fallback
        
    return normalized

def main():
    """Point d'entrée du script"""
    parser = argparse.ArgumentParser(
        description='Fetch ZEturf data with retry logic and error handling'
    )
    parser.add_argument(
        '--mode',
        choices=['h30', 'h5', 'planning'],
        default='h30',
        help='Mode de collecte'
    )
    parser.add_argument(
        '--course-id',
        type=str,
        help='ID numérique de la course'
    )
    parser.add_argument(
        '--reunion-url',
        type=str,
        help='URL complète de la réunion ZEturf'
    )
    parser.add_argument(
        '--out',
        type=str,
        required=True,
        help='Chemin de sortie pour le snapshot JSON'
    )
    parser.add_argument(
        '--snapshot',
        type=str,
        choices=['H-30', 'H-5'],
        help='Type de snapshot (H-30 ou H-5)'
    )
    parser.add_argument(
        '--use-cache',
        action='store_true',
        help='Utiliser le cache local si disponible'
    )
    parser.add_argument(
        '--max-retries',
        type=int,
        default=3,
        help='Nombre max de tentatives'
    )
    parser.add_argument(
        '--timeout',
        type=int,
        default=10,
        help='Timeout en secondes'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Mode verbeux'
    )
    
    args = parser.parse_args()
    
    # Configurer le niveau de log
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    
    # Validation des arguments
    if not args.course_id and not args.reunion_url:
        parser.error("Vous devez fournir --course-id ou --reunion-url")
    
    # Mapper snapshot vers mode si fourni
    mode = args.mode
    if args.snapshot:
        mode = 'h30' if args.snapshot == 'H-30' else 'h5'
    
    try:
        # Créer le fetcher
        fetcher = ZeturfFetcher(
            max_retries=args.max_retries,
            timeout=args.timeout,
            use_cache=args.use_cache
        )
        
        # Récupérer les données
        logger.info(f"Début de la collecte en mode {mode}")
        snapshot = fetcher.fetch_race_snapshot(
            course_id=args.course_id,
            reunion_url=args.reunion_url,
            mode=mode
        )
        
        # Sauvegarder
        fetcher.save_snapshot(snapshot, args.out)
        
        logger.info("✓ Collecte terminée avec succès")
        return 0
        
    except ZeturfFetchError as e:
        logger.error(f"✗ Erreur de collecte: {e}")
        return 1
        
    except Exception as e:
        logger.error(f"✗ Erreur inattendue: {e}", exc_info=True)
        return 2


if __name__ == '__main__':
    sys.exit(main())