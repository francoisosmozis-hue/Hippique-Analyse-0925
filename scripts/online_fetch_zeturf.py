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
from typing import Optional, Dict, Any
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
                
                # Petit délai pour éviter de surcharger le serveur
                time.sleep(0.5)
                
                logger.info(f"✓ Succès pour {url}")
                return response
                
            except Timeout as e:
                last_exception = e
                logger.warning(f"Timeout sur tentative {attempt + 1}: {e}")
                
            except ConnectionError as e:
                last_exception = e
                logger.warning(f"Erreur de connexion sur tentative {attempt + 1}: {e}")
                
            except RequestException as e:
                last_exception = e
                logger.warning(f"Erreur HTTP sur tentative {attempt + 1}: {e}")
            
            # Attendre avant de réessayer (backoff exponentiel)
            if attempt < self.max_retries - 1:
                wait_time = self.delay * (2 ** attempt)
                logger.info(f"Attente de {wait_time:.1f}s avant nouvelle tentative...")
                time.sleep(wait_time)
        
        # Toutes les tentatives ont échoué
        error_msg = f"Échec après {self.max_retries} tentatives pour {url}: {last_exception}"
        logger.error(error_msg)
        raise ZeturfFetchError(error_msg)
    
    def load_sources_config(self, course_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Charge la configuration sources.yml avec substitution EN MÉMOIRE
        
        IMPORTANT: Ne modifie PAS le fichier sources.yml sur le disque
        
        Args:
            course_id: ID de la course pour substitution (optionnel)
            
        Returns:
            Configuration avec substitutions effectuées
        """
        config_path = Path('config/sources.yml')
        
        if not config_path.exists():
            raise ZeturfFetchError(f"Fichier de configuration introuvable: {config_path}")
        
        # Charger le fichier
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        # Substitution EN MÉMOIRE seulement (pas de modification du fichier!)
        if course_id and 'zeturf' in config:
            original_url = config['zeturf'].get('url', '')
            config['zeturf']['url'] = original_url.replace('{course_id}', str(course_id))
            logger.debug(f"Substitution: {original_url} -> {config['zeturf']['url']}")
        
        return config
    
    def fetch_race_snapshot(
        self,
        course_id: Optional[str] = None,
        reunion_url: Optional[str] = None,
        mode: str = 'h30'
    ) -> Dict[str, Any]:
        """
        Récupère un snapshot de course depuis ZEturf
        
        Args:
            course_id: ID numérique de la course
            reunion_url: URL de la réunion complète
            mode: Mode de collecte ('h30', 'h5', 'planning')
            
        Returns:
            Données de snapshot au format dict
        """
        # Déterminer l'URL à utiliser
        if reunion_url:
            url = reunion_url
            logger.info(f"Mode réunion: {url}")
        elif course_id:
            config = self.load_sources_config(course_id)
            url = config.get('zeturf', {}).get('url', '')
            if not url:
                raise ZeturfFetchError("URL ZEturf introuvable dans la config")
            logger.info(f"Mode course ID: {url}")
        else:
            raise ZeturfFetchError("Vous devez fournir soit course_id soit reunion_url")
        
        # Vérifier le cache si activé
        if self.use_cache:
            cache_data = self._check_cache(url, mode)
            if cache_data:
                logger.info("✓ Données récupérées depuis le cache")
                return cache_data
        
        # Fetch depuis ZEturf
        try:
            response = self.fetch_with_retry(url)
            
            # Parser selon le content-type
            content_type = response.headers.get('Content-Type', '')
            
            if 'application/json' in content_type:
                data = response.json()
            else:
                # HTML - parser avec BeautifulSoup
                data = self._parse_html(response.text, url)
            
            # Enrichir avec métadonnées
            snapshot = self._build_snapshot(data, mode, url)
            
            return snapshot
            
        except Exception as e:
            logger.error(f"Erreur lors du fetch: {e}")
            raise ZeturfFetchError(f"Impossible de récupérer les données: {e}")
    
    def _parse_html(self, html: str, url: str) -> Dict[str, Any]:
        """Parse HTML ZEturf pour extraire les données de course"""
        soup = BeautifulSoup(html, 'lxml')
        
        data = {
            'runners': [],
            'partants': [],
            'market': {},
            'phase': 'open',
            'meta': {}
        }
        
        # Extraire l'heure de départ
        start_time = self._extract_start_time(soup)
        if start_time:
            data['meta']['start_time'] = start_time
            data['start_time'] = start_time
        
        # Extraire les partants et cotes
        # (Logique spécifique à implémenter selon structure HTML ZEturf)
        runners_data = soup.find_all(class_='runner-item')  # À adapter
        
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
