#!/bin/bash
set -e

# --- Configuration ---
HOST="0.0.0.0"
PORT="8080"
HEALTH_URL="http://127.0.0.1:$PORT/healthz"
SERVER_LOG="server.log"
UVICORN_PID=0

# URL de course ZEturf pour le test (exemple)
# R1C3 à Pau le 20/06/2024
DEFAULT_COURSE_URL="https://www.zeturf.fr/fr/course/2024-06-20/R1C3-pau-prix-de-la-federation-des-courses-du-sud-ouest"
OUTPUT_DIR="data/R1C3"

# --- Fonctions ---
cleanup() {
    echo "[INFO] Nettoyage..."
    if [ $UVICORN_PID -ne 0 ]; then
        echo "[INFO] Arrêt du serveur Uvicorn (PID: $UVICORN_PID)..."
        kill $UVICORN_PID
        wait $UVICORN_PID 2>/dev/null
    fi
    rm -f $SERVER_LOG
    # Supprimer les artefacts générés pour garantir l'idempotence
    # rm -f snapshot_H5.json chronos.csv *_je.csv p_finale.json analysis_H5.json tracking.csv
    rm -rf "$OUTPUT_DIR"
    echo "[INFO] Nettoyage terminé."
}

trap cleanup EXIT

# --- Installation ---
echo "[INFO] Installation des dépendances depuis requirements.txt..."
pip install -r requirements.txt --quiet
echo "[INFO] Installation du projet en mode éditable..."
pip install -e . --quiet

# --- Démarrage ---
echo "[INFO] Démarrage du serveur FastAPI en arrière-plan..."
python src/service.py > $SERVER_LOG 2>&1 &
UVICORN_PID=$!
echo "[INFO] Serveur démarré avec le PID: $UVICORN_PID."

# --- Attente et Test de Santé ---
echo "[INFO] Attente du démarrage du serveur..."
for i in {1..10}; do
    if curl -s -f $HEALTH_URL > /dev/null; then
        echo "[OK] Le serveur répond sur $HEALTH_URL."
        break
    fi
    echo "[INFO] Tentative $i/10: le serveur n'est pas encore prêt."
    sleep 1
done

if ! curl -s -f $HEALTH_URL > /dev/null; then
    echo "[ERREUR] Le serveur n'a pas démarré correctement."
    cat $SERVER_LOG
    exit 1
fi

# --- Exécution du Pipeline ---
echo "[INFO] Lancement de l'analyse pour la phase H30..."
PYTHONPATH=src python analyse_courses_du_jour_enrichie.py --phase H30 --reunion-url "$DEFAULT_COURSE_URL" --source geny --data-dir data

echo "[INFO] Lancement de l'analyse pour la phase H5 avec un budget de 5€..."
# Note: analyse_courses_du_jour_enrichie.py est un wrapper qui finit par appeler runner_chain.py
PYTHONPATH=src python analyse_courses_du_jour_enrichie.py --phase H5 --budget 5 --reunion-url "$DEFAULT_COURSE_URL" --source geny --data-dir data

# --- Vérification des Artefacts ---
echo "[INFO] Vérification des fichiers de sortie attendus dans $OUTPUT_DIR..."
EXPECTED_FILES=(
    "chronos.csv"
    "p_finale.json"
    "analysis_H5.json"
    "tracking.csv"
    "*_H-5.json"
    "*_je.csv"
)
ALL_FOUND=true

for f in "${EXPECTED_FILES[@]}"; do
    # ls gère les wildcards (glob patterns) directement.
    if ls "$OUTPUT_DIR/$f" 1> /dev/null 2>&1; then
        echo "[OK] Fichier/pattern trouvé: $f"
    else
        echo "[ERREUR] Fichier/pattern manquant: $f dans $OUTPUT_DIR"
        ALL_FOUND=false
    fi
done

if ! $ALL_FOUND; then
    echo "[ERREUR] Tous les artefacts attendus n'ont pas été produits."
    exit 1
fi

echo ""
echo "[OK] pipeline testé."
