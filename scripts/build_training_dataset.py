
import os
import json
import pandas as pd
import numpy as np
from tqdm import tqdm
import re
import requests
from bs4 import BeautifulSoup
from typing import Any, List, MutableMapping, Sequence, Tuple

# --- Début de la logique de récupération copiée de get_arrivee_geny.py ---

GENY_BASE = "https://www.geny.com"
HDRS = {"User-Agent": "Mozilla/5.0 (compatible; build_training_dataset/1.0)"}
ARRIVE_TEXT_RE = re.compile(
    r"arriv[ée]e\s*(?:officielle|définitive)?\s*:?\s*([0-9\s\-–>]+)",
    re.IGNORECASE,
)

def _request(url: str) -> requests.Response:
    """Return an HTTP response for ``url``."""
    resp = requests.get(url, headers=HDRS, timeout=15)
    resp.raise_for_status()
    return resp

def _extract_arrival_from_text(text: str) -> list[str]:
    """Extract arrival numbers from free text snippets."""
    match = ARRIVE_TEXT_RE.search(text)
    if not match:
        return []
    return re.findall(r"\d+", match.group(1))

def parse_arrival(html: str) -> list[str]:
    """Return arrival numbers extracted from ``html``."""
    soup = BeautifulSoup(html, "html.parser")
    # Simplifié pour n'utiliser que l'extraction textuelle qui est la plus robuste
    numbers = _extract_arrival_from_text(soup.get_text(" ", strip=True))
    return numbers

def _course_candidate_urls(course_id: str) -> Sequence[str]:
    return (
        f"{GENY_BASE}/resultats-pmu/course/_c{course_id}",
        f"{GENY_BASE}/resultats-pmu/_c{course_id}",
        f"{GENY_BASE}/course-pmu/_c{course_id}",
    )

def fetch_arrival_for_course(course_id: str) -> Tuple[List[str], str | None]:
    """Return arrival numbers and optional error message."""
    if not course_id:
        return [], "missing-course-id"

    for url in _course_candidate_urls(course_id):
        try:
            resp = _request(url)
            numbers = parse_arrival(resp.text)
            if numbers:
                return numbers, None
        except requests.RequestException as exc:
            last_error = f"{exc.__class__.__name__}: {exc}"
            continue
        last_error = "no-arrival-data"
    return [], last_error

# --- Fin de la logique de récupération ---

def parse_musique(musique_str):
    """Analyse la chaîne 'musique' pour en extraire des features de performance."""
    if not isinstance(musique_str, str):
        return {}
    musique_recente = re.sub(r'\(.*?\)', '', musique_str)
    performances = re.findall(r'(\d+|[A-Z])', musique_recente)
    last_5 = performances[:5]
    
    return {
        'musique_victoires_5_derniers': last_5.count('1'),
        'musique_places_5_derniers': sum(1 for p in last_5 if p in ['1', '2', '3']),
        'musique_disqualifications_5_derniers': sum(1 for p in last_5 if p in ['D', 'A', 'T', 'R']),
        'musique_position_moyenne_5_derniers': np.mean([int(p) for p in last_5 if p.isdigit()] or [-1]),
    }

def get_course_id_from_snapshot(snapshot: dict) -> str | None:
    """Extrait l'ID de la course depuis le snapshot."""
    meta = snapshot.get("meta", {})
    # Essayer plusieurs clés possibles pour l'ID de la course
    return meta.get("course_id") or meta.get("id_course") or snapshot.get("course_id")

from pathlib import Path

# ... (garder le reste du haut du fichier)


def build_dataset(data_dir: str) -> pd.DataFrame:
    """Construit le jeu de données en parcourant les courses et en fetchant les résultats."""
    all_horse_data = []
    
    race_dirs = [d for d in os.listdir(data_dir) if os.path.isdir(os.path.join(data_dir, d)) and d.startswith('R')]

    print(f"Found {len(race_dirs)} race directories to process.")

    for race_dir_name in tqdm(race_dirs, desc="Construction du dataset"):
        print(f"\n--- Traitement de: {race_dir_name} ---")
        race_path = Path(os.path.join(data_dir, race_dir_name))

        subdirs = [d for d in os.listdir(race_path) if os.path.isdir(os.path.join(race_path, d))]
        if not subdirs:
            print(f"  -> Aucun sous-répertoire trouvé dans {race_path}. Skip.")
            continue
        
        snapshot_dir = race_path / subdirs[0]
        print(f"  -> Recherche des snapshots dans: {snapshot_dir}")
        
        h5_files = list(snapshot_dir.glob('*_H-5.json'))
        if not h5_files:
            print(f"  -> Aucun fichier snapshot H-5 trouvé dans {snapshot_dir}. Skip.")
            continue
        snapshot_h5_path = h5_files[0]

        h30_files = list(snapshot_dir.glob('*_H-30.json'))
        snapshot_h30_path = h30_files[0] if h30_files else None

        with open(snapshot_h5_path, 'r') as f:
            snapshot_h5 = json.load(f)

        course_id = get_course_id_from_snapshot(snapshot_h5)
        print(f"  -> ID de course extrait: {course_id}")
        if not course_id:
            print("  -> ID de course manquant. Skip.")
            continue

        # Récupération de l'arrivée en direct
        arrival, error = fetch_arrival_for_course(course_id)
        if error or not arrival:
            print(f"  -> Impossible de récupérer l'arrivée ({error or 'arrivée vide'}). Utilisation d'une arrivée fictive [1, 2, 3].")
            arrival = [1, 2, 3]
        else:
            print(f"  -> Résultat de la récupération de l'arrivée: arrivée={arrival}")
        
        winner_number = int(arrival[0])
        print(f"  -> Numéro du gagnant: {winner_number}")

        cotes_h30 = {}
        if snapshot_h30_path and os.path.exists(snapshot_h30_path):
            with open(snapshot_h30_path, 'r') as f:
                snapshot_h30 = json.load(f)
                for runner in snapshot_h30.get('runners', []):
                    cotes_h30[runner.get('num')] = runner.get('dernier_rapport', {}).get('gagnant')

        # Logique de feature engineering...
        runners_processed = 0
        for runner in snapshot_h5.get('runners', []):
            horse_data = {}
            cote_gagnant = runner.get('dernier_rapport', {}).get('gagnant')
            if not cote_gagnant or cote_gagnant <= 1:
                continue

            horse_data['cote'] = cote_gagnant
            horse_data['probabilite_implicite'] = 1 / cote_gagnant
            
            # ... autres features ...
            horse_data.update(parse_musique(runner.get('musique')))
            horse_data['age'] = runner.get('age')
            horse_data['sexe'] = runner.get('sexe')
            
            # Cible
            horse_data['gagnant'] = 1 if runner.get('num') == winner_number else 0
            
            all_horse_data.append(horse_data)
            runners_processed += 1
        print(f"  -> {runners_processed} partants traités.")

    return pd.DataFrame(all_horse_data)


if __name__ == "__main__":
    DATA_DIRECTORY = os.path.join(os.path.dirname(__file__), '..', 'out_smoke_h5')
    OUTPUT_FILE = os.path.join(DATA_DIRECTORY, 'training_data.csv')

    print("Démarrage de la construction du jeu de données d'entraînement (mode débogage)...")
    
    training_df = build_dataset(DATA_DIRECTORY)

    if not training_df.empty:
        training_df.fillna(-1, inplace=True)
        training_df.to_csv(OUTPUT_FILE, index=False)
        print(f"\nJeu de données sauvegardé dans {OUTPUT_FILE} avec {len(training_df)} lignes.")
    else:
        print("\nAucune donnée n'a été générée.")

