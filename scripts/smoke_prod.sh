#!/bin/bash
set -e

# Vérifier que l'URL de production est fournie
if [ -z "$1" ]; then
  echo "Usage: $0 <production_url>"
  exit 1
fi
URL=$1

echo "### Smoke Test - Health Check ###"
curl -fL "$URL/health" | grep '"status":"healthy"'

echo -e "\n### Smoke Test - API Pronostics (JSON) ###"
curl -fL "$URL/api/pronostics" | grep '"ok":true'

echo -e "\n### Smoke Test - UI Pronostics (HTML) ###"
curl -fL "$URL/pronostics" | grep '<title>Hippique Orchestrator - Pronostics</title>'

echo -e "\n### Smoke Test - /schedule (sans API Key) ###"
# Nous attendons un code 403, donc nous ne voulons pas que -f échoue le script
response_code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$URL/schedule" -H "Content-Type: application/json" -d '{"date": "2025-01-01"}')
if [ "$response_code" -eq 403 ]; then
  echo "OK: Received expected 403 Forbidden"
else
  echo "FAIL: Expected 403, but received $response_code"
  exit 1
fi

if [ -z "$HIPPIQUE_INTERNAL_API_KEY" ]; then
  echo -e "\n### SKIP: /schedule (avec API Key) - HIPPIQUE_INTERNAL_API_KEY non définie ###"
else
  echo -e "\n### Smoke Test - /schedule (avec API Key) ###"
  curl -f -X POST "$URL/schedule" -H "Content-Type: application/json" -H "X-API-Key: $HIPPIQUE_INTERNAL_API_KEY" -d '{"date": "2025-01-01"}' | grep '"ok":true'
fi

echo -e "\n### Tous les smoke tests ont réussi ! ###"
