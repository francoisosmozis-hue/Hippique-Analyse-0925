# Force l'ajout de la racine du repo dans sys.path au démarrage de pytest
import sys, pathlib
root = pathlib.Path(__file__).resolve().parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))
