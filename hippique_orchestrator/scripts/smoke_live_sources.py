import json
import logging
import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

# Configuration des logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Mockups pour les modules non disponibles dans ce script stand-alone
# Dans un environnement de production, ces imports seraient réels.
# from hippique_orchestrator.programme_provider import get_programme
# from hippique_orchestrator.source_registry import get_source
# from hippique_orchestrator.config import get_config

# --- Début des Mocks ---
# Ces mocks simulent le comportement des vrais modules pour permettre au script de fonctionner.

def get_config():
    """ Mock de la configuration. """
    return {"secondary_odds_provider": "pmu_odds_source"} # Exemple de fallback

def get_programme(date: datetime.date) -> List[Dict[str, Any]]:
    """ Mock du programme des courses. """
    logging.info(f"MOCK: Récupération du programme pour le {date}")
    return [
        {"reunion_id": "R1", "course_id": "C1", "race_url": "http://example.com/r1c1"},
        {"reunion_id": "R1", "course_id": "C2", "race_url": "http://example.com/r1c2"},
        {"reunion_id": "R1", "course_id": "C3", "race_url": "http://example.com/r1c3"},
        {"reunion_id": "R1", "course_id": "C4", "race_url": "http://example.com/r1c4"},
    ]

class MockSource:
    """ Classe mock pour simuler les sources de données. """
    def __init__(self, name: str, success: bool = True):
        self._name = name
        self._success = success

    def fetch_snapshot(self, race_url: str) -> Dict[str, Any]:
        """ Mock de fetch_snapshot. """
        if not self._success:
            raise ConnectionError(f"MOCK: {self._name} - Impossible de fetch le snapshot.")
        logging.info(f"MOCK: {self._name} - Snapshot récupéré pour {race_url}")
        return {
            "partants": [
                {"num": 1, "nom": "CHEVAL A"},
                {"num": 2, "nom": "CHEVAL B"},
                {"num": 3, "nom": "CHEVAL C"},
                {"num": 4, "nom": "CHEVAL D"},
            ]
        }

    def fetch_odds(self, snapshot: Dict[str, Any]) -> Dict[int, Dict[str, float]]:
        """ Mock de fetch_odds. """
        if not self._success:
            raise ConnectionError(f"MOCK: {self._name} - Impossible de fetch les cotes.")
        logging.info(f"MOCK: {self._name} - Cotes récupérées.")
        # Simule une variation des cotes
        if "H5" in self._name:
            return {
                1: {"win": 2.5, "place": 1.2},
                2: {"win": 4.0, "place": 1.8},
                3: {"win": 8.0, "place": 2.5},
                # Le 4 n'a pas de cote pour simuler une donnée manquante
            }
        else: # H30
            return {
                1: {"win": 2.2, "place": 1.1},
                2: {"win": 4.5, "place": 1.9},
                3: {"win": 7.5, "place": 2.4},
                4: {"win": 15.0, "place": 4.0},
            }

def get_source(name: str) -> MockSource:
    """ Mock du registre de sources. """
    # Simule un échec de la source primaire pour tester le fallback
    if name == "zeturf_odds_source":
        return MockSource("zeturf_odds_source_H5", success=True)
    elif name == "pmu_odds_source":
         return MockSource("pmu_odds_source_H30", success=True)
    return MockSource(name)

# --- Fin des Mocks ---


def calculate_odds_place_ratio(merged_data: Dict[int, Dict]) -> float:
    """ Calcule le ratio moyen des cotes placées sur les cotes gagnantes. """
    ratios = []
    for _num, data in merged_data.items():
        if data.get("H5_win_odds") and data.get("H5_place_odds") and data["H5_win_odds"] > 0:
            ratios.append(data["H5_place_odds"] / data["H5_win_odds"])
    return sum(ratios) / len(ratios) if ratios else 0.0

def calculate_drift_coverage(merged_data: Dict[int, Dict]) -> float:
    """ Calcule la proportion de partants ayant des cotes H30 et H5. """
    count = 0
    total_partants = len(merged_data)
    if total_partants == 0:
        return 0.0
    for _num, data in merged_data.items():
        if data.get("H30_win_odds") and data.get("H5_win_odds"):
            count += 1
    return count / total_partants

def calculate_quality_score(drift_coverage: float, place_ratio: float) -> float:
    """ Calcule un score de qualité composite. """
    # Un score simple pour commencer: la couverture du drift est le plus important.
    # On peut y ajouter d'autres métriques avec des poids.
    # Exemple: Poids de 80% pour la couverture, 20% pour le ratio de place.
    return 0.8 * drift_coverage + 0.2 * (1 - abs(0.5 - place_ratio))


def fetch_with_retries(source_name: str, snapshot: Dict[str, Any], retries: int = 2, delay: int = 5) -> Optional[Dict[int, Dict[str, float]]]:
    """ Tente de récupérer les cotes avec plusieurs essais. """
    last_exception = None
    for i in range(retries):
        try:
            source = get_source(source_name)
            return source.fetch_odds(snapshot)
        except Exception as e:
            last_exception = e
            logging.warning(f"Tentative {i+1}/{retries} échouée pour {source_name}. Erreur: {e}. Nouvel essai dans {delay}s.")
            # time.sleep(delay) # En production, on attendrait
    logging.error(f"Toutes les tentatives ont échoué pour {source_name}. Erreur finale: {last_exception}")
    return None

