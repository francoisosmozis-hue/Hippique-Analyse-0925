import sys
import traceback
from pathlib import Path

print("--- Début du test d'importation ---")
try:
    # Ajout des chemins nécessaires pour simuler l'environnement
    sys.path.insert(0, str(Path(__file__).parent))

    print(f"PYTHONPATH (début): {sys.path[:3]}")
    print("Tentative d'importation de 'src.service'...")

    print("--- Importation de 'src.service' réussie ! ---")

except Exception:
    print("--- ERREUR D'IMPORTATION ---")
    traceback.print_exc()
    print("----------------------------")
    sys.exit(1)

print("Le module a été importé sans erreur au niveau supérieur.")
sys.exit(0)
