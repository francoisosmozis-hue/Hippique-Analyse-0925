#!/bin/bash
#
# Smoke Test pour le service Hippique Orchestrator en production.
#
# Ce script vérifie que les endpoints critiques sont en ligne et se comportent
# comme attendu après un déploiement.
#
# Prérequis :
#   - Les variables d'environnement SERVICE_URL et HIPPIQUE_INTERNAL_API_KEY doivent être définies.
#   - Les outils `curl` et `jq` doivent être installés.

set -e # Quitte immédiatement si une commande échoue

# --- Fonctions utilitaires ---
print_status() {
    GREEN='\033[0;32m'
    RED='\033[0;31m'
    NC='\033[0m' # No Color
    if [ "$2" -eq 0 ]; then
        echo -e "[ ${GREEN}OK${NC} ] $1"
    else
        echo -e "[ ${RED}FAIL${NC} ] $1"
    fi
}

check_var() {
    if [ -z "${!1}" ]; then
        echo "Erreur : La variable d'environnement $1 n'est pas définie."
        exit 1
    fi
}

# --- Vérification des prérequis ---
check_var "SERVICE_URL"
check_var "HIPPIQUE_INTERNAL_API_KEY"

echo "--- Début des Smoke Tests pour ${SERVICE_URL} ---"

# --- Test 1: Endpoint /health ---
echo -n "1. Test /health ... "
status_code=$(curl --silent --output /dev/null --write-out "%{{http_code}}" "${{SERVICE_URL}}/health")
if [ "$status_code" -eq 200 ]; then
    print_status "/health" 0
else
    print_status "/health (Code: ${status_code})" 1
    exit 1
fi

# --- Test 2: Endpoint /api/pronostics ---
echo -n "2. Test /api/pronostics ... "
response=$(curl --silent -H "Accept: application/json" "${{SERVICE_URL}}/api/pronostics")
ok_status=$(echo "$response" | jq -r .ok)
if [ "$ok_status" == "true" ]; then
    print_status "/api/pronostics" 0
else
    print_status "/api/pronostics (Réponse invalide)" 1
    echo "Réponse reçue :"
    echo "$response" | jq
    exit 1
fi

# --- Test 3: Endpoint /schedule (sans authentification) ---
echo -n "3. Test /schedule (403 Forbidden attendu) ... "
schedule_status_403=$(curl --silent --output /dev/null --write-out "%{{http_code}}" -X POST "${{SERVICE_URL}}/schedule")
if [ "$schedule_status_403" -eq 403 ]; then
    print_status "/schedule sans clé" 0
else
    print_status "/schedule sans clé (Code: ${schedule_status_403})" 1
    exit 1
fi

# --- Test 4: Endpoint /schedule (avec authentification) ---
echo -n "4. Test /schedule (200 OK attendu) ... "
schedule_status_200=$(curl --silent --output /dev/null --write-out "%{{http_code}}" -X POST -H "X-API-Key: ${{HIPPIQUE_INTERNAL_API_KEY}}" "${{SERVICE_URL}}/schedule?dry_run=true")
if [ "$schedule_status_200" -eq 200 ]; then
    print_status "/schedule avec clé" 0
else
    print_status "/schedule avec clé (Code: ${schedule_status_200})" 1
    exit 1
fi

echo -e "\n${GREEN}--- Tous les smoke tests ont réussi ---${NC}"