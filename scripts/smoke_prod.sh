#!/bin/bash
set -euo pipefail

# Production Smoke Test for Hippique Orchestrator
#
# This script performs basic checks to ensure the deployed service is alive
# and responding correctly.
#
# USAGE:
#   export API_KEY="your-api-key"
#   bash scripts/smoke_prod.sh <service_base_url>
#
# EXAMPLE:
#   bash scripts/smoke_prod.sh https://hippique-orchestrator-prod.app

# --- Configuration ---
if [ -z "$1" ]; then
    echo "Error: Service base URL is required."
    echo "Usage: bash scripts/smoke_prod.sh <service_base_url>"
    exit 1
fi

BASE_URL="$1"
# Remove trailing slash if present
BASE_URL="${BASE_URL%/}"

if [ -z "${API_KEY:-}" ]; then
    echo "Error: API_KEY environment variable is not set."
    exit 1
fi

echo "Smoke testing service at: ${BASE_URL}"

# --- Helper Functions ---
function check_health() {
    local url="${BASE_URL}/health"
    echo -n "1. Checking /health endpoint... "
    
    response=$(curl --fail -s -H "X-API-Key: ${API_KEY}" "${url}")
    
    status=$(echo "${response}" | jq -r '.status')
    
    if [ "${status}" == "healthy" ]; then
        echo "OK"
    else
        echo "FAIL"
        echo "   Response was: ${response}"
        exit 1
    fi
}

function check_pronostics() {
    local url="${BASE_URL}/api/pronostics"
    echo -n "2. Checking /api/pronostics endpoint... "
    
    response=$(curl --fail -s -H "X-API-Key: ${API_KEY}" "${url}")
    
    ok_status=$(echo "${response}" | jq -r '.ok')
    pronostics_count=$(echo "${response}" | jq '.pronostics | length')
    
    if [ "${ok_status}" == "true" ] && [ "${pronostics_count}" -ge 0 ]; then
        echo "OK (${pronostics_count} pronostics found)"
    else
        echo "FAIL"
        echo "   ok_status: ${ok_status}"
        echo "   pronostics_count: ${pronostics_count}"
        echo "   Response was: ${response}"
        exit 1
    fi
}


# --- Main Execution ---
check_health
check_pronostics

echo
echo "Smoke test PASSED."
exit 0