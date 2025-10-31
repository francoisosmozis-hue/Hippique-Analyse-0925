#!/bin/bash
set -e

# ============================================================================
# Script de test local - Orchestrateur Hippique
# ============================================================================
# Usage: ./test_local.sh [--no-auth]
# ============================================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}🧪 Tests locaux de l'orchestrateur hippique${NC}"
echo "=============================================="

# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------
BASE_URL=${BASE_URL:-"http://localhost:8080"}
AUTH_HEADER=""

if [ "$1" == "--no-auth" ]; then
    echo -e "${YELLOW}Mode sans authentification${NC}"
else
    if [ ! -z "$SERVICE_URL" ]; then
        BASE_URL=$SERVICE_URL
        echo -e "${YELLOW}Mode production avec authentification${NC}"
        TOKEN=$(gcloud auth print-identity-token --audiences=$SERVICE_URL 2>/dev/null || echo "")
        if [ -z "$TOKEN" ]; then
            echo -e "${RED}❌ Impossible d'obtenir le token. Utilisez --no-auth pour les tests locaux.${NC}"
            exit 1
        fi
        AUTH_HEADER="Authorization: Bearer $TOKEN"
    else
        echo -e "${YELLOW}Mode local sans authentification${NC}"
    fi
fi

echo "Base URL: $BASE_URL"
echo ""

# ----------------------------------------------------------------------------
# Test 1: Healthcheck
# ----------------------------------------------------------------------------
echo -e "${BLUE}Test 1: Healthcheck${NC}"
RESPONSE=$(curl -s -w "\n%{http_code}" -H "$AUTH_HEADER" "$BASE_URL/healthz")
HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | head -n-1)

if [ "$HTTP_CODE" == "200" ]; then
    echo -e "${GREEN}✅ Healthcheck OK${NC}"
    echo "   Response: $BODY"
else
    echo -e "${RED}❌ Healthcheck failed (HTTP $HTTP_CODE)${NC}"
    echo "   Response: $BODY"
    exit 1
fi

echo ""

# ----------------------------------------------------------------------------
# Test 2: Schedule endpoint (dry-run avec date future)
# ----------------------------------------------------------------------------
echo -e "${BLUE}Test 2: POST /schedule (date future pour éviter exécutions réelles)${NC}"

# Date dans 7 jours
FUTURE_DATE=$(date -d "+7 days" +%Y-%m-%d 2>/dev/null || date -v+7d +%Y-%m-%d)

PAYLOAD="{\"date\":\"$FUTURE_DATE\",\"mode\":\"tasks\"}"

echo "Payload: $PAYLOAD"

RESPONSE=$(curl -s -w "\n%{http_code}" \
    -H "$AUTH_HEADER" \
    -H "Content-Type: application/json" \
    -X POST \
    -d "$PAYLOAD" \
    "$BASE_URL/schedule")

HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | head -n-1)

if [ "$HTTP_CODE" == "200" ]; then
    echo -e "${GREEN}✅ Schedule endpoint OK${NC}"
    
    # Parser le JSON (si jq disponible)
    if command -v jq &> /dev/null; then
        RACES_COUNT=$(echo "$BODY" | jq -r '.races_count // "N/A"')
        TASKS_COUNT=$(echo "$BODY" | jq -r '.tasks_scheduled // "N/A"')
        echo "   Races trouvées: $RACES_COUNT"
        echo "   Tâches programmées: $TASKS_COUNT"
    else
        echo "   Response: $BODY"
    fi
else
    echo -e "${RED}❌ Schedule failed (HTTP $HTTP_CODE)${NC}"
    echo "   Response: $BODY"
    
    # Si 404, c'est peut-être normal (pas de courses dans 7 jours)
    if [ "$HTTP_CODE" == "404" ]; then
        echo -e "${YELLOW}⚠️  Aucune course trouvée pour $FUTURE_DATE (normal)${NC}"
    fi
fi

echo ""

# ----------------------------------------------------------------------------
# Test 3: POST /run (simulation avec URL bidon)
# ----------------------------------------------------------------------------
echo -e "${BLUE}Test 3: POST /run (simulation - peut échouer si URL invalide)${NC}"

RUN_PAYLOAD='{
  "course_url": "https://www.zeturf.fr/fr/course/2025-10-16/R1C1-test",
  "phase": "H30",
  "date": "2025-10-16"
}'

echo "Payload: $RUN_PAYLOAD"

RESPONSE=$(curl -s -w "\n%{http_code}" \
    -H "$AUTH_HEADER" \
    -H "Content-Type: application/json" \
    -X POST \
    -d "$RUN_PAYLOAD" \
    "$BASE_URL/run")

HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | head -n-1)

if [ "$HTTP_CODE" == "200" ]; then
    echo -e "${GREEN}✅ Run endpoint OK${NC}"
    
    if command -v jq &> /dev/null; then
        OK=$(echo "$BODY" | jq -r '.ok // false')
        RC=$(echo "$BODY" | jq -r '.returncode // "N/A"')
        echo "   Succès: $OK"
        echo "   Return code: $RC"
    else
        echo "   Response: $BODY"
    fi
else
    echo -e "${YELLOW}⚠️  Run failed (HTTP $HTTP_CODE) - Normal si URL de test invalide${NC}"
    echo "   Response: ${BODY:0:200}..."
fi

echo ""

# ----------------------------------------------------------------------------
# Test 4: Vérification structure logs (si local)
# ----------------------------------------------------------------------------
if [[ "$BASE_URL" == *"localhost"* ]]; then
    echo -e "${BLUE}Test 4: Vérification logs structurés${NC}"
    
    # Lancer une requête et vérifier le format des logs
    echo "Déclenchement d'une requête pour observer les logs..."
    curl -s -H "$AUTH_HEADER" "$BASE_URL/healthz" > /dev/null
    
    echo -e "${GREEN}✅ Vérifiez que les logs affichés sont en format JSON${NC}"
    echo "   Exemple attendu: {\"timestamp\":\"...\",\"severity\":\"INFO\",\"message\":\"...\"}"
fi

echo ""

# ----------------------------------------------------------------------------
# Résumé
# ----------------------------------------------------------------------------
echo -e "${BLUE}================================================${NC}"
echo -e "${GREEN}✅ TESTS TERMINÉS${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""
echo -e "${YELLOW}📝 Prochaines étapes:${NC}"
echo "   1. Si tests OK en local, déployer sur Cloud Run:"
echo "      ./scripts/deploy_cloud_run.sh"
echo ""
echo "   2. Créer le scheduler quotidien:"
echo "      ./scripts/create_scheduler_0900.sh"
echo ""
echo "   3. Tester en production:"
echo "      SERVICE_URL=https://... ./test_local.sh"
echo ""
echo -e "${YELLOW}🔍 Commandes de monitoring utiles:${NC}"
echo "   # Logs Cloud Run"
echo "   gcloud logging read \"resource.type=cloud_run_revision\" --limit 50"
echo ""
echo "   # Tâches en attente"
echo "   gcloud tasks list --queue=horse-racing-queue --location=europe-west1"
echo ""
echo "   # Jobs Scheduler"
echo "   gcloud scheduler jobs list --location=europe-west1"
echo ""
echo -e "${GREEN}🐴 Happy testing!${NC}"
