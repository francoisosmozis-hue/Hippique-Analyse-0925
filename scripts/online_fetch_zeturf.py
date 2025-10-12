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
import re
import datetime as dt
from typing import Optional, Dict, Any, Mapping, MutableMapping
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


# --- Stubs for missing functions ---
# These functions are used by fetch_race_snapshot but were not defined.
# I am creating placeholder implementations.
def _normalise_rc(label):
    logger.warning("STUB: _normalise_rc called")
    if "R" in label and "C" in label:
        return label
    return None

def _derive_rc_parts(rc_label):
    logger.warning("STUB: _derive_rc_parts called")
    match = re.search(r"R(\d+)C(\d+)", rc_label)
    if match:
        return f"R{match.group(1)}", f"C{match.group(2)}"
    return None, None

def _normalise_reunion_label(label):
    logger.warning("STUB: _normalise_reunion_label called")
    return label

def _normalise_course_label(label):
    logger.warning("STUB: _normalise_course_label called")
    return label

def _fetch_race_snapshot_by_rc(*args, **kwargs):
    logger.error("FATAL: _fetch_race_snapshot_by_rc is not implemented")
    raise NotImplementedError("_fetch_race_snapshot_by_rc is not implemented")
# --- End Stubs ---


class ZeturfFetchError(Exception):
    """Exception personnalisée pour les erreurs de fetch ZEturf"""
    pass

def fetch_from_pmu_api(date: str, reunion: int, course: int) -> Dict[str, Any]:
    """
    This function was reconstructed from the broken code block.
    Its logic is likely incomplete as it depends on external API calls.
    """
    logger.info(f"Fetching PMU data for R{reunion}C{course} on {date}")
    try:
        # This block was inside the broken file.
        # It depends on `rows`, `runners`, `partants_data` which are not defined.
        # I am defining them as empty to make the function syntactically valid.
        rows = []
        runners = []
        partants_data = {}
        
        # --- BEGIN odds_map population (fixed) ---
        odds_map: Dict[str, float] = {}
        for row in rows:
            if not row:
                continue
            runner_id = row.get("id") or row.get("runner_id")
            if not runner_id:
                continue
            raw = row.get("odds") or row.get("odd") or row.get("sp")
            try:
                odds_map[str(runner_id)] = float(str(raw).replace(",", "."))
            except (TypeError, ValueError):
                continue
        # --- END ---

        for runner in runners:
            if str(runner['num']) in odds_map:
                runner['dernier_rapport'] = {'gagnant': odds_map[str(runner['num'])]}
                runner['cote'] = odds_map[str(runner['num'])]
        
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

    except Exception as e:
        logger.warning(f"Failed to fetch PMU rapports for R{reunion}C{course}: {e}")
        return {
            "runners": [], "hippodrome": None, "discipline": None, "partants": 0,
            "course_id": None, "reunion": f"R{reunion}", "course": f"C{course}", "date": date,
        }


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
        """
        last_exception = None
        for attempt in range(self.max_retries):
            try:
                logger.info(f"Tentative {attempt + 1}/{self.max_retries} pour {url}")
                response = self.session.get(url, timeout=self.timeout, allow_redirects=True)
                response.raise_for_status()
                return response
            except (Timeout, ConnectionError, RequestException) as e:
                last_exception = e
                logger.warning(f"Erreur réseau ({e}), tentative {attempt + 1} échouée. Nouvelle tentative...")
                time.sleep(self.delay * (2 ** attempt))
        
        raise ZeturfFetchError(f"Échec final de la récupération de {url} après {self.max_retries} tentatives") from last_exception

    def fetch_race_snapshot(self, course_id: str, reunion_url: str, mode: str) -> Dict[str, Any]:
        logger.warning("STUB: ZeturfFetcher.fetch_race_snapshot is not fully implemented.")
        url = reunion_url
        if not url and course_id:
            # This is a guess, the URL structure needs to be confirmed.
            url = f"https://www.zeturf.fr/fr/course/{course_id}"

        if not url:
            raise ZeturfFetchError("URL de la réunion ou ID de course requis.")
        
        response = self.fetch_with_retry(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        data = {'runners': [], 'partants': []}
        # This selector is a guess and needs to be confirmed.
        runners_data = soup.select('.runner-item') 
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
        
        data['start_time'] = self._extract_start_time(soup)
        return self._build_snapshot(data, mode, url)

    def _extract_start_time(self, soup: BeautifulSoup) -> Optional[str]:
        """
        Extrait l'heure de départ depuis le HTML
        Gère plusieurs formats possibles
        """
        time_elem = soup.find('time', {'datetime': True})
        if time_elem:
            dt_str = time_elem.get('datetime')
            try:
                dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
                return dt.strftime('%H:%M')
            except Exception:
                pass
        
        elem = soup.find(attrs={'data-start-time': True})
        if elem:
            return elem.get('data-start-time')
        
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
        
        if 'start_time' in data:
            snapshot['meta']['start_time'] = data['start_time']
            snapshot['start_time'] = data['start_time']
        
        return snapshot
    
    def _check_cache(self, url: str, mode: str) -> Optional[Dict[str, Any]]:
        """Vérifie si des données en cache existent"""
        return None
    
    def save_snapshot(self, snapshot: Dict[str, Any], output_path: str):
        """Sauvegarde le snapshot dans un fichier JSON"""
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False)
        
        logger.info(f"✓ Snapshot sauvegardé: {output_file}")


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
    ]

    h30_file = rc_dir / "dummy_H-30.json"
    with open(h30_file, "w", encoding="utf-8") as f:
        json.dump({"id_course": course_id, "phase": "H-30", "runners": runners, "distance": 2100}, f)
    logger.info("STUB: Wrote dummy H-30 file to %s", h30_file)

    h5_file = rc_dir / "dummy_H-5.json"
    with open(h5_file, "w", encoding="utf-8") as f:
        json.dump({"id_course": course_id, "phase": "H-5", "runners": runners, "distance": 2100}, f)
    logger.info("STUB: Wrote dummy H-5 file to %s", h5_file)


# --- Wrappers de Compatibilité API ---
# Le wrapper online_fetch_zeturf.py à la racine s'attend à ce que ces fonctions existent.
# Nous les définissons ici comme des wrappers légers autour de la classe ZeturfFetcher
# pour combler le fossé entre l'ancienne API à base de fonctions et la nouvelle.

def http_get(url: str, session: Optional[requests.Session] = None, **kwargs) -> str:
    """
    Wrapper léger pour ZeturfFetcher pour maintenir la compatibilité API pour la récupération de contenu HTML.
    """
    logger.info(f"[compat-wrapper] http_get appelé pour {url}")
    fetcher = ZeturfFetcher(**kwargs)
    if session:
        fetcher.session = session
    response = fetcher.fetch_with_retry(url)
    return response.text

def parse_course_page(url: str, snapshot: str) -> Dict[str, Any]:
    """
    Wrapper pour parser une page de course, pour maintenir la compatibilité API.
    """
    logger.info(f"[compat-wrapper] parse_course_page appelé pour {url} (snapshot: {snapshot})")
    fetcher = ZeturfFetcher()
    mode = snapshot.lower().replace('-', '')
    
    response = fetcher.fetch_with_retry(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    data = {'runners': [], 'partants': []}
    # Ce sélecteur est une supposition et doit être confirmé en inspectant les pages ZEturf.
    runners_data = soup.select('.race-runner-row') 
    for idx, runner_elem in enumerate(runners_data, 1):
        try:
            runner = {
                'number': fetcher._safe_extract(runner_elem, '.runner-number'),
                'name': fetcher._safe_extract(runner_elem, '.runner-name'),
                'odds': fetcher._extract_odds(runner_elem),
                'jockey': fetcher._safe_extract(runner_elem, '.jockey-name'),
                'trainer': fetcher._safe_extract(runner_elem, '.trainer-name')
            }
            data['runners'].append(runner)
            data['partants'].append(str(idx))
        except Exception as e:
            logger.warning(f"Erreur extraction runner {idx}: {e}")
            continue
    
    data['start_time'] = fetcher._extract_start_time(soup)
    return fetcher._build_snapshot(data, mode, url)

def parse_meeting_page(url: str) -> Dict[str, Any]:
    """Stub pour la compatibilité API."""
    logger.warning(f"STUB: parse_meeting_page appelé pour {url}, mais non implémenté.")
    return {"url": url, "courses": []}

def to_pipeline_json(snapshot: Dict[str, Any]) -> str:
    """Stub pour la compatibilité API."""
    logger.warning("STUB: to_pipeline_json appelé, mais non implémenté.")
    return json.dumps(snapshot)

def normalize_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Stub pour la compatibilité API."""
    logger.warning("STUB: normalize_snapshot appelé, mais non implémenté.")
    return snapshot

