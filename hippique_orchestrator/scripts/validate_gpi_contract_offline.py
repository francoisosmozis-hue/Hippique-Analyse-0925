import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

from hippique_orchestrator.data_contract import compute_odds_place_ratio
from hippique_orchestrator.scrapers.zeturf import ZeturfSource
from hippique_orchestrator.scripts import online_fetch_zeturf  # For mocking _http_get

# Configuration des seuils
MIN_QUALITY_SCORE = 0.85
MIN_ODDS_PLACE_RATIO = 0.90

# Chemin vers la fixture HTML ZEturf
ZETURF_FIXTURE_PATH = Path("tests/fixtures/zeturf_race.html")


async def validate_zeturf_gpi_contract_offline():
    """
    Valide le contrat GPI hors ligne pour les données ZEturf
    en utilisant une fixture HTML et en vérifiant les seuils de qualité.
    """
    print(f"--- Validation du contrat GPI hors ligne pour ZEturf ({ZETURF_FIXTURE_PATH}) ---")

    if not ZETURF_FIXTURE_PATH.exists():
        print(f"Erreur: Fichier fixture non trouvé: {ZETURF_FIXTURE_PATH}")
        sys.exit(1)

    zeturf_html_content = ZETURF_FIXTURE_PATH.read_text(encoding="utf-8")

    # Mock _http_get for fetch_race_snapshot_full to run offline
    with patch("hippique_orchestrator.scripts.online_fetch_zeturf._http_get", return_value=zeturf_html_content):
        
        zeturf_source = ZeturfSource() # Create instance
        try:
            # Call the real fetch_snapshot, it will use the real asyncio.to_thread
            # and the mocked _http_get
            snapshot = await zeturf_source.fetch_snapshot(
                "https://www.zeturf.fr/fr/course/2026-01-16/R1C1-Prix-d-Amerique"
            )

            # --- Vérification du Quality Score ---
            quality = snapshot.quality
            print(f"Quality Score: {quality['score']:.2f} (Status: {quality['status']})")
            print(f"Quality Reason: {quality['reason']}")

            if quality["score"] < MIN_QUALITY_SCORE or quality["status"] == "FAILED":
                print(f"Erreur: Quality Score ({quality['score']:.2f}) inférieur au seuil requis ({MIN_QUALITY_SCORE:.2f}) ou statut FAILED.")
                sys.exit(1)

            # --- Vérification du Odds Place Ratio ---
            place_odds_dict = {
                runner.nom: runner.odds_place
                for runner in snapshot.runners
                if runner.odds_place is not None
            }
            total_runners = len(snapshot.runners)

            if total_runners == 0:
                print("Erreur: Aucun partant trouvé pour calculer le odds place ratio.")
                sys.exit(1)

            odds_place_ratio = compute_odds_place_ratio(place_odds_dict, total_runners)
            print(f"Odds Place Ratio: {odds_place_ratio:.2f}")

            if odds_place_ratio < MIN_ODDS_PLACE_RATIO:
                print(f"Erreur: Odds Place Ratio ({odds_place_ratio:.2f}) inférieur au seuil requis ({MIN_ODDS_PLACE_RATIO:.2f}).")
                sys.exit(1)

            print("Validation GPI hors ligne ZEturf réussie: Tous les seuils sont respectés.")
            sys.exit(0)

        except Exception as e:
            print(f"Erreur critique lors de la validation GPI hors ligne ZEturf: {e}")
            sys.exit(1)

if __name__ == "__main__":
    asyncio.run(validate_zeturf_gpi_contract_offline())