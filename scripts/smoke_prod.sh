#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# --- Configuration ---
# L'utilisateur doit fournir l'URL du service.
if [ -z "$1" ]; then
    echo "Usage: $0 <SERVICE_URL>"
    echo "Example: $0 https://hippique-orchestrator-XXXXX.run.app"
    exit 1
fi
SERVICE_URL="$1"

# La clé API est lue depuis l'environnement. NE PAS la hardcoder ici.
if [ -z "${HIPPIQUE_INTERNAL_API_KEY}" ]; then
    echo "Error: HIPPIQUE_INTERNAL_API_KEY environment variable is not set."
    exit 1
fi

echo "--- Running smoke tests against $SERVICE_URL ---"

# --- Test /pronostics endpoint ---
echo "Testing /pronostics UI endpoint..."
RESPONSE=$(curl -s "$SERVICE_URL/pronostics")
if echo "$RESPONSE" | grep -q "Hippique Orchestrator - Pronostics"; then
    echo "✅ /pronostics UI is accessible."
else
    echo "❌ /pronostics UI test failed. Response:"
    echo "$RESPONSE"
    exit 1
fi

# --- Test /api/pronostics endpoint ---
echo "Testing /api/pronostics endpoint..."
API_PRONOSTICS_RESPONSE=$(curl -s "$SERVICE_URL/api/pronostics?date=$(date +%F)")
if echo "$API_PRONOSTICS_RESPONSE" | jq . > /dev/null; then
    echo "✅ /api/pronostics returned valid JSON."
else
    echo "❌ /api/pronostics test failed. Response:"
    echo "$API_PRONOSTICS_RESPONSE"
    exit 1
fi

# --- Test /schedule endpoint (without API key - expected 403) ---
echo "Testing /schedule endpoint without API key (expecting 403 Forbidden)..."
SCHEDULE_NO_KEY_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$SERVICE_URL/schedule" -X POST -H "Content-Type: application/json" -d '{"dry_run": true}')
if [ "$SCHEDULE_NO_KEY_STATUS" -eq 403 ]; then
    echo "✅ /schedule without API key returned 403 Forbidden as expected."
else
    echo "❌ /schedule without API key failed. Expected 403, got $SCHEDULE_NO_KEY_STATUS."
    exit 1
fi

# --- Test /schedule endpoint (with valid API key - expected 200) ---
echo "Testing /schedule endpoint with valid API key (expecting 200 OK)..."
SCHEDULE_WITH_KEY_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$SERVICE_URL/schedule" -X POST -H "Content-Type: application/json" -H "X-API-KEY: ${HIPPIQUE_INTERNAL_API_KEY}" -d '{"dry_run": true, "date": "$(date +%F)"}')
if [ "$SCHEDULE_WITH_KEY_STATUS" -eq 200 ]; then
    echo "✅ /schedule with valid API key returned 200 OK as expected."
else
    echo "❌ /schedule with valid API key failed. Expected 200, got $SCHEDULE_WITH_KEY_STATUS."
    exit 1
fi

echo "--- All smoke tests passed successfully! ---"