# --- Fin des Wrappers de Compatibilité API ---


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
    parser.add_argument('--course-id', type=str, help='ID numérique de la course')
    parser.add_argument('--reunion-url', type=str, help='URL complète de la réunion ZEturf')
    parser.add_argument('--out', type=str, required=True, help='Chemin de sortie pour le snapshot JSON')
    parser.add_argument('--snapshot', type=str, choices=['H-30', 'H-5'], help='Type de snapshot (H-30 ou H-5)')
    parser.add_argument('--use-cache', action='store_true', help='Utiliser le cache local si disponible')
    parser.add_argument('--max-retries', type=int, default=3, help='Nombre max de tentatives')
    parser.add_argument('--timeout', type=int, default=10, help='Timeout en secondes')
    parser.add_argument('--verbose', action='store_true', help='Mode verbeux')
    
    args = parser.parse_args()
    
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    
    if not args.course_id and not args.reunion_url:
        parser.error("Vous devez fournir --course-id ou --reunion-url")
    
    mode = args.mode
    if args.snapshot:
        mode = 'h30' if args.snapshot == 'H-30' else 'h5'
    
    try:
        fetcher = ZeturfFetcher(
            max_retries=args.max_retries,
            timeout=args.timeout,
            use_cache=args.use_cache
        )
        
        # In the original file, fetch_race_snapshot was called on the fetcher instance.
        # But it's a global function. I'm assuming it should be a method.
        snapshot = fetcher.fetch_race_snapshot(
            course_id=args.course_id,
            reunion_url=args.reunion_url,
            mode=mode
        )
        
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