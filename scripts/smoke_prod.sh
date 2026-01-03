#!/bin/bash

# Configuration
URL_PROD="${URL_PROD:-""}"
API_KEY="${HIPPIQUE_INTERNAL_API_KEY:-""}"

# Fonctions de test
assert_status() {
    local url=$1
    local expected_status=$2
    local extra_args=$3
    local description=$4

    # shellcheck disable=SC2086
    local status_code=$(curl -s -o /dev/null -w "%{http_code}" $extra_args "$url")

    if [ "$status_code" -eq "$expected_status" ]; then
        echo "[OK] $description (Status: $status_code)"
    else
        echo "[FAIL] $description (Expected: $expected_status, Got: $status_code)"
        exit 1
    fi
}

# --- Début des Tests ---

if [ -z "$URL_PROD" ]; then
    echo "[FAIL] La variable d'environnement URL_PROD n'est pas définie."
    exit 1
fi

echo "--- Démarrage des Smoke Tests sur $URL_PROD ---"

# 1. Test de l'endpoint public /api/pronostics
assert_status "${URL_PROD}/api/pronostics?date=$(date +%F)" 200 "" "Endpoint /api/pronostics"

# 2. Test de l'interface utilisateur /pronostics
assert_status "${URL_PROD}/pronostics" 200 "" "Endpoint /pronostics UI"

# 3. Test de /schedule sans clé API (accès refusé)
assert_status "${URL_PROD}/schedule" 403 "-X POST" "/schedule (sans API Key)"

# 4. Test de /schedule avec clé API (accès autorisé)
if [ -z "$API_KEY" ]; then
    echo "[SKIP] HIPPIQUE_INTERNAL_API_KEY non définie. Le test /schedule avec authentification est sauté."
else
    assert_status "${URL_PROD}/schedule" 200 "-X POST -H \"X-API-KEY: ${API_KEY}\"" "/schedule (avec API Key)"
fi

echo "--- Smoke Tests terminés avec succès ---"
