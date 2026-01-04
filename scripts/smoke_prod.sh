#!/bin/bash
#
# Smoke Test pour l'application Hippique Orchestrator
#
# Usage:
#   export HIPPIQUE_INTERNAL_API_KEY="votre_cle_api"
#   ./scripts/smoke_prod.sh https://votre-app-url.run.app

set -e # Quitte immédiatement si une commande échoue

# --- Validation des entrées ---

TARGET_URL=${1}
if [ -z "${TARGET_URL}" ]; then
    echo "❌ Erreur : L'URL de l'application doit être fournie en premier argument."
    echo "   Usage: $0 https://votre-app-url.run.app"
    exit 1
fi

# Supprimer la barre oblique finale si présente
TARGET_URL=${TARGET_URL%/}

echo "✅ URL Cible : ${TARGET_URL}"
echo "---"

# --- Tests ---

echo "1. Test du Health Check [/health]..."
curl -s -f -L "${TARGET_URL}/health" > /dev/null
echo "   ✅ OK"

echo "2. Test de l'UI principale [/pronostics]..."
curl -s -f -L "${TARGET_URL}/pronostics" | grep -q "<title>Hippique Orchestrator - Pronostics</title>"
echo "   ✅ OK"

echo "3. Test de l'API des pronostics [/api/pronostics]..."
curl -s -f -L "${TARGET_URL}/api/pronostics?date=$(date +%F)" | grep -q '"ok": true'
echo "   ✅ OK"

echo "4. Test de sécurité sur /schedule (sans authentification)..."
STATUS_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${TARGET_URL}/schedule")
if [ "${STATUS_CODE}" -ne 403 ]; then
    echo "   ❌ ERREUR : Le statut HTTP attendu était 403, mais a reçu ${STATUS_CODE}"
    exit 1
fi
echo "   ✅ OK (reçu ${STATUS_CODE} comme attendu)"

echo "5. Test de sécurité sur /schedule (avec authentification)..."
if [ -z "${HIPPIQUE_INTERNAL_API_KEY}" ]; then
    echo "   ⚠️  ATTENTION : La variable d'environnement HIPPIQUE_INTERNAL_API_KEY n'est pas définie. Test sauté."
else
    # dry_run=true pour ne pas créer de vraies tâches
    curl -s -f -X POST \
        -H "Content-Type: application/json" \
        -H "X-API-Key: ${HIPPIQUE_INTERNAL_API_KEY}" \
        -d '{"dry_run": true}' \
        "${TARGET_URL}/schedule" > /dev/null
    echo "   ✅ OK"
fi

echo ""
echo "🎉 Tous les tests de smoke ont réussi !"
exit 0
