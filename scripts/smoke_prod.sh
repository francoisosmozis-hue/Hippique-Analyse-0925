#!/bin/bash
#
# Smoke test script for production-like environments.
#
# This script checks the health and accessibility of key endpoints.
# It requires the target base URL to be provided as the first argument.
# For authenticated endpoints, it uses the HIPPIQUE_INTERNAL_API_KEY environment variable.
#
# Usage:
#   export HIPPIQUE_INTERNAL_API_KEY="your-secret-key"
#   ./scripts/smoke_prod.sh https://your-cloud-run-service-url.a.run.app

set -euo pipefail

# --- Configuration ---
BASE_URL="${1:-}"
if [ -z "$BASE_URL" ]; then
    echo "Error: Base URL is required. Please provide it as the first argument."
    echo "Usage: $0 https://your-service-url.a.run.app"
    exit 1
fi

# Remove trailing slash if present
BASE_URL="${BASE_URL%/}"

# Use a default date (today) for API checks
DATE=$(date +%F)

# --- Colors for output ---
C_RED='\033[0;31m'
C_GREEN='\033[0;32m'
C_YELLOW='\033[0;33m'
C_BLUE='\033[0;34m'
C_NC='\033[0m' # No Color

# --- Helper Functions ---
info() {
    echo -e "${C_BLUE}[INFO]${C_NC} $1"
}

success() {
    echo -e "${C_GREEN}[PASS]${C_NC} $1"
}

fail() {
    echo -e "${C_RED}[FAIL]${C_NC} $1"
    # Optionally, exit immediately on failure
    # exit 1
}

warn() {
    echo -e "${C_YELLOW}[WARN]${C_NC} $1"
}

# --- Test Functions ---

# Test 1: Check the main UI page (/pronostics)
test_ui_page() {
    info "Checking UI page: GET ${BASE_URL}/pronostics"
    response=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/pronostics")
    if [ "$response" -eq 200 ]; then
        success "UI page is accessible (HTTP 200)."
    else
        fail "UI page returned HTTP ${response}. Expected 200."
    fi
}

# Test 2: Check the public API endpoint (/api/pronostics)
test_public_api() {
    info "Checking public API: GET ${BASE_URL}/api/pronostics?date=${DATE}"
    response=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/api/pronostics?date=${DATE}")
    if [ "$response" -eq 200 ]; then
        success "Public API is accessible (HTTP 200)."
        # Optional: Add a check for JSON content validity
        # body=$(curl -s "${BASE_URL}/api/pronostics?date=${DATE}")
        # if echo "$body" | jq -e '.ok == true' > /dev/null; then
        #     success "Public API response contains 'ok: true'."
        # else
        #     fail "Public API response JSON is not valid or missing 'ok: true'."
        # fi
    else
        fail "Public API returned HTTP ${response}. Expected 200."
    fi
}

# Test 3: Check /schedule endpoint without authentication
test_schedule_unauthenticated() {
    info "Checking /schedule (unauthenticated): POST ${BASE_URL}/schedule"
    response=$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE_URL}/schedule")
    if [ "$response" -eq 401 ] || [ "$response" -eq 403 ]; then
        success "Unauthenticated /schedule access is correctly forbidden (HTTP ${response})."
    else
        fail "Unauthenticated /schedule returned HTTP ${response}. Expected 401 or 403."
    fi
}

# Test 4: Check /schedule endpoint with authentication
test_schedule_authenticated() {
    info "Checking /schedule (authenticated): POST ${BASE_URL}/schedule"
    if [ -z "${HIPPIQUE_INTERNAL_API_KEY:-}" ]; then
        warn "HIPPIQUE_INTERNAL_API_KEY is not set. Skipping authenticated /schedule test."
        return
    fi

    response=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
        -H "Content-Type: application/json" \
        -H "X-API-Key: ${HIPPIQUE_INTERNAL_API_KEY}" \
        -d '{"dry_run": true}' \
        "${BASE_URL}/schedule")

    if [ "$response" -eq 200 ]; then
        success "Authenticated /schedule access is successful (HTTP 200)."
    else
        fail "Authenticated /schedule returned HTTP ${response}. Expected 200."
    fi
}


# --- Main Execution ---
echo "--- Starting Production Smoke Test for ${BASE_URL} ---"
test_ui_page
test_public_api
test_schedule_unauthenticated
test_schedule_authenticated
echo "--- Smoke Test Finished ---"