def run_smoke_test():
    """ Corps principal du script de smoke test. """
    logging.info("Démarrage du smoke test des sources de données live.")
    
    # Création du dossier artifacts s'il n'existe pas
    artifacts_dir = Path("artifacts")
    artifacts_dir.mkdir(exist_ok=True)
    
    output_path = artifacts_dir / "smoke_live_metrics.json"
    results: Dict[str, Any] = {"races": [], "global_decision": {}}
    
    today = datetime.date.today()
    try:
        programme = get_programme(today)
    except Exception as e:
        logging.critical(f"Impossible de récupérer le programme du jour. Arrêt du test. Erreur: {e}")
        results["error"] = "Programme non disponible"
        with open(output_path, "w") as f:
            json.dump(results, f, indent=4)
        return

    races_to_process = programme[:3]
    logging.info(f"Traitement des {len(races_to_process)} premières courses du jour.")

    all_races_metrics = []

    for race_info in races_to_process:
        race_id = f"{race_info['reunion_id']}{race_info['course_id']}"
        logging.info(f"--- Traitement de la course {race_id} ---")
        race_metrics = {"race_id": race_id, "status": "PENDING"}

        try:
            # 1. Fetch snapshot de base
            snapshot_source = get_source("boturfers_snapshot_source")
            snapshot = snapshot_source.fetch_snapshot(race_info['race_url'])
            
            # Initialisation du conteneur de données mergées
            merged_data: Dict[int, Dict] = {p["num"]: {"nom": p["nom"]} for p in snapshot["partants"]}

            # 2. Fetch odds H30 (primaire: Zeturf)
            odds_h30 = fetch_with_retries("zeturf_odds_source", snapshot)
            
            # 3. Logique de fallback pour H30
            if not odds_h30:
                logging.warning("Source primaire (Zeturf H30) échouée. Tentative avec le fallback.")
                config = get_config()
                fallback_provider = config.get("secondary_odds_provider")
                if fallback_provider:
                    odds_h30 = fetch_with_retries(fallback_provider, snapshot)
                    race_metrics["h30_source"] = fallback_provider if odds_h30 else "ECHEC_FALLBACK"
                else:
                    race_metrics["h30_source"] = "ECHEC_SANS_FALLBACK"
            else:
                race_metrics["h30_source"] = "zeturf_odds_source"

            # 4. Fetch odds H5 (primaire: Zeturf)
            odds_h5 = fetch_with_retries("zeturf_odds_source", snapshot)
            race_metrics["h5_source"] = "zeturf_odds_source" if odds_h5 else "ECHEC"

            # 5. Merge des données
            if odds_h30:
                for num, o in odds_h30.items():
                    if num in merged_data:
                        merged_data[num]["H30_win_odds"] = o.get("win")
                        merged_data[num]["H30_place_odds"] = o.get("place")
            
            if odds_h5:
                for num, o in odds_h5.items():
                    if num in merged_data:
                        merged_data[num]["H5_win_odds"] = o.get("win")
                        merged_data[num]["H5_place_odds"] = o.get("place")

            # 6. Calcul des KPIs
            odds_coverage_h5 = len(odds_h5) / len(snapshot["partants"]) if odds_h5 else 0.0
            drift_cov = calculate_drift_coverage(merged_data)
            place_ratio = calculate_odds_place_ratio(merged_data)
            quality_score = calculate_quality_score(drift_cov, place_ratio)

            race_metrics.update({
                "odds_coverage_h5": round(odds_coverage_h5, 2),
                "drift_coverage": round(drift_cov, 2),
                "odds_place_ratio_h5": round(place_ratio, 2),
                "quality_score": round(quality_score, 2),
                "merged_data": merged_data,
            })
            
            # 7. Décision par course
            if quality_score < 0.85 or odds_coverage_h5 < 0.90 or drift_cov < 0.80:
                race_metrics["status"] = "ABSTENTION"
                reasons = []
                if quality_score < 0.85:
                    reasons.append(f"quality_score trop bas ({quality_score:.2f} < 0.85)")
                if odds_coverage_h5 < 0.90:
                    reasons.append(f"odds_coverage_h5 insuffisante ({odds_coverage_h5:.2f} < 0.90)")
                if drift_cov < 0.80:
                    reasons.append(f"drift_coverage insuffisant ({drift_cov:.2f} < 0.80)")
                race_metrics["reason"] = ", ".join(reasons)
                logging.warning(f"Course {race_id}: ABSTENTION. Raison: {race_metrics['reason']}")
            else:
                race_metrics["status"] = "GO"
                logging.info(f"Course {race_id}: GO")

        except Exception as e:
            logging.error(f"Erreur inattendue lors du traitement de la course {race_id}: {e}", exc_info=True)
            race_metrics["status"] = "FAILED"
            race_metrics["reason"] = str(e)

        results["races"].append(race_metrics)
        all_races_metrics.append(race_metrics)

    # Décision globale
    if not all_races_metrics or any(r["status"] == "FAILED" for r in all_races_metrics):
        global_status = "NO-GO"
        global_reason = "Au moins une course a échoué ou le programme est vide."
    elif any(r["status"] == "ABSTENTION" for r in all_races_metrics):
        global_status = "NO-GO"
        global_reason = "Au moins une course est en abstention à cause de la qualité des données."
    else:
        global_status = "GO"
        global_reason = "Toutes les courses analysées ont un score de qualité suffisant."
    
    results["global_decision"] = {"status": global_status, "reason": global_reason}
    logging.info(f"Décision globale du smoke test: {global_status} - {global_reason}")

    # Écriture du rapport
    with open(output_path, "w") as f:
        json.dump(results, f, indent=4, default=str)
    
    logging.info(f"Smoke test terminé. Rapport disponible dans {output_path}")

if __name__ == "__main__":
    run_smoke_test()