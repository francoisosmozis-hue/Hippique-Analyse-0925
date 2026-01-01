#!/bin/bash

# Script de Smoke Test pour l'application Hippique Orchestrator
#
# Utilisation : ./scripts/smoke_prod.sh https://votre-url.com

set -e # Quitte immédiatement si une commande échoue

# --- Fonctions utilitaires ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

fail() {
    echo -e "${RED}[FAIL]${NC} $1" >&2
    exit 1
}

check_status() {
    local url=$1
    local expected_status=$2
    local extra_args=$3
    local description=$4

    echo -n "-> Test: $description..."
    
    # shellcheck disable=SC2086
    local status_code=$(curl -o /dev/null -s -w "%{http_code}" "$url" $extra_args)
    
    if [ "$status_code" -eq "$expected_status" ]; then
        echo -e " ${GREEN}OK ($status_code)${NC}"
    else
        echo -e " ${RED}ERREUR (Reçu: $status_code, Attendu: $expected_status)${NC}"
        exit 1
    fi
}


# --- Validation des arguments ---
BASE_URL=$1
if [ -z "$BASE_URL" ]; then
    fail "URL de base manquante. Utilisation : $0 https://votre-url.com"
fi

info "Lancement des smoke tests pour l'URL de base : $BASE_URL"

# --- Exécution des tests ---

# 1. Test de l'endpoint UI
check_status "$BASE_URL/pronostics" 200 "-L" "Endpoint UI (/pronostics)"

# 2. Test de l'endpoint API public
check_status "$BASE_URL/api/pronostics?date=$(date +%F)" 200 "-L" "Endpoint API (/api/pronostics)"

# 3. Test de l'endpoint sécurisé SANS clé API
# Nous nous attendons à un 403 Forbidden car la sécurité est gérée par l'API Key.
# Un 401 Unauthorized serait aussi acceptable.
echo -n "-> Test: Endpoint sécurisé (/schedule) SANS clé..."
status_no_key=$(curl -o /dev/null -s -w "%{http_code}" -X POST "$BASE_URL/schedule")
if [ "$status_no_key" -eq 403 ] || [ "$status_no_key" -eq 401 ]; then
    echo -e " ${GREEN}OK (Accès refusé comme attendu avec code $status_no_key)${NC}"
else
    echo -e " ${RED}ERREUR (Reçu: $status_no_key, Attendu: 401 ou 403)${NC}"
    exit 1
fi

# 4. Test de l'endpoint sécurisé AVEC clé API
if [ -z "$HIPPIQUE_INTERNAL_API_KEY" ]; then
    warn "Variable d'environnement HIPPIQUE_INTERNAL_API_KEY non définie. Skip du test d'accès authentifié."
else
    # Le endpoint /schedule attend un payload, même vide, pour certaines configurations.
    # On envoie un POST avec un corps vide et le header d'authentification.
    check_status "$BASE_URL/schedule" 200 "-X POST -H 'Content-Type: application/json' -H \"X-API-Key: $HIPPIQUE_INTERNAL_API_KEY\" -d '{}'" "Endpoint sécurisé (/schedule) AVEC clé"
fi

info "Tous les smoke tests ont réussi."
exit 0
