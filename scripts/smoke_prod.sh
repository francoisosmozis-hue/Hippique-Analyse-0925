#!/bin/bash

# Configuration
BASE_URL="https://hippique-orchestrator-1084663881709.europe-west1.run.app"
TODAY_DATE=$(date +%F) # YYYY-MM-DD format

echo "--- Starting Smoke Tests for Hippique Orchestrator ($BASE_URL) ---"
echo "Testing date: $TODAY_DATE"

# --- Test 1: UI /pronostics endpoint ---
echo -e "\n--- Test 1: UI /pronostics (HTML) ---"
UI_RESPONSE=$(curl -s "$BASE_URL/pronostics")
if echo "$UI_RESPONSE" | grep -q "Hippique Orchestrator - Pronostics"; then
    echo "✅ UI /pronostics endpoint is accessible and contains expected title."
else
    echo "❌ UI /pronostics endpoint FAILED. Response did not contain expected title."
    echo "Response excerpt:"
    echo "$UI_RESPONSE" | head -n 10
    exit 1
fi

# --- Test 2: API /api/pronostics endpoint (JSON) ---
echo -e "\n--- Test 2: API /api/pronostics (JSON) ---"
API_RESPONSE=$(curl -s "$BASE_URL/api/pronostics?date=$TODAY_DATE")

# Validate JSON and check for 'ok: true'
if echo "$API_RESPONSE" | jq -e '.ok == true' > /dev/null; then
    echo "✅ API /api/pronostics endpoint is accessible and returned 'ok: true'."
    echo "API Response excerpt:"
    echo "$API_RESPONSE" | jq . | head -n 15
else
    echo "❌ API /api/pronostics endpoint FAILED. Response did not contain 'ok: true' or was not valid JSON."
    echo "Response excerpt:"
    echo "$API_RESPONSE" | head -n 20
    exit 1
fi

echo -e "\n--- All Smoke Tests Completed Successfully ---"
exit 0
