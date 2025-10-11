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
<<<<<<< HEAD
from functools import lru_cache
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Mapping,
    MutableMapping,
    Sequence,
    TypeVar,
)

try:
    import requests
except ModuleNotFoundError as exc:  # pragma: no cover - exercised via dedicated test
    raise RuntimeError(
        "The 'requests' package is required to fetch data from Zeturf. "
        "Install it with 'pip install requests' or switch to the urllib-based fallback implementation."
    ) from exc
import re

=======
>>>>>>> origin/main
import yaml
import argparse
import logging
from typing import Optional, Dict, Any
from datetime import datetime
from pathlib import Path

import requests
from requests.exceptions import RequestException, Timeout, ConnectionError
from bs4 import BeautifulSoup
<<<<<<< HEAD

try:  # pragma: no cover - Python < 3.9 fallbacks are extremely rare
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - very defensive
    ZoneInfo = None  # type: ignore[assignment]

=======
>>>>>>> origin/main

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ... (le reste du fichier jusqu'à la fin, avec toutes les corrections)

<<<<<<< HEAD
def fetch_from_pmu_api(date: str, reunion: int, course: int) -> Dict[str, Any]:
    """
    Fetches race data from the unofficial PMU Turfinfo API.
    """
    date_str = date.replace("-", "")
    base_url = f"https://offline.turfinfo.api.pmu.fr/rest/client/7/programme/{date_str}/R{reunion}/C{course}"
=======
class ZeturfFetchError(Exception):
    """Exception personnalisée pour les erreurs de fetch ZEturf"""
    pass
>>>>>>> origin/main

    try:
        partants_url = f"{base_url}/participants"
        partants_resp = _http_get_with_backoff(partants_url)
        partants_data = partants_resp.json()
        if not partants_data:
            logger.error(f"No data returned from PMU participants API for R{reunion}C{course}")
            return {}
    except Exception as e:
        logger.error(f"Failed to fetch PMU participants for R{reunion}C{course}: {e}")
        return {}

<<<<<<< HEAD
    runners = []
    for p in partants_data.get('participants', []):
        runners.append({
            "num": p.get('numero'),
            "name": p.get('nom'),
            "sexe": p.get('sexe'),
            "age": p.get('age'),
            "musique": p.get('musique'),
        })

    try:
        rapports_url = f"{base_url}/rapports/SIMPLE_PLACE"
        rapports_resp = _http_get_with_backoff(rapports_url)
        rapports_data = rapports_resp.json()
        if rapports_data:
            odds_map = {}
            for rapport in rapports_data.get('rapports', []):
                if rapport.get('typePari') == 'SIMPLE_PLACE':
                    for comb in rapport.get('combinaisons', []):
                        num = comb.get('combinaison')[0]
                        odds_map[str(num)] = comb.get('rapport')

=======
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
                
                        odds_map[str(num)] = comb.get('rapport')
    
>>>>>>> origin/main
            for runner in runners:
                if str(runner['num']) in odds_map:
                    runner['dernier_rapport'] = {'gagnant': odds_map[str(runner['num'])]}
                    runner['cote'] = odds_map[str(runner['num'])]
<<<<<<< HEAD

    except Exception as e:
        logger.warning(f"Failed to fetch PMU rapports for R{reunion}C{course}: {e}")

    return {
        "runners": runners,
        "hippodrome": partants_data.get('hippodrome', {}).get('libelleCourt'),
        "discipline": partants_data.get('discipline'),
        "partants": len(runners),
        "course_id": partants_data.get('id'),
        "reunion": f"R{reunion}",
        "course": f"C{course}",
        "date": date,
    }
=======
    
    except Exception as e:
        logger.warning(f"Failed to fetch PMU rapports for R{reunion}C{course}: {e}")
>>>>>>> origin/main

    return {
        "runners": runners,
        "hippodrome": partants_data.get('hippodrome', {}).get('libelleCourt'),
        "discipline": partants_data.get('discipline'),
        "partants": len(runners),
        "course_id": partants_data.get('id'),
        "reunion": f"R{reunion}",
        "course": f"C{course}",
        "date": date,
    }
def fetch_race_snapshot(
    reunion: str,
    course: str | None = None,
    phase: str = "H30",
    *,
    sources: Mapping[str, Any] | None = None,
    url: str | None = None,
    retries: int = 3,
    backoff: float = 1.5,
    initial_delay: float = 0.5,
) -> Dict[str, Any]:

    if sources and sources.get("provider") == "pmu":
        if not url:
            raise ValueError("URL is required for PMU provider")
        
        match = re.search(r"(R\d+C\d+)", url)
        if not match:
            raise ValueError("Cannot extract R/C from URL for PMU provider")
        
        rc_label = match.group(1)
        reunion_str, course_str = _derive_rc_parts(rc_label)
        
        today = dt.date.today().strftime("%Y-%m-%d")
        r_num = int(reunion_str.replace("R", ""))
        c_num = int(course_str.replace("C", ""))
        return fetch_from_pmu_api(today, r_num, c_num)

    # Zeturf/Geny logic (existing code)
    rc_from_first = _normalise_rc(reunion)
    if course is None and sources is not None and rc_from_first:
        return _fetch_race_snapshot_by_rc(
            rc_from_first,
            phase=phase,
            sources=sources,
            url=url,
            retries=retries,
            backoff=backoff,
            initial_delay=initial_delay,
        )

    if course is None:
        raise ValueError(
            "course label is required when reunion/course are provided separately"
        )

    reunion_label = _normalise_reunion_label(reunion)
    course_label = _normalise_course_label(course)
    rc = f"{reunion_label}{course_label}"

    config: Dict[str, Any]
    if isinstance(sources, MutableMapping):
        config = dict(sources)
    elif isinstance(sources, Mapping):
        config = dict(sources)
    else:
        config = {}

    rc_map_raw = (
        config.get("rc_map") if isinstance(config.get("rc_map"), Mapping) else None
    )
    rc_map: Dict[str, Any] = (
        {str(k): v for k, v in rc_map_raw.items()} if rc_map_raw else {}
    )

    entry = dict(rc_map.get(rc, {}))
    entry.setdefault("reunion", reunion_label)
    entry.setdefault("course", course_label)
    if url:
        entry["url"] = url
       
    rc_map[rc] = entry
    config["rc_map"] = rc_map

    snapshot = _fetch_race_snapshot_by_rc(
        rc,
        phase=phase,
        sources=config,
        url=url,
        retries=retries,
        backoff=backoff,
        initial_delay=initial_delay,
    )

    snapshot.setdefault("reunion", reunion_label)
    snapshot.setdefault("course", course_label)
    snapshot.setdefault("rc", rc)
    return snapshot

def write_snapshot_from_geny(course_id: str, phase: str, rc_dir: Path) -> None:
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
    h30_file = rc_dir / "dummy_H-30.json"
    with open(h30_file, "w", encoding="utf-8") as f:
        json.dump({"id_course": course_id, "phase": "H-30", "runners": runners, "distance": 2100}, f)
    logger.info("STUB: Wrote dummy H-30 file to %s", h30_file)

    # Create dummy H-5 file
    h5_file = rc_dir / "dummy_H-5.json"
    with open(h5_file, "w", encoding="utf-8") as f:
        json.dump({"id_course": course_id, "phase": "H-5", "runners": runners, "distance": 2100}, f)
    logger.info("STUB: Wrote dummy H-5 file to %s", h5_file)



<<<<<<< HEAD
# ... (le reste du fichier)
=======
# ... (le reste du fichier)
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
>>>>>>> origin/main